from typing import Any

import httpx

from packages.shared.config import Settings, get_settings


class LobbyingDisclosureClient:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()

    async def search_activity(self, query: str) -> dict[str, Any]:
        if not self.settings.lobbying_disclosure_base_url or not self.settings.lobbying_api_live:
            return self._demo_activity(query)

        url = f"{self.settings.lobbying_disclosure_base_url}/filings/"
        headers = self._auth_headers()
        try:
            async with httpx.AsyncClient(timeout=self.settings.lobbying_api_timeout_seconds) as client:
                response = await client.get(
                    url,
                    headers=headers,
                    params={"filing_specific_lobbying_issues": query, "page_size": 5},
                )
                response.raise_for_status()
                results = [
                    self._normalize_filing(item)
                    for item in response.json().get("results", [])
                    if isinstance(item, dict)
                ]
        except httpx.HTTPError:
            return self._demo_activity(query)

        return {
            "source": "lobbying_disclosure_api",
            "query": query,
            "registrations": results,
            "confidence": "medium" if results else "low",
        }

    def _normalize_filing(self, filing: dict[str, Any]) -> dict[str, Any]:
        client = filing.get("client") if isinstance(filing.get("client"), dict) else {}
        registrant = filing.get("registrant") if isinstance(filing.get("registrant"), dict) else {}
        lobbying_activities = filing.get("lobbying_activities") or []
        issues = [
            activity.get("general_issue_code_display") or activity.get("general_issue_code")
            for activity in lobbying_activities
            if isinstance(activity, dict)
        ]
        return {
            **filing,
            "client_name": filing.get("client_name") or client.get("name"),
            "registrant_name": filing.get("registrant_name") or registrant.get("name"),
            "issue": filing.get("issue")
            or filing.get("filing_specific_lobbying_issues")
            or ", ".join(issue for issue in issues if issue),
        }

    def _auth_headers(self) -> dict[str, str]:
        if not self.settings.lobbying_disclosure_api_key:
            return {}
        return {"Authorization": f"Token {self.settings.lobbying_disclosure_api_key}"}

    def _demo_activity(self, query: str) -> dict[str, Any]:
        return {
            "source": "demo",
            "query": query,
            "registrations": [
                {
                    "client_name": "Public Sector Technology Coalition",
                    "issue": "Federal AI procurement and transparency standards",
                },
                {
                    "client_name": "Civil Liberties Policy Network",
                    "issue": "Algorithmic accountability and privacy safeguards",
                },
            ],
            "confidence": "low",
        }
