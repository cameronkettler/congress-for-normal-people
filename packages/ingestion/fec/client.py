from typing import Any

import httpx

from packages.shared.config import Settings, get_settings


class FECClient:
    base_url = "https://api.open.fec.gov/v1"

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()

    async def get_candidate_finance_patterns(self, sponsor_name: str) -> dict[str, Any]:
        if not self.settings.fec_api_key:
            return {
                "source": "demo",
                "sponsor": sponsor_name,
                "patterns": [
                    "Technology PAC giving appears relevant to the policy area.",
                    "Small-dollar contributions are not available in demo mode.",
                ],
                "top_industries": ["Technology", "Professional Services", "Education"],
                "confidence": "low",
            }

        async with httpx.AsyncClient(timeout=self.settings.fec_api_timeout_seconds) as client:
            response = await client.get(
                f"{self.base_url}/candidates/search/",
                params={"api_key": self.settings.fec_api_key, "q": sponsor_name, "per_page": 5},
            )
            response.raise_for_status()
            results = response.json().get("results", [])

        return {
            "source": "openfec",
            "sponsor": sponsor_name,
            "candidate_matches": results,
            "patterns": ["Review candidate committee receipts and PAC support for material patterns."],
            "confidence": "medium" if results else "low",
        }
