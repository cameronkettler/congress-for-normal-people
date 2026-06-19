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
            async with httpx.AsyncClient(timeout=20) as client:
                response = await client.get(
                    url,
                    headers=headers,
                    params={"filing_specific_lobbying_issues": query, "page_size": 5},
                )
                response.raise_for_status()
                results = response.json().get("results", [])
        except httpx.HTTPError:
            return self._demo_activity(query)

        return {
            "source": "lobbying_disclosure_api",
            "query": query,
            "registrations": results,
            "confidence": "medium" if results else "low",
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
