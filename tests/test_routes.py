import asyncio
import json

from apps.api.app.api import routes
from packages.agents.bill_lookup import ProviderLookupError
from packages.shared.schemas import BillLookupRequest


class _EmptyQuery:
    def order_by(self, *_: object):
        return self

    def limit(self, *_: object):
        return self

    def all(self) -> list[object]:
        return []


class _EmptyDb:
    def query(self, *_: object) -> _EmptyQuery:
        return _EmptyQuery()


class _UnexpectedCongressClient:
    async def list_recent_bills(self, *_: object, **__: object) -> list[object]:
        raise AssertionError("recent_bills should not call Congress.gov synchronously")


def test_recent_bills_returns_warning_without_live_feed(monkeypatch):
    monkeypatch.setattr(routes, "CongressClient", _UnexpectedCongressClient)

    response = asyncio.run(routes.recent_bills(_EmptyDb()))

    assert response.items == []
    assert response.warning == "No cached bills yet. Run polling to populate recent bills."


class _CongressFailureWorkflow:
    async def run(self, bill_id: str):
        raise ProviderLookupError("Congress.gov")


def test_lookup_bill_returns_structured_502_for_congress_failure(monkeypatch):
    monkeypatch.setattr(routes, "BillLookupWorkflow", _CongressFailureWorkflow)

    response = asyncio.run(routes.lookup_bill(BillLookupRequest(bill_id="hr-22-119"), _EmptyDb()))

    assert response.status_code == 502
    assert json.loads(response.body) == {
        "error": "Bill lookup failed",
        "provider": "Congress.gov",
        "detail": "External data source unavailable or timed out",
    }
