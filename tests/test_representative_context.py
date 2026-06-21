import asyncio

from apps.api.app.api import routes
from packages.ingestion.search import SearchResult
from packages.shared.schemas import BillRecord, RepresentativeRecord


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


def test_representative_vote_signal_reports_senate_vote(monkeypatch):
    async def fake_senate_member_vote(vote: dict[str, object], representative: RepresentativeRecord):
        return {
            "vote_cast": "Yea",
            "vote_question": "On Passage",
            "result": "Passed",
            "roll_call_number": "22",
        }

    monkeypatch.setattr(routes, "safe_senate_member_vote", fake_senate_member_vote)
    representative = RepresentativeRecord(
        name="Cruz, Ted",
        chamber="Senate",
        party="Republican",
        state="TX",
        bioguide_id="C001098",
    )

    signal = asyncio.run(
        routes.representative_vote_signal(
            "s-5-119",
            representative,
            [],
            [
                {
                    "congress": "119",
                    "sessionNumber": "1",
                    "rollCallNumber": "22",
                    "voteQuestion": "On Passage",
                    "result": "Passed",
                    "startDate": "2025-01-20T12:00:00-04:00",
                }
            ],
        )
    )

    assert signal is not None
    assert signal[0] == "Voted for"
    assert "The Senate vote result was Passed" in signal[1]


def test_representative_cosponsor_matching_handles_weber_name_and_bioguide_variants():
    representative = RepresentativeRecord(
        name="Weber, Randy K. Sr.",
        chamber="House",
        party="Republican",
        state="TX",
        district="14",
        bioguide_id="W000814",
    )
    cosponsors = [
        {
            "bioguideID": "W000814",
            "fullName": "Rep. Weber, Randy K. Sr. [R-TX-14]",
        }
    ]

    assert routes.representative_is_cosponsor(representative, cosponsors)


def test_representative_name_matching_handles_first_last_and_suffixes():
    assert routes.names_refer_to_same_person("Weber, Randy K. Sr.", "Randy Weber")
    assert routes.names_refer_to_same_person("Cruz, Ted", "Ted Cruz")
    assert not routes.names_refer_to_same_person("Cruz, Ted", "John Cornyn")


def test_typed_representative_lookup_can_resolve_current_state_member(monkeypatch):
    class FakeQuery:
        def filter(self, *_: object):
            return self

        def one_or_none(self):
            return type(
                "Profile",
                (),
                {"user_id": 1, "state": "TX", "congressional_district": "30"},
            )()

    class FakeDb:
        def query(self, *_: object):
            return FakeQuery()

    async def fake_representatives_for_profile(profile):
        return ([], None)

    async def fake_current_state_members(state: str):
        return [
            RepresentativeRecord(
                name="Weber, Randy K. Sr.",
                chamber="House",
                party="Republican",
                state=state,
                district="14",
                bioguide_id="W000814",
                photo_url="https://www.congress.gov/img/member/w000814_200.jpg",
            )
        ]

    monkeypatch.setattr(routes, "representatives_for_profile", fake_representatives_for_profile)
    monkeypatch.setattr(routes, "current_state_members", fake_current_state_members)

    representative = asyncio.run(
        routes.representative_from_user_or_name(
            FakeDb(),
            type("User", (), {"id": 1})(),
            "Randy Weber",
        )
    )

    assert representative.party == "Republican"
    assert representative.chamber == "House"
    assert representative.photo_url == "https://www.congress.gov/img/member/w000814_200.jpg"


def test_representative_signal_for_bill_can_evaluate_typed_senator_name(monkeypatch):
    async def fake_search(bill: dict[str, object], representative: RepresentativeRecord, session=None):
        return []

    class FakeReportGenerator:
        async def generate_representative_position_reason(self, **_: object):
            return None

    monkeypatch.setattr(routes, "search_representative_position", fake_search)
    monkeypatch.setattr(routes, "OpenAIReportGenerator", FakeReportGenerator)
    representative = RepresentativeRecord(
        name="Cruz, Ted",
        chamber="Senate",
        party="Republican",
        state="TX",
        bioguide_id="C001098",
    )
    bill = BillRecord(
        congress_bill_id="sres-1-119",
        title="A Senate resolution",
        summary="A resolution.",
        sponsor="Sen. Cruz, Ted [R-TX]",
        latest_action="Introduced.",
        status="introduced",
        topic="Government Operations",
    )

    signal = asyncio.run(
        routes.representative_signal_for_bill(
            bill=bill,
            representative=representative,
            cosponsors=[],
            house_votes=[],
        )
    )

    assert signal.signal == "Sponsor"
    assert signal.representative.chamber == "Senate"


