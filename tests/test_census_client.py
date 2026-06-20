import asyncio

import httpx

from packages.ingestion.census import CensusGeocoderClient
from packages.shared.config import Settings


class _FakeCensusAsyncClient:
    requests: list[dict[str, object]] = []

    def __init__(self, **_: object) -> None:
        self.__class__.requests = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_: object) -> None:
        return None

    async def get(self, url: str, **kwargs: object) -> httpx.Response:
        self.__class__.requests.append({"url": url, **kwargs})
        return httpx.Response(
            200,
            request=httpx.Request("GET", url),
            json={
                "result": {
                    "addressMatches": [
                        {
                            "matchedAddress": "1011 S PEARL EXPY, DALLAS, TX, 75201",
                            "geographies": {
                                "States": [{"STUSAB": "TX"}],
                                "119th Congressional Districts": [{"CD119": "30"}],
                            },
                        }
                    ]
                }
            },
        )


def test_census_geocoder_parses_current_congressional_district_key(monkeypatch):
    monkeypatch.setattr(httpx, "AsyncClient", _FakeCensusAsyncClient)

    resolved = asyncio.run(
        CensusGeocoderClient(Settings()).resolve_location(
            street_address="1011 South Pearl Expressway",
            address_line_2="Suite 200",
            city="Dallas",
            state="TX",
            zip_code="75201",
        )
    )

    assert resolved.state == "TX"
    assert resolved.congressional_district == "30"
    assert resolved.confidence == "address_match"
    assert _FakeCensusAsyncClient.requests[0]["url"].endswith("/geographies/address")


def test_census_geocoder_supports_oneline_address(monkeypatch):
    monkeypatch.setattr(httpx, "AsyncClient", _FakeCensusAsyncClient)

    resolved = asyncio.run(
        CensusGeocoderClient(Settings()).resolve_address("1011 S Pearl Expy Dallas TX 75201")
    )

    assert resolved.state == "TX"
    assert resolved.congressional_district == "30"
    assert _FakeCensusAsyncClient.requests[0]["url"].endswith("/geographies/onelineaddress")
