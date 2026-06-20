import asyncio

import httpx

from packages.agents.bill_lookup import BillLookupWorkflow
from packages.ingestion.congress import CongressClient
from packages.ingestion.fec import FECClient
from packages.ingestion.lobbying import LobbyingDisclosureClient
from packages.shared.config import Settings
from packages.shared.schemas import BillRecord
from packages.shared.topics import DEFAULT_MONITORING_TOPICS


def test_bill_lookup_workflow_returns_structured_report():
    async def run_lookup():
        settings = Settings(
            congress_api_key=None,
            fec_api_key=None,
            lobbying_api_live=False,
            lobbying_disclosure_api_key=None,
        )
        return await BillLookupWorkflow(
            congress_client=CongressClient(settings),
            fec_client=FECClient(settings),
            lobbying_client=LobbyingDisclosureClient(settings),
        ).run("hr-1234-119")

    response = asyncio.run(run_lookup())

    assert response.bill.congress_bill_id == "hr-1234-119"
    assert response.generated_summary
    assert response.generated_analysis
    assert response.stakeholders["possible_supporters"]
    assert response.caveats


def test_congress_client_demo_recent_bills_are_classified():
    async def list_bills():
        return await CongressClient(Settings(congress_api_key=None)).list_recent_bills(limit=2)

    bills = asyncio.run(list_bills())

    assert len(bills) == 2
    assert all(bill.topic for bill in bills)


def test_congress_client_classifies_common_policy_domains():
    client = CongressClient(Settings(congress_api_key=None))

    assert client.classify_topic("SAVE Act voter registration requirements") == "Elections"
    assert client.classify_topic("Farm, Food, and National Security Act") == "Agriculture"
    assert client.classify_topic("Veterans health care access improvement") == "Healthcare"
    assert client.classify_topic("A bill to recognize a commemorative week") == "Uncategorized"


def test_default_monitoring_topics_include_classifier_taxonomy():
    topics = Settings(monitoring_topics=DEFAULT_MONITORING_TOPICS).topics

    assert "Agriculture" in topics
    assert "Elections" in topics
    assert "Transportation" in topics
    assert "Veterans" in topics


def test_bill_lookup_workflow_extracts_unique_stakeholder_names():
    workflow = BillLookupWorkflow(settings=Settings(openai_api_live=False))

    insights = workflow._stakeholder_insights(
        [
            {"client": {"name": "American College of Physicians"}},
            {"client_name": "American College of Physicians"},
            {
                "registrant": {"name": "National Affordable Housing Management Association"},
                "issue": "Housing affordability",
            },
            {},
        ]
    )

    assert [item.name for item in insights] == [
        "American College of Physicians",
        "National Affordable Housing Management Association",
    ]
    assert insights[1].context == "Disclosure topic match: Housing affordability."
    assert insights[1].takeaway
    assert insights[1].relevance


class _FailingFinanceClient:
    async def get_candidate_finance_patterns(self, *_: object):
        raise httpx.ReadTimeout("finance timed out")


class _FailingLobbyingClient:
    async def search_activity(self, *_: object):
        raise httpx.ReadTimeout("lobbying timed out")


def test_bill_lookup_workflow_degrades_optional_provider_failures():
    workflow = BillLookupWorkflow(
        fec_client=_FailingFinanceClient(),
        lobbying_client=_FailingLobbyingClient(),
        settings=Settings(openai_api_live=False),
    )
    bill = BillRecord(
        congress_bill_id="hr-22-119",
        title="SAVE Act",
        summary="Requires proof of citizenship for federal voter registration.",
        sponsor="Rep. Roy, Chip [R-TX-21]",
        latest_action="Received in the Senate.",
        status="introduced",
        topic="Elections",
    )

    finance = asyncio.run(workflow.retrieve_finance({"bill": bill}))
    lobbying = asyncio.run(workflow.retrieve_lobbying({"bill": bill}))

    assert finance["finance"]["source"] == "openfec_unavailable"
    assert finance["finance"]["confidence"] == "low"
    assert lobbying["lobbying"]["source"] == "lobbying_disclosure_unavailable"
    assert lobbying["lobbying"]["registrations"] == []


def test_bill_lookup_workflow_fallback_explains_election_bill_stakes():
    workflow = BillLookupWorkflow(settings=Settings(openai_api_live=False))
    bill = BillRecord(
        congress_bill_id="hr-22-119",
        title="SAVE Act",
        summary="Requires documentary proof of U.S. citizenship to register for federal elections.",
        sponsor="Rep. Roy, Chip [R-TX-21]",
        latest_action="Received in the Senate.",
        status="introduced",
        topic="Elections",
    )

    report = workflow._template_report(
        {
            "bill": bill,
            "stakeholders": {"possible_supporters": [], "possible_opponents": []},
            "caveats": [],
            "confidence": "medium",
        }
    )

    assert "What The Bill Does" in report["analysis_sections"]
    assert "election-integrity" in report["analysis_sections"]["Why Supporters Want It"]
    assert "eligible voters" in report["analysis_sections"]["Why Critics Are Concerned"]
    assert "registration could require more paperwork" in report["analysis_sections"]["How It Could Affect Daily Life"]