def test_representative_position_queries_are_neutral_and_stance_oriented():
    queries = routes.representative_position_queries(
        rep_name="Weber, Randy K. Sr.",
        bill_id="hr-22-119",
        title="SAVE Act",
        official_url="https://weber.house.gov",
    )

    assert queries == [
        (
            '"Weber, Randy K. Sr." ("SAVE Act" "hr-22-119" "hr-22") '
            "(site:weber.house.gov OR site:house.gov OR site:senate.gov OR site:congress.gov) "
            "(statement OR press release OR voted OR vote OR support OR oppose OR cosponsor)"
        ),
    ]
    assert len(queries) == 1
    assert all(" quote" not in query for query in queries)
    assert all(" interview" not in query for query in queries)
    assert all("voter suppression" not in query for query in queries)
    assert all("proof of citizenship" not in query for query in queries)


def test_representative_position_queries_work_without_official_url():
    queries = routes.representative_position_queries(
        rep_name="Crockett, Jasmine",
        bill_id="hr-8800-119",
        title="National Defense Authorization Act for Fiscal Year 2027",
    )

    assert queries[0] == (
        '"Crockett, Jasmine" ("National Defense Authorization Act for Fiscal Year 2027" "hr-8800-119" "hr-8800") '
        "(site:house.gov OR site:senate.gov OR site:congress.gov) "
        "(statement OR press release OR voted OR vote OR support OR oppose OR cosponsor)"
    )
    assert len(queries) == 1


def test_representative_position_detail_appends_grounded_public_reason(monkeypatch):
    async def fake_search(bill: dict[str, object], representative: RepresentativeRecord, session=None):
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

    signal, detail, sources, ai_context = asyncio.run(
        routes.enrich_representative_position_signal(
            bill={"congress_bill_id": "hr-22-119", "title": "SAVE Act"},
            representative=representative,
            signal="Voted against",
            detail="Your representative voted Nay on On Passage.",
        )
    )

    assert signal == "Voted against"
    assert detail == "Your representative voted Nay on On Passage."
    assert ai_context is not None
    assert "voting barriers" in ai_context
    assert sources[0].url == "https://example.com/statement"


