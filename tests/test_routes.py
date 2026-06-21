import asyncio
import json
from datetime import datetime, timezone

from apps.api.app.api import routes
from packages.agents.bill_lookup import ProviderLookupError
from packages.db.models import Base, ReportCache, RepresentativeDeepDiveCache, User
from packages.shared.schemas import BillLookupRequest, RepresentativeDeepDiveResponse
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker


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


def test_hot_topics_returns_searchable_bill_prompts():
    response = routes.hot_topics(_EmptyDb())

    assert response.items
    assert response.items[0].congress_bill_id == "hr-8800-119"
    assert all(item.title for item in response.items)
    assert all(item.reason for item in response.items)


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


def test_cached_report_response_returns_fresh_full_report_without_workflow():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    db = Session()
    db.add(
        ReportCache(
            congress_bill_id="hr-22-119",
            profile_key="anonymous",
            response_json={
                "bill": {
                    "congress_bill_id": "hr-22-119",
                    "title": "SAVE Act",
                    "summary": "Cached summary",
                    "sponsor": "Rep. Roy, Chip [R-TX-21]",
                    "latest_action": "Cached action",
                    "status": "introduced",
                    "topic": "Elections",
                },
                "sponsor": {},
                "finance": {"confidence": "low"},
                "lobbying": {},
                "generated_summary": "Cached generated summary",
                "generated_analysis": "Cached generated analysis",
                "analysis_sections": {},
                "stakeholders": {"possible_supporters": [], "possible_opponents": []},
                "caveats": ["Cached caveat"],
                "confidence": "medium",
                "representative_context": [
                    {
                        "representative": {
                            "name": "Crockett, Jasmine",
                            "chamber": "House",
                            "party": "Democrat",
                            "state": "TX",
                            "district": "30",
                        },
                        "signal": "Voted against",
                        "detail": "Cached representative context",
                        "sources": [],
                    }
                ],
            },
            created_at=datetime.now(timezone.utc),
        )
    )
    db.commit()

    response = routes.cached_report_response(db, "hr-22", None)

    assert response is not None
    assert response.bill.congress_bill_id == "hr-22-119"
    assert response.generated_summary == "Cached generated summary"
    assert response.representative_context[0].detail == "Cached representative context"


def test_cached_representative_deep_dive_response_returns_fresh_profile():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    db = Session()
    user = User(id=7, email="cache@example.com", password_hash="hash")
    db.add(user)
    db.add(
        RepresentativeDeepDiveCache(
            profile_key="user:7:no-location",
            topics_key='["defense"]',
            response_json={
                "items": [
                    {
                        "representative": {
                            "name": "Cornyn, John",
                            "chamber": "Senate",
                            "party": "Republican",
                            "state": "TX",
                        },
                        "serving_since": "2002",
                        "next_election": "Lost the 2026 runoff.",
                        "summary": "Cached deep dive",
                        "money_context": "Cached money context",
                        "sources": [{"label": "Source", "url": "https://example.com", "description": "Cached source"}],
                    }
                ],
            },
            created_at=datetime.now(timezone.utc),
        )
    )
    db.commit()

    response = routes.cached_representative_deep_dive_response(db, user, ["Defense"])

    assert response is not None
    assert response.items[0].representative.name == "John Cornyn"
    assert response.items[0].summary == "Cached deep dive"


def test_representative_deep_dive_cache_skips_partial_responses():
    response = RepresentativeDeepDiveResponse(
        items=[],
        warning="Some representative deep dives were unavailable.",
    )

    assert not routes.representative_deep_dive_response_is_cacheable(response)
