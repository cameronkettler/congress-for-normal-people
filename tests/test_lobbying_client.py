import asyncio

import httpx

from packages.ingestion.lobbying.client import LobbyingDisclosureClient
from packages.shared.config import Settings


class _FakeAsyncClient:
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
                "results": [
                    {
                        "client": {"name": "Example Client"},
                        "filing_specific_lobbying_issues": "AI procurement",
                    }
                ]
            },
        )


def test_lobbying_client_sends_lda_token_and_documented_filter(monkeypatch):
    _FakeAsyncClient.last_request = None
    monkeypatch.setattr(httpx, "AsyncClient", _FakeAsyncClient)
    settings = Settings(
        lobbying_api_live=True,
        lobbying_disclosure_api_key="test-token",
        lobbying_disclosure_base_url="https://lda.gov/api/v1",
    )

    result = asyncio.run(LobbyingDisclosureClient(settings).search_activity("AI procurement"))

    assert result["source"] == "lobbying_disclosure_api"
    assert _FakeAsyncClient.last_request == {
        "url": "https://lda.gov/api/v1/filings/",
        "headers": {"Authorization": "Token test-token"},
        "params": {"filing_specific_lobbying_issues": "AI procurement", "page_size": 5},
    }