def test_representative_position_signal_upgrades_no_direct_signal_from_public_evidence(monkeypatch):
    async def fake_search(bill: dict[str, object], representative: RepresentativeRecord, session=None):
        return [
            SearchResult(
                title="News report on SAVE Act vote",
                link="https://example.com/news",
                snippet="Crockett criticized the SAVE Act as a voter suppression measure.",
                source="example.com",
            )
        ]

    class FakeReportGenerator:
        async def generate_representative_position_reason(self, **_: object):
            return {
                "position": "criticizes",
                "reason": "Public reporting says the representative criticized the bill as a voter suppression measure.",
                "sources": [{"title": "News report on SAVE Act vote", "url": "https://example.com/news"}],
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

    signal, detail, sources, ai_context = asyncio.run(
        routes.enrich_representative_position_signal(
            bill={"congress_bill_id": "hr-22-119", "title": "SAVE Act"},
            representative=representative,
            signal="No direct signal found",
            detail="No sponsor or cosponsor relationship was found in the available Congress.gov data.",
        )
    )

    assert signal == "Publicly criticized"
    assert "formal sponsor, cosponsor, or recorded-vote signal" in detail
    assert ai_context is not None
    assert "voter suppression" in ai_context
    assert sources[0].url == "https://example.com/news"


def test_public_search_can_report_cosponsor_relationship_without_llm(monkeypatch):
    async def fake_search(bill: dict[str, object], representative: RepresentativeRecord, session=None):
        return [
            SearchResult(
                title="H.R. 8800 cosponsors",
                link="https://example.com/hr-8800",
                snippet="Rep. Jasmine Crockett is listed as a cosponsor of H.R. 8800.",
                source="Example",
            )
        ]

    class UnexpectedReportGenerator:
        async def generate_representative_position_reason(self, **_: object):
            raise AssertionError("reported cosponsor should be detected before LLM enrichment")

    monkeypatch.setattr(routes, "search_representative_position", fake_search)
    monkeypatch.setattr(routes, "OpenAIReportGenerator", UnexpectedReportGenerator)
    representative = RepresentativeRecord(
        name="Crockett, Jasmine",
        chamber="House",
        party="Democratic",
        state="TX",
        district="30",
        bioguide_id="C001130",
    )

    signal, detail, sources, ai_context = asyncio.run(
        routes.enrich_representative_position_signal(
            bill={"congress_bill_id": "hr-8800-119", "title": "National Defense Authorization Act for Fiscal Year 2027"},
            representative=representative,
            signal="No direct signal found",
            detail="No sponsor or cosponsor relationship was found in the available Congress.gov data.",
        )
    )

    assert signal == "Reported cosponsor"
    assert "support signal" in detail
    assert ai_context is None
    assert sources[0].url == "https://example.com/hr-8800"


def test_representative_position_signal_reports_public_search_when_reason_unclear(monkeypatch):
    async def fake_search(bill: dict[str, object], representative: RepresentativeRecord, session=None):
        return [
            SearchResult(
                title="SAVE Act coverage",
                link="https://example.com/coverage",
                snippet="Coverage mentions the representative and the bill.",
                source="example.com",
            )
        ]

    class FakeReportGenerator:
        async def generate_representative_position_reason(self, **_: object):
            return None

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

    signal, detail, sources, ai_context = asyncio.run(
        routes.enrich_representative_position_signal(
            bill={"congress_bill_id": "hr-22-119", "title": "SAVE Act"},
            representative=representative,
            signal="No direct signal found",
            detail="No sponsor or cosponsor relationship was found in the available Congress.gov data.",
        )
    )

    assert signal == "Public search reviewed"
    assert "review the source links below" in detail
    assert ai_context is None
    assert sources[0].url == "https://example.com/coverage"


def test_representative_position_signal_keeps_unclear_ai_context(monkeypatch):
    async def fake_search(bill: dict[str, object], representative: RepresentativeRecord, session=None):
        return [
            SearchResult(
                title="Bill tracking in US - S 1582",
                link="https://example.com/s-1582",
                snippet="Bill tracking page for S. 1582 and public legislative status.",
                source="Example",
            )
        ]

    class FakeReportGenerator:
        async def generate_representative_position_reason(self, **_: object):
            return {
                "position": "unclear",
                "reason": "Public sources identify the bill and representative, but they do not establish whether the senator supports or opposes the measure.",
                "sources": [{"title": "Bill tracking in US - S 1582", "url": "https://example.com/s-1582"}],
                "confidence": "low",
            }

    monkeypatch.setattr(routes, "search_representative_position", fake_search)
    monkeypatch.setattr(routes, "OpenAIReportGenerator", FakeReportGenerator)
    representative = RepresentativeRecord(
        name="Cruz, Ted",
        chamber="Senate",
        party="Republican",
        state="TX",
        bioguide_id="C001098",
    )

    signal, detail, sources, ai_context = asyncio.run(
        routes.enrich_representative_position_signal(
            bill={"congress_bill_id": "s-1582-119", "title": "GENIUS Act"},
            representative=representative,
            signal="No direct signal found",
            detail="No sponsor or cosponsor relationship was found in the available Congress.gov data.",
        )
    )

    assert signal == "Public search reviewed"
    assert "formal sponsor, cosponsor, or recorded-vote signal" in detail
    assert ai_context is not None
    assert "do not establish" in ai_context
    assert sources[0].url == "https://example.com/s-1582"


def test_representative_position_signal_combines_openai_web_search_context(monkeypatch):
    async def fake_search(bill: dict[str, object], representative: RepresentativeRecord, session=None):
        return []

    class FakeReportGenerator:
        async def generate_representative_web_context(self, **_: object):
            return {
                "position": "supports",
                "reason": "OpenAI web search found a public source saying the senator backed the bill's stablecoin framework.",
                "sources": [{"title": "Senator statement", "url": "https://www.senate.gov/member-statement"}],
                "confidence": "medium",
            }

        async def generate_representative_position_reason(self, **kwargs: object):
            search_results = kwargs["search_results"]
            assert any(
                item["source"] == "OpenAI web search"
                for item in search_results
            )
            return {
                "position": "supports",
                "reason": "Public context says the senator backed the bill's stablecoin framework.",
                "sources": [{"title": "Senator statement", "url": "https://www.senate.gov/member-statement"}],
                "confidence": "medium",
            }

    monkeypatch.setattr(routes, "search_representative_position", fake_search)
    monkeypatch.setattr(routes, "OpenAIReportGenerator", FakeReportGenerator)
    representative = RepresentativeRecord(
        name="Cruz, Ted",
        chamber="Senate",
        party="Republican",
        state="TX",
        bioguide_id="C001098",
    )

    signal, detail, sources, ai_context = asyncio.run(
        routes.enrich_representative_position_signal(
            bill={"congress_bill_id": "s-1582-119", "title": "GENIUS Act"},
            representative=representative,
            signal="No direct signal found",
            detail="No sponsor or cosponsor relationship was found in the available Congress.gov data.",
        )
    )

    assert signal == "Publicly supported"
    assert "formal sponsor, cosponsor, or recorded-vote signal" in detail
    assert ai_context is not None
    assert "stablecoin framework" in ai_context
    assert sources[0].url == "https://www.senate.gov/member-statement"


def test_representative_position_agent_can_use_formal_signal_without_search(monkeypatch):
    async def fake_search(bill: dict[str, object], representative: RepresentativeRecord, session=None):
        return []

    class FakeReportGenerator:
        async def generate_representative_position_reason(self, **_: object):
            return {
                "position": "supports",
                "reason": "The recorded vote is a formal support signal, while the bill topic suggests a defense-policy rationale.",
                "sources": [],
                "confidence": "low",
            }

    monkeypatch.setattr(routes, "search_representative_position", fake_search)
    monkeypatch.setattr(routes, "OpenAIReportGenerator", FakeReportGenerator)
    representative = RepresentativeRecord(
        name="Weber, Randy K. Sr.",
        chamber="House",
        party="Republican",
        state="TX",
        district="14",
        bioguide_id="W000814",
    )

    signal, detail, sources, ai_context = asyncio.run(
        routes.enrich_representative_position_signal(
            bill={"congress_bill_id": "hr-8800-119", "title": "National Defense Authorization Act for Fiscal Year 2027"},
            representative=representative,
            signal="Voted for",
            detail="Your representative voted Aye on On Passage.",
        )
    )

    assert signal == "Voted for"
    assert detail == "Your representative voted Aye on On Passage."
    assert sources == []
    assert ai_context is not None
    assert "formal support signal" in ai_context


def test_formatted_position_sources_filters_unrelated_sources():
    representative = RepresentativeRecord(
        name="Crockett, Jasmine",
        chamber="House",
        party="Democratic",
        state="TX",
        district="30",
        bioguide_id="C001130",
    )
    search_results = [
        SearchResult(
            title="Crockett criticizes SAVE Act",
            link="https://example.com/crockett",
            snippet="Jasmine Crockett called the bill voter suppression.",
            source="Example",
        ),
        SearchResult(
            title="Cosponsored - pass the SAVE America Act",
            link="https://www.facebook.com/RepJohnJames/posts/123",
            snippet="Rep. John James supports the bill.",
            source="Facebook",
        ),
    ]
    reason = {
        "sources": [
            {"title": "Cosponsored - pass the SAVE America Act", "url": "https://www.facebook.com/RepJohnJames/posts/123"},
            {"title": "Crockett criticizes SAVE Act", "url": "https://example.com/crockett"},
        ]
    }

    sources = routes.formatted_position_sources(reason, search_results, representative)

    assert sources[0].url == "https://example.com/crockett"
    assert all("RepJohnJames" not in str(source.url) for source in sources)


def test_lcv_roll_call_source_links_to_member_scorecard():
    representative = RepresentativeRecord(
        name="Crockett, Jasmine",
        chamber="House",
        party="Democratic",
        state="TX",
        district="30",
        bioguide_id="C001130",
    )
    source = routes.source_reference(
        SearchResult(
            title="Requiring Proof of Citizenship to Register for Federal Elections",
            link="https://www.lcv.org/roll-call-vote/requiring-proof-of-citizenship-to-register-for-federal-elections/",
            snippet="Vote summary for H.R. 22.",
            source="LCV",
        ),
        representative,
        confidence="low",
    )

    assert source.label == "LCV vote summary"
    assert source.url == "https://www.lcv.org/moc/jasmine-crockett/"
    assert "vote summary" in source.description
