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
        attempts = self._oneline_attempts(address)
        return await self._resolve_attempts(attempts)

    async def resolve_location(
        self,
        *,
        street_address: str = "",
        address_line_2: str = "",
        city: str = "",
        state: str = "",
        zip_code: str = "",
    ) -> ResolvedDistrict:
        attempts = self._address_attempts(street_address, address_line_2, city, state, zip_code)
        return await self._resolve_attempts(attempts)

    async def _resolve_attempts(self, attempts: list[dict[str, Any]]) -> ResolvedDistrict:
        async with httpx.AsyncClient(timeout=self.settings.census_geocoder_timeout_seconds) as client:
            for attempt in attempts:
                response = await client.get(attempt["url"], params=attempt["params"])
                response.raise_for_status()
                if resolved := self._resolved_from_payload(response.json(), attempt["label"]):
                    return resolved
        raise ValueError("Census Geocoder could not match that address to a congressional district.")

    def _address_attempts(
        self,
        street_address: str,
        address_line_2: str,
        city: str,
        state: str,
        zip_code: str,
    ) -> list[dict[str, Any]]:
        base_params = self._base_params()
        street_variants = self._street_variants(street_address)
        line_2 = " ".join(address_line_2.split())
        street_attempts = street_variants[:]
        if line_2:
            street_attempts.extend(f"{street} {line_2}" for street in street_variants)

        attempts: list[dict[str, Any]] = []
        for street in street_attempts:
            if street and (city or state or zip_code):
                attempts.append(
                    {
                        "label": "address_match",
                        "url": f"{self.settings.census_geocoder_base_url}/geographies/address",
                        "params": {
                            **base_params,
                            "street": street,
                            "city": city,
                            "state": state,
                            "zip": zip_code,
                        },
                    }
                )

        for street in street_attempts or [""]:
            oneline = " ".join(part for part in [street, city, state, zip_code] if part).strip()
            if oneline:
                attempts.extend(self._oneline_attempts(oneline))
        return attempts

    def _oneline_attempts(self, address: str) -> list[dict[str, Any]]:
        normalized = " ".join(address.split())
        if not normalized:
            return []
        return [
            {
                "label": "address_match",
                "url": f"{self.settings.census_geocoder_base_url}/geographies/onelineaddress",
                "params": {**self._base_params(), "address": normalized},
            }
        ]

    def _base_params(self) -> dict[str, str]:
        return {
            "benchmark": "Public_AR_Current",
            "vintage": "Current_Current",
            "layers": "all",
            "format": "json",
        }

    def _street_variants(self, street_address: str) -> list[str]:
        street = " ".join(street_address.split())
        if not street:
            return []
        variants = [street]
        replacements = {
            " South ": " S ",
            " North ": " N ",
            " East ": " E ",
            " West ": " W ",
            " Expressway": " Expy",
            " Parkway": " Pkwy",
            " Avenue": " Ave",
            " Street": " St",
            " Road": " Rd",
            " Drive": " Dr",
        }
        abbreviated = f" {street} "
        for source, target in replacements.items():
            abbreviated = abbreviated.replace(source, target)
        abbreviated = abbreviated.strip()
        if abbreviated != street:
            variants.append(abbreviated)
        return variants

    def _resolved_from_payload(self, payload: dict[str, Any], confidence: str) -> ResolvedDistrict | None:
        matches = payload.get("result", {}).get("addressMatches", [])
        if not matches:
            return None
        for match in matches:
            geographies = match.get("geographies", {})
            district = self._first_matching_geography(geographies, "congressional district")
            state = self._first_matching_geography(geographies, "states")
            if district and state:
                return ResolvedDistrict(
                    state=state.get("STUSAB") or state.get("BASENAME", ""),
                    congressional_district=self._district_code(district),
                    matched_address=match.get("matchedAddress", ""),
                    confidence=confidence,
                )
        return None

    def _first_matching_geography(self, geographies: dict[str, Any], needle: str) -> dict[str, Any] | None:
        for key, values in geographies.items():
            if needle in key.lower() and isinstance(values, list) and values and isinstance(values[0], dict):
                return values[0]
        return None

    def _district_code(self, district: dict[str, Any]) -> str:
        for key in ("CD119", "CD118", "CD117", "BASENAME"):
            value = district.get(key)
            if value not in (None, ""):
                return str(value).zfill(2)
        geoid = str(district.get("GEOID", ""))
        return geoid[-2:] if len(geoid) >= 2 else ""
