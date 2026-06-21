import logging
from typing import Any

import httpx

logger = logging.getLogger(__name__)

TIGERWEB_LEGISLATIVE_BASE_URL = (
    "https://tigerweb.geo.census.gov/arcgis/rest/services/TIGERweb/Legislative/MapServer"
)

TIGERWEB_STATE_COUNTY_BASE_URL = (
    "https://tigerweb.geo.census.gov/arcgis/rest/services/TIGERweb/State_County/MapServer"
)

CONGRESSIONAL_DISTRICTS_119_LAYER_ID = 0
STATES_LAYER_ID = 0

STATE_FIPS: dict[str, str] = {
    "AL": "01",
    "AK": "02",
    "AZ": "04",
    "AR": "05",
    "CA": "06",
    "CO": "08",
    "CT": "09",
    "DE": "10",
    "DC": "11",
    "FL": "12",
    "GA": "13",
    "HI": "15",
    "ID": "16",
    "IL": "17",
    "IN": "18",
    "IA": "19",
    "KS": "20",
    "KY": "21",
    "LA": "22",
    "ME": "23",
    "MD": "24",
    "MA": "25",
    "MI": "26",
    "MN": "27",
    "MS": "28",
    "MO": "29",
    "MT": "30",
    "NE": "31",
    "NV": "32",
    "NH": "33",
    "NJ": "34",
    "NM": "35",
    "NY": "36",
    "NC": "37",
    "ND": "38",
    "OH": "39",
    "OK": "40",
    "OR": "41",
    "PA": "42",
    "RI": "44",
    "SC": "45",
    "SD": "46",
    "TN": "47",
    "TX": "48",
    "UT": "49",
    "VT": "50",
    "VA": "51",
    "WA": "53",
    "WV": "54",
    "WI": "55",
    "WY": "56",
}


class CensusGeometryClient:
    async def congressional_district_geometry(
        self,
        *,
        state: str,
        district: str,
    ) -> dict[str, Any]:
        state_fips = state_to_fips(state)
        district_code = normalize_district(district)

        if not state_fips or not district_code:
            return empty_feature_collection()

        where = f"STATE='{state_fips}' AND CD119='{district_code}'"
        return await self._query_geojson(
            base_url=TIGERWEB_LEGISLATIVE_BASE_URL,
            layer_id=CONGRESSIONAL_DISTRICTS_119_LAYER_ID,
            where=where,
        )

    async def state_geometry(self, *, state: str) -> dict[str, Any]:
        state_fips = state_to_fips(state)

        if not state_fips:
            return empty_feature_collection()

        where = f"STATE='{state_fips}'"
        return await self._query_geojson(
            base_url=TIGERWEB_STATE_COUNTY_BASE_URL,
            layer_id=STATES_LAYER_ID,
            where=where,
        )

    async def _query_geojson(
        self,
        *,
        base_url: str,
        layer_id: int,
        where: str,
    ) -> dict[str, Any]:
        url = f"{base_url}/{layer_id}/query"

        params = {
            "where": where,
            "outFields": "*",
            "returnGeometry": "true",
            "outSR": "4326",
            "f": "geojson",
        }

        async with httpx.AsyncClient(timeout=httpx.Timeout(20.0)) as client:
            response = await client.get(url, params=params)
            response.raise_for_status()
            payload = response.json()

        if not isinstance(payload, dict):
            return empty_feature_collection()

        if payload.get("type") != "FeatureCollection":
            return empty_feature_collection()

        return payload


def state_to_fips(state: str) -> str:
    return STATE_FIPS.get(state.strip().upper(), "")


def normalize_district(district: str) -> str:
    cleaned = district.strip().upper()

    if not cleaned:
        return ""

    if cleaned in {"AT LARGE", "AT-LARGE", "AL", "00"}:
        return "00"

    digits = "".join(ch for ch in cleaned if ch.isdigit())

    if not digits:
        return ""

    return digits.zfill(2)


def empty_feature_collection() -> dict[str, Any]:
    return {"type": "FeatureCollection", "features": []}