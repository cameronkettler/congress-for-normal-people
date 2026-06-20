import asyncio

import httpx

from packages.ingestion.congress.client import CongressClient
from packages.shared.config import Settings


class _TimeoutAsyncClient:
    last_timeout: httpx.Timeout | None = None

    def __init__(self, **kwargs: object) -> None:
        self.__class__.last_timeout = kwargs.get("timeout")

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_: object) -> None:
        return None

    async def get(self, *_: object, **__: object) -> httpx.Response:
        raise httpx.ReadTimeout("timed out")


def test_list_recent_bills_returns_empty_list_when_congress_times_out(monkeypatch):
    _TimeoutAsyncClient.last_timeout = None
    monkeypatch.setattr(httpx, "AsyncClient", _TimeoutAsyncClient)

    result = asyncio.run(CongressClient(Settings(congress_api_key="test-key")).list_recent_bills())

    assert result == []
    assert isinstance(_TimeoutAsyncClient.last_timeout, httpx.Timeout)
