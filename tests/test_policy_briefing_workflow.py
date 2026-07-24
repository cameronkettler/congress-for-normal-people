from datetime import datetime, timedelta, timezone

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from packages.agents.policy_briefing import PolicyBriefingRequest, PolicyBriefingWorkflow
from packages.db.models import Base, Bill, BillChangeEvent, UserTopicPreference
from packages.jobs.poll_new_bills.events import event_fingerprint
from packages.shared.config import Settings


def test_workflow_filters_topics_and_builds_grounded_fallback():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine)()
    now = datetime.now(timezone.utc)
    db.add_all([UserTopicPreference(user_id=1, topic="Energy", enabled=True), UserTopicPreference(user_id=1, topic="Defense", enabled=False), Bill(congress_bill_id="hr-2-119", title="Grid Act", latest_action="Passed the House", status="passed_house", topic="Energy")])
    description = "Passed the House by recorded vote."
    db.add(BillChangeEvent(congress_bill_id="hr-2-119", event_type="passed_house", event_date=now, observed_at=now, title="Grid Act", description=description, source_url="https://congress.gov/bill/2", source_label="Congress.gov", topic="Energy", raw_payload={}, fingerprint=event_fingerprint("hr-2-119", "passed_house", None, description)))
    db.commit()
    response = PolicyBriefingWorkflow(Settings(openai_api_live=False)).run(db, PolicyBriefingRequest(1, now - timedelta(days=1), now + timedelta(seconds=1)))
    assert response.topics == ["Energy"]
    assert response.total_items == 1
    item = response.groups[0].items[0]
    assert item.bills and item.evidence and item.sources
    assert "does not by itself make" in item.why_it_matters


def test_housing_keyword_does_not_match_president_or_current():
    assert not PolicyBriefingWorkflow.keyword_matches("the president in the current fiscal year", "rent")
    assert PolicyBriefingWorkflow.keyword_matches("rental housing assistance", "rent") is False
    assert PolicyBriefingWorkflow.keyword_matches("rent assistance", "rent")


def test_briefing_window_uses_official_action_date_not_ingestion_time():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine)()
    now = datetime.now(timezone.utc)
    db.add_all([
        UserTopicPreference(user_id=1, topic="Healthcare", enabled=True),
        Bill(congress_bill_id="hres-10-119", title="HEALTH Act", latest_action="Referred to committee", status="introduced", topic="Healthcare"),
        BillChangeEvent(congress_bill_id="hres-10-119", event_type="committee_activity", event_date=now - timedelta(days=300), observed_at=now, title="HEALTH Act", description="Referred to the House Committee on Health.", source_label="Congress.gov", topic="Healthcare", raw_payload={}, fingerprint="old-action"),
        BillChangeEvent(congress_bill_id="hr-78-119", event_type="committee_activity", event_date=None, observed_at=now, title="Health Safety Act", description="Referred to committee.", source_label="Congress.gov", topic="Healthcare", raw_payload={}, fingerprint="undated-action"),
    ])
    db.commit()
    response = PolicyBriefingWorkflow(Settings()).run(db, PolicyBriefingRequest(1, now - timedelta(days=7), now))
    assert response.total_items == 0
    assert response.groups[0].items == []
