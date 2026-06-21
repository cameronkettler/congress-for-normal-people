import asyncio

from packages.agents.representative_deep_dive import RepresentativeDeepDiveWorkflow
from packages.shared.schemas import RepresentativeRecord


class _FakeCongressClient:
    async def get_member_profile(self, representative: RepresentativeRecord):
        return {
            "terms": [{"startYear": "2021", "endYear": "2027"}],
            "committees": ["Armed Services"],
            "serving_since": "2021",
            "official_url": representative.official_url,
        }

    async def list_member_sponsored_legislation(self, representative: RepresentativeRecord, *, limit: int = 5):
        return [
            {
                "title": "Defense Readiness Act",
                "congress_bill_id": "s-123-119",
                "introduced_date": "2026-01-10",
                "latest_action": "Introduced",
                "policy_area": "Defense",
                "url": "https://www.congress.gov/bill/119th-congress/senate-bill/123",
            }
        ]


class _FakeMalformedLegislationCongressClient(_FakeCongressClient):
    async def list_member_sponsored_legislation(self, representative: RepresentativeRecord, *, limit: int = 5):
        return [
            {
                "title": "Malformed Action Act",
                "congress_bill_id": "s-999-119",
                "introduced_date": "2026-01-10",
                "latest_action": {"text": "Introduced"},
                "policy_area": "Defense",
                "url": "https://www.congress.gov/bill/119th-congress/senate-bill/999",
            },
            {
                "title": "Valid Action Act",
                "congress_bill_id": "s-1000-119",
                "introduced_date": "2026-01-11",
                "latest_action": "Introduced",
                "policy_area": "Defense",
                "url": "https://www.congress.gov/bill/119th-congress/senate-bill/1000",
            },
        ]


class _FakeFECClient:
    async def get_candidate_finance_patterns(self, sponsor_name: str):
        return {"confidence": "medium", "candidate_matches": [{"name": sponsor_name}]}


class _FakeReportGenerator:
    async def generate_representative_deep_dive_context(self, **_: object):
        return {
            "summary": "Public sources describe a focus on defense and national security.",
            "serving_since": "2013",
            "next_election": "Next regularly scheduled Senate election is 2030.",
            "public_themes": ["Defense policy and national security."],
            "watchlist_alignment": ["Defense activity overlaps with your watchlist."],
            "sources": [{"title": "Official member page", "url": "https://www.senate.gov/member"}],
            "caveats": ["Stock disclosures are not included."],
        }


def test_representative_deep_dive_workflow_combines_existing_free_sources():
    workflow = RepresentativeDeepDiveWorkflow(
        congress_client=_FakeCongressClient(),
        fec_client=_FakeFECClient(),
        report_generator=_FakeReportGenerator(),
    )
    representative = RepresentativeRecord(
        name="Cruz, Ted",
        chamber="Senate",
        party="Republican",
        state="TX",
        bioguide_id="C001098",
        official_url="https://www.cruz.senate.gov",
    )

    result = asyncio.run(
        workflow.run(representative=representative, watchlist_topics=["Defense"])
    )

    assert result.representative.name == "Ted Cruz"
    assert result.serving_since == "2013"
    assert result.next_election == "Next regularly scheduled Senate election is 2030."
    assert result.committees == ["Armed Services"]
    assert result.recent_legislation[0].title == "Defense Readiness Act"
    assert result.finance["confidence"] == "medium"
    assert result.public_themes == ["Defense policy and national security."]
    assert result.watchlist_alignment == ["Defense activity overlaps with your watchlist."]


def test_representative_deep_dive_workflow_streams_progress_events():
    workflow = RepresentativeDeepDiveWorkflow(
        congress_client=_FakeCongressClient(),
        fec_client=_FakeFECClient(),
        report_generator=_FakeReportGenerator(),
    )
    representative = RepresentativeRecord(
        name="Cruz, Ted",
        chamber="Senate",
        party="Republican",
        state="TX",
        bioguide_id="C001098",
    )

    async def collect_events():
        return [
            event
            async for event in workflow.run_with_progress(
                representative=representative,
                watchlist_topics=["Defense"],
            )
        ]

    events = asyncio.run(collect_events())

    assert [event["type"] for event in events].count("progress") == 5
    assert events[-1]["type"] == "item"
    assert events[-1]["data"].representative.name == "Ted Cruz"


def test_representative_deep_dive_skips_malformed_legislation_items():
    workflow = RepresentativeDeepDiveWorkflow(
        congress_client=_FakeMalformedLegislationCongressClient(),
        fec_client=_FakeFECClient(),
        report_generator=_FakeReportGenerator(),
    )
    representative = RepresentativeRecord(
        name="Cornyn, John",
        chamber="Senate",
        party="Republican",
        state="TX",
        bioguide_id="C001056",
    )

    result = asyncio.run(
        workflow.run(representative=representative, watchlist_topics=["Defense"])
    )

    assert result.representative.name == "John Cornyn"
    assert [item.title for item in result.recent_legislation] == ["Valid Action Act"]
    assert result.next_election == "Next regularly scheduled Senate election is 2030."
