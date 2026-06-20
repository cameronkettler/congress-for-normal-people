import asyncio

import httpx

from packages.ingestion.search import SerpApiClient
from packages.shared.config import Settings


class _FakeSerpAsyncClient:
    last_request: dict | None = None

    def __init__(self, **_: object) -> None:
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_: object) -> None:
        return None

    async def get(self, url: str, **kwargs: object) -> httpx.Response:
        self.__class__.last_request = {"url": url, **kwargs}
        return httpx.Response(
            200,
            request=httpx.Request("GET", url),
            json={
                "organic_results": [
                    {
                        "title": "Rep. statement on H.R. 22",
                        "link": "https://example.com/hr-22",
                        "snippet": "The representative opposed the bill.",
                        "source": "Example",
                    }
                ]
            },
        )


def test_serpapi_client_parses_organic_results(monkeypatch):
    monkeypatch.setattr(httpx, "AsyncClient", _FakeSerpAsyncClient)
    settings = Settings(serpapi_enabled=True, serpapi_api_key="test-key", rep_position_search_results=3)

    results = asyncio.run(SerpApiClient(settings).search('"Crockett" "H.R. 22"'))

    assert len(results) == 1
    assert results[0].title == "Rep. statement on H.R. 22"
    assert results[0].link == "https://example.com/hr-22"
    assert _FakeSerpAsyncClient.last_request is not None
    assert _FakeSerpAsyncClient.last_request["params"]["engine"] == "google"
    assert _FakeSerpAsyncClient.last_request["params"]["api_key"] == "test-key"


def test_serpapi_client_returns_empty_when_disabled(monkeypatch):
    monkeypatch.setattr(httpx, "AsyncClient", _FakeSerpAsyncClient)

    results = asyncio.run(SerpApiClient(Settings(serpapi_enabled=False)).search("anything"))

    assert results == []
