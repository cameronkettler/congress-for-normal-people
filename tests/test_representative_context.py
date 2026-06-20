import asyncio

from apps.api.app.api import routes
from packages.ingestion.search import SearchResult
from packages.shared.schemas import RepresentativeRecord


def test_representative_vote_signal_reports_nay_vote(monkeypatch):
    async def fake_house_member_vote(vote: dict[str, object], representative: RepresentativeRecord):
        return {
            "vote_cast": "Nay",
            "vote_question": "On Passage",
            "result": "Passed",
            "roll_call_number": "102",
        }

    monkeypatch.setattr(routes, "safe_house_member_vote", fake_house_member_vote)
    representative = RepresentativeRecord(
        name="Crockett, Jasmine",
        chamber="House",
        party="Democratic",
        state="TX",
        district="30",
        bioguide_id="C001130",
    )

    signal = asyncio.run(
        routes.representative_vote_signal(
            "hr-22-119",
            representative,
            [
                {
                    "congress": "119",
                    "sessionNumber": "1",
                    "rollCallNumber": "102",
                    "voteQuestion": "On Passage",
                    "result": "Passed",
                    "startDate": "2025-04-10T12:00:00-04:00",
                }
            ],
        )
    )

    assert signal is not None
    assert signal[0] == "Voted against"
    assert "voted Nay" in signal[1]


def test_representative_position_detail_appends_grounded_public_reason(monkeypatch):
    async def fake_search(bill: dict[str, object], representative: RepresentativeRecord):
        return [
            SearchResult(
                title="Member statement",
                link="https://example.com/statement",
                snippet="The representative criticized the bill as creating voting barriers.",
                source="example.com",
            )
        ]

    class FakeReportGenerator:
        async def generate_representative_position_reason(self, **_: object):
            return {
                "position": "criticizes",
                "reason": "Public reporting says the representative criticized the bill as creating voting barriers.",
                "sources": [{"title": "Member statement", "url": "https://example.com/statement"}],
                "confidence": "medium",
            }

    monkeypatch.setattr(routes, "search_representative_position", fake_search)
    monkeypatch.setattr(routes, "OpenAIReportGenerator", FakeReportGenerator)
    representative = RepresentativeRecord(
        name="Crockett, Jasmine",
        chamber="House",
        party="Democratic",
        state="TX",
        district="30",
        bioguide_id="C001130",
    )

    detail = asyncio.run(
        routes.enrich_representative_position_detail(
            bill={"congress_bill_id": "hr-22-119", "title": "SAVE Act"},
            representative=representative,
            signal="Voted against",
            detail="Your representative voted Nay on On Passage.",
        )
    )

    assert "Public-position context" in detail
    assert "voting barriers" in detail
    assert "https://example.com/statement" in detail
