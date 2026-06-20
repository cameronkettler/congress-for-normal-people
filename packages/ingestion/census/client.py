from dataclasses import dataclass
from typing import Any

import httpx

from packages.shared.config import Settings, get_settings


@dataclass(frozen=True)
class ResolvedDistrict:
    state: str
    congressional_district: str
    matched_address: str
    confidence: str


class CensusGeocoderClient:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()

    async def resolve_address(self, address: str) -> ResolvedDistrict:
        url = f"{self.settings.census_geocoder_base_url}/geographies/onelineaddress"
        async with httpx.AsyncClient(timeout=self.settings.census_geocoder_timeout_seconds) as client:
            response = await client.get(
                url,
                params={
                    "address": address,
                    "benchmark": "Public_AR_Current",
                    "vintage": "Current_Current",
                    "layers": "all",
                    "format": "json",
                },
            )
            response.raise_for_status()

        matches = response.json().get("result", {}).get("addressMatches", [])
        if not matches:
            raise ValueError("Census Geocoder could not match that address.")

        match = matches[0]
        geographies = match.get("geographies", {})
        district = self._first_geography(geographies, "Congressional Districts")
        state = self._first_geography(geographies, "States")
        if not district or not state:
            raise ValueError("Census Geocoder did not return a congressional district.")

        return ResolvedDistrict(
            state=state.get("STUSAB") or state.get("BASENAME", ""),
            congressional_district=str(district.get("CD119") or district.get("BASENAME") or "").zfill(2),
            matched_address=match.get("matchedAddress", address),
            confidence="address_match",
        )

    def _first_geography(self, geographies: dict[str, Any], key: str) -> dict[str, Any] | None:
        values = geographies.get(key)
        if isinstance(values, list) and values and isinstance(values[0], dict):
            return values[0]
        return None
