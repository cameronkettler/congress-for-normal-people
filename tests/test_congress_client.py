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


class _SuccessfulBillAsyncClient:
    last_timeout: httpx.Timeout | None = None

    def __init__(self, **kwargs: object) -> None:
        self.__class__.last_timeout = kwargs.get("timeout")

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_: object) -> None:
        return None

    async def get(self, url: str, **__: object) -> httpx.Response:
        return httpx.Response(
            200,
            request=httpx.Request("GET", url),
            json={
                "bill": {
                    "title": "SAVE Act",
                    "latestAction": {"text": "Received in the Senate."},
                    "sponsors": [{"fullName": "Rep. Roy, Chip [R-TX-21]"}],
                    "introducedDate": "2025-01-03",
                    "status": "introduced",
                }
            },
        )


def test_list_recent_bills_returns_empty_list_when_congress_times_out(monkeypatch):
    _TimeoutAsyncClient.last_timeout = None
    monkeypatch.setattr(httpx, "AsyncClient", _TimeoutAsyncClient)

    result = asyncio.run(CongressClient(Settings(congress_api_key="test-key")).list_recent_bills())

    assert result == []
    assert isinstance(_TimeoutAsyncClient.last_timeout, httpx.Timeout)


def test_get_bill_uses_configured_five_minute_timeout(monkeypatch):
    _SuccessfulBillAsyncClient.last_timeout = None
    monkeypatch.setattr(httpx, "AsyncClient", _SuccessfulBillAsyncClient)

    bill = asyncio.run(
        CongressClient(
            Settings(congress_api_key="test-key", congress_api_timeout_seconds=300)
        ).get_bill("hr-22")
    )

    assert bill.title == "SAVE Act"
    assert isinstance(_SuccessfulBillAsyncClient.last_timeout, httpx.Timeout)
    assert _SuccessfulBillAsyncClient.last_timeout.connect == 300
