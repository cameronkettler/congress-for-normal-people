from datetime import date
from html.parser import HTMLParser
from typing import Any

import httpx

from packages.shared.config import Settings, get_settings
from packages.shared.schemas import BillRecord, RepresentativeRecord, SourceReference
from packages.shared.topics import TOPIC_KEYWORDS


class _SummaryTextParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []

    def handle_data(self, data: str) -> None:
        text = data.strip()
        if text:
            self.parts.append(text)

    def text(self) -> str:
        return " ".join(self.parts)


class CongressClient:
    """Congress.gov provider boundary.

    The client returns stable demo data when no API key is configured so local demos and tests remain
    deterministic.
    """

    base_url = "https://api.congress.gov/v3"

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()

    async def get_bill(self, bill_id: str) -> BillRecord:
        if not self.settings.congress_api_key:
            return self._demo_bill(bill_id)

        congress, bill_type, number = self._parse_bill_id(bill_id)
        url = f"{self.base_url}/bill/{congress}/{bill_type}/{number}"
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(self.settings.congress_api_timeout_seconds)
        ) as client:
            response = await client.get(url, params=self._request_params())
            response.raise_for_status()
            payload = response.json().get("bill", {})
            summary = await self._get_bill_summary(client, congress, bill_type, number, payload)

        title = payload.get("title") or payload.get("shortTitle") or f"{bill_type.upper()} {number}"
        latest_action = (payload.get("latestAction") or {}).get("text", "No latest action available")
        sponsor = (payload.get("sponsors") or [{}])[0].get("fullName", "Unknown sponsor")
        introduced = payload.get("introducedDate")
        introduced_date = date.fromisoformat(introduced) if introduced else None

        return BillRecord(
            congress_bill_id=bill_id,
            title=title,
            summary=summary,
            sponsor=sponsor,
            introduced_date=introduced_date,
            latest_action=latest_action,
            status=payload.get("status", "introduced"),
            topic=self._topic_from_payload(payload, f"{title} {summary}"),
            sources=[
                SourceReference(
                    label="Congress.gov bill endpoint",
                    url=url,
                    confidence="high",
                )
            ],
        )

    async def get_sponsor(self, sponsor_name: str) -> dict[str, Any]:
        return {
            "name": sponsor_name,
            "party": "Unknown",
            "state": "Unknown",
            "committees": ["Committee data requires Congress.gov member expansion"],
        }

    async def get_current_house_member(self, state: str, district: str) -> RepresentativeRecord | None:
        if not self.settings.congress_api_key:
            return RepresentativeRecord(
                name="Demo Representative",
                chamber="House",
                party="Unknown",
                state=state,
                district=district,
            )

        url = f"{self.base_url}/member/congress/119/{state.upper()}/{int(district)}"
        async with httpx.AsyncClient(timeout=httpx.Timeout(self.settings.congress_api_timeout_seconds)) as client:
            response = await client.get(url, params={**self._request_params(), "currentMember": "true"})
            response.raise_for_status()
            members = response.json().get("members", [])
        if not members:
            return None
        return self._representative_from_member(members[0], "House")

    async def list_current_senators(self, state: str) -> list[RepresentativeRecord]:
        if not self.settings.congress_api_key:
            return [
                RepresentativeRecord(name="Demo Senator A", chamber="Senate", party="Unknown", state=state),
                RepresentativeRecord(name="Demo Senator B", chamber="Senate", party="Unknown", state=state),
            ]

        url = f"{self.base_url}/member/congress/119/{state.upper()}"
        async with httpx.AsyncClient(timeout=httpx.Timeout(self.settings.congress_api_timeout_seconds)) as client:
            response = await client.get(url, params={**self._request_params(), "currentMember": "true"})
            response.raise_for_status()
            members = response.json().get("members", [])
        return [
            representative
            for member in members
            if (representative := self._representative_from_member(member, self._member_chamber(member))).chamber == "Senate"
        ][:2]

    async def list_bill_cosponsors(self, bill_id: str) -> list[dict[str, Any]]:
        if not self.settings.congress_api_key:
            return []

        congress, bill_type, number = self._parse_bill_id(bill_id)
        url = f"{self.base_url}/bill/{congress}/{bill_type}/{number}/cosponsors"
        async with httpx.AsyncClient(timeout=httpx.Timeout(self.settings.congress_api_timeout_seconds)) as client:
            response = await client.get(url, params=self._request_params())
            response.raise_for_status()
            return response.json().get("cosponsors", [])

    async def list_house_votes_for_bill(self, bill_id: str) -> list[dict[str, Any]]:
        if not self.settings.congress_api_key:
            return []

        congress, bill_type, number = self._parse_bill_id(bill_id)
        bill_type = bill_type.upper()
        votes: list[dict[str, Any]] = []
        async with httpx.AsyncClient(timeout=httpx.Timeout(self.settings.congress_api_timeout_seconds)) as client:
            for session in ("2", "1"):
                offset = 0
                while offset < 1000:
                    url = f"{self.base_url}/house-vote/{congress}/{session}"
                    response = await client.get(
                        url,
                        params={**self._request_params(), "limit": 250, "offset": offset},
                    )
                    response.raise_for_status()
                    page = [self._normalize_house_vote(item) for item in self._house_vote_items(response.json())]
                    votes.extend(
                        vote
                        for vote in page
                        if str(vote.get("legislationType", "")).upper() == bill_type
                        and str(vote.get("legislationNumber", "")) == number
                    )
                    if len(page) < 250:
                        break
                    offset += 250
        return sorted(votes, key=lambda vote: str(vote.get("startDate", "")), reverse=True)

    async def get_house_member_vote(self, vote: dict[str, Any], representative: RepresentativeRecord) -> dict[str, Any] | None:
        if not self.settings.congress_api_key:
            return None

        congress = str(vote.get("congress", ""))
        session = self._vote_session(vote)
        vote_number = self._vote_roll_call_number(vote)
        if not congress or not session or not vote_number:
            return None

        url = f"{self.base_url}/house-vote/{congress}/{session}/{vote_number}/members"
        async with httpx.AsyncClient(timeout=httpx.Timeout(self.settings.congress_api_timeout_seconds)) as client:
            response = await client.get(url, params={**self._request_params(), "limit": 250})
            response.raise_for_status()
            payload = response.json().get("houseRollCallVoteMemberVotes", {})

        for item in self._house_member_vote_items(payload):
            if self._vote_matches_representative(item, representative):
                return {
                    "vote_cast": item.get("voteCast", ""),
                    "vote_question": payload.get("voteQuestion") or vote.get("voteQuestion", ""),
                    "result": payload.get("result") or vote.get("result", ""),
                    "roll_call_number": payload.get("rollCallNumber") or vote_number,
                    "start_date": payload.get("startDate") or vote.get("startDate", ""),
                }
        return None

    async def list_recent_bills(self, limit: int = 10) -> list[BillRecord]:
        if not self.settings.congress_api_key:
            return [self._demo_bill(f"hr-{1200 + index}-119") for index in range(1, limit + 1)]

        url = f"{self.base_url}/bill"
        try:
            async with httpx.AsyncClient(
                timeout=httpx.Timeout(self.settings.congress_recent_api_timeout_seconds)
            ) as client:
                response = await client.get(
                    url,
                    params={
                        "api_key": self.settings.congress_api_key,
                        "format": "json",
                        "sort": "updateDate+desc",
                        "limit": limit,
                    },
                )
                response.raise_for_status()
                bills = response.json().get("bills", [])
        except (httpx.TimeoutException, httpx.HTTPError):
            return []

        records: list[BillRecord] = []
        for item in bills:
            congress = item.get("congress")
            bill_type = item.get("type", "").lower()
            number = item.get("number")
            records.append(
                BillRecord(
                    congress_bill_id=f"{bill_type}-{number}-{congress}",
                    title=item.get("title", f"{bill_type.upper()} {number}"),
                    summary=item.get("summary", "Summary pending."),
                    sponsor="Unknown",
                    introduced_date=None,
                    latest_action=(item.get("latestAction") or {}).get("text", "Recently updated"),
                    status="introduced",
                    topic=self.classify_topic(item.get("title", "")),
                    sources=[SourceReference(label="Congress.gov recent bills", url=url, confidence="high")],
                )
            )
        return records

    def classify_topic(self, text: str) -> str:
        lowered = text.lower()
        for topic, keywords in TOPIC_KEYWORDS.items():
            if any(keyword in lowered for keyword in keywords):
                return topic
        return "Uncategorized"

    async def _get_bill_summary(
        self,
        client: httpx.AsyncClient,
        congress: str,
        bill_type: str,
        number: str,
        payload: dict[str, Any],
    ) -> str:
        embedded = self._clean_summary_text(payload.get("summary"))
        if embedded:
            return embedded

        url = self._summary_url(payload, congress, bill_type, number)
        try:
            response = await client.get(url, params=self._request_params())
            response.raise_for_status()
        except httpx.HTTPError:
            return "Summary unavailable from Congress.gov."

        summaries = response.json().get("summaries", [])
        if not summaries:
            return "Summary unavailable from Congress.gov."

        latest = max(summaries, key=lambda item: item.get("updateDate") or item.get("actionDate") or "")
        return self._clean_summary_text(latest.get("text")) or "Summary unavailable from Congress.gov."

    def _summary_url(self, payload: dict[str, Any], congress: str, bill_type: str, number: str) -> str:
        summaries = payload.get("summaries") or {}
        if isinstance(summaries, dict) and summaries.get("url"):
            return summaries["url"]
        return f"{self.base_url}/bill/{congress}/{bill_type}/{number}/summaries"

    def _clean_summary_text(self, value: Any) -> str:
        if not isinstance(value, str) or not value.strip():
            return ""
        parser = _SummaryTextParser()
        parser.feed(value)
        text = parser.text() or value
        return " ".join(text.split())

    def _request_params(self) -> dict[str, str]:
        return {"api_key": self.settings.congress_api_key or "", "format": "json"}

    def _topic_from_payload(self, payload: dict[str, Any], fallback_text: str) -> str:
        policy_area = payload.get("policyArea") or {}
        if isinstance(policy_area, dict) and policy_area.get("name"):
            return policy_area["name"]
        return self.classify_topic(fallback_text)

    def _representative_from_member(self, member: dict[str, Any], chamber: str) -> RepresentativeRecord:
        terms = member.get("terms", {}).get("item", []) if isinstance(member.get("terms"), dict) else []
        latest_term = terms[-1] if terms else {}
        return RepresentativeRecord(
            name=member.get("directOrderName") or member.get("name") or member.get("invertedOrderName") or "Unknown member",
            chamber=chamber,
            party=member.get("partyName") or latest_term.get("partyName") or "Unknown",
            state=member.get("state") or latest_term.get("stateCode") or "",
            district=str(member.get("district") or latest_term.get("district") or "") or None,
            bioguide_id=member.get("bioguideId"),
            official_url=member.get("officialUrl"),
        )

    def _member_chamber(self, member: dict[str, Any]) -> str:
        terms = member.get("terms", {}).get("item", []) if isinstance(member.get("terms"), dict) else []
        latest = terms[-1] if terms else {}
        chamber = latest.get("chamber", "")
        return "Senate" if "Senate" in chamber else "House"

    def _parse_bill_id(self, bill_id: str) -> tuple[str, str, str]:
        normalized = bill_id.lower().replace(".", "").replace(" ", "-")
        parts = normalized.split("-")
        if len(parts) == 3:
            bill_type, number, congress = parts
            return congress, bill_type, number
        return "119", parts[0], parts[-1]

    def _house_vote_items(self, payload: dict[str, Any]) -> list[dict[str, Any]]:
        raw_items = payload.get("houseRollCallVotes", [])
        if isinstance(raw_items, dict):
            raw_items = raw_items.get("item", [])
        if not isinstance(raw_items, list):
            return []
        return [self._unwrap_item(item, "houseRollCallVote") for item in raw_items]

    def _house_member_vote_items(self, payload: dict[str, Any]) -> list[dict[str, Any]]:
        raw_items = payload.get("results", [])
        if isinstance(raw_items, dict):
            raw_items = raw_items.get("item", [])
        if not isinstance(raw_items, list):
            return []
        return [self._unwrap_item(item, "item") for item in raw_items]

    def _unwrap_item(self, item: Any, key: str) -> dict[str, Any]:
        if isinstance(item, dict) and isinstance(item.get(key), dict):
            return item[key]
        return item if isinstance(item, dict) else {}

    def _vote_session(self, vote: dict[str, Any]) -> str:
        value = vote.get("sessionNumber") or vote.get("sessioNumber") or vote.get("session")
        return str(value or "")

    def _vote_roll_call_number(self, vote: dict[str, Any]) -> str:
        value = vote.get("rollCallNumber") or vote.get("voteNumber")
        if value:
            return str(value)
        identifier = str(vote.get("identifier", ""))
        session = self._vote_session(vote)
        congress = str(vote.get("congress", ""))
        prefix = f"{congress}{session}"
        if identifier.startswith(prefix) and len(identifier) > len(prefix) + 4:
            return str(int(identifier[len(prefix) + 4 :]))
        return ""

    def _normalize_house_vote(self, vote: dict[str, Any]) -> dict[str, Any]:
        normalized = dict(vote)
        if "sessionNumber" not in normalized and self._vote_session(normalized):
            normalized["sessionNumber"] = self._vote_session(normalized)
        if "rollCallNumber" not in normalized and self._vote_roll_call_number(normalized):
            normalized["rollCallNumber"] = self._vote_roll_call_number(normalized)
        if "legislationNumber" in normalized:
            normalized["legislationNumber"] = str(normalized["legislationNumber"])
        return normalized

    def _vote_matches_representative(
        self,
        vote_item: dict[str, Any],
        representative: RepresentativeRecord,
    ) -> bool:
        if representative.bioguide_id and vote_item.get("bioguideId") == representative.bioguide_id:
            return True

        vote_name = " ".join(
            part
            for part in [str(vote_item.get("firstName", "")), str(vote_item.get("lastName", ""))]
            if part
        ).casefold()
        rep_name = representative.name.casefold()
        return bool(vote_name and (vote_name in rep_name or rep_name in vote_name))

    def _demo_bill(self, bill_id: str) -> BillRecord:
        title = "Responsible Artificial Intelligence in Public Services Act"
        topic = self.classify_topic(title)
        return BillRecord(
            congress_bill_id=bill_id,
            title=title,
            summary=(
                "Establishes standards for federal agency use of artificial intelligence, including "
                "risk assessments, procurement transparency, and public reporting requirements."
            ),
            sponsor="Rep. Jordan Lee",
            introduced_date=date(2026, 2, 12),
            latest_action="Referred to the House Committee on Oversight and Accountability.",
            status="introduced",
            topic=topic,
            sources=[
                SourceReference(
                    label="Demo Congress.gov response",
                    url="https://api.congress.gov",
                    confidence="medium",
                )
            ],
        )
