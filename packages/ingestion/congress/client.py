from datetime import date
from typing import Any

import httpx

from packages.shared.config import Settings, get_settings
from packages.shared.schemas import BillRecord, SourceReference
from packages.shared.topics import TOPIC_KEYWORDS


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
            response = await client.get(url, params={"api_key": self.settings.congress_api_key})
            response.raise_for_status()
            payload = response.json().get("bill", {})

        title = payload.get("title") or payload.get("shortTitle") or f"{bill_type.upper()} {number}"
        latest_action = (payload.get("latestAction") or {}).get("text", "No latest action available")
        sponsor = (payload.get("sponsors") or [{}])[0].get("fullName", "Unknown sponsor")
        introduced = payload.get("introducedDate")
        introduced_date = date.fromisoformat(introduced) if introduced else None

        return BillRecord(
            congress_bill_id=bill_id,
            title=title,
            summary=payload.get("summary", "Summary unavailable from Congress.gov."),
            sponsor=sponsor,
            introduced_date=introduced_date,
            latest_action=latest_action,
            status=payload.get("status", "introduced"),
            topic=self.classify_topic(title),
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

    def _parse_bill_id(self, bill_id: str) -> tuple[str, str, str]:
        normalized = bill_id.lower().replace(".", "").replace(" ", "-")
        parts = normalized.split("-")
        if len(parts) == 3:
            bill_type, number, congress = parts
            return congress, bill_type, number
        return "119", parts[0], parts[-1]

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
