import asyncio

import httpx

from packages.ingestion.census import CensusGeocoderClient
from packages.shared.config import Settings


class _FakeCensusAsyncClient:
    def __init__(self, **_: object) -> None:
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_: object) -> None:
        return None

    async def get(self, url: str, **__: object) -> httpx.Response:
        return httpx.Response(
            200,
            request=httpx.Request("GET", url),
            json={
                "result": {
                    "addressMatches": [
                        {
                            "matchedAddress": "1600 PENNSYLVANIA AVE NW, WASHINGTON, DC, 20500",
                            "geographies": {
                                "States": [{"STUSAB": "DC"}],
                                "Congressional Districts": [{"CD119": "98"}],
                            },
                        }
                    ]
                }
            },
        )


def test_census_geocoder_resolves_congressional_district(monkeypatch):
    monkeypatch.setattr(httpx, "AsyncClient", _FakeCensusAsyncClient)

    resolved = asyncio.run(
        CensusGeocoderClient(Settings()).resolve_address("1600 Pennsylvania Ave NW Washington DC 20500")
    )

    assert resolved.state == "DC"
    assert resolved.congressional_district == "98"
    assert resolved.confidence == "address_match"
