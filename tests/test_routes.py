import asyncio

from apps.api.app.api import routes


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
