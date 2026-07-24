import asyncio
from datetime import date

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from packages.db.models import Base, Bill, BillChangeEvent, BillMonitoring
from packages.jobs.poll_new_bills import poll_new_bills
from packages.jobs.poll_new_bills.job import backfill_missing_event_dates
from packages.jobs.poll_new_bills.events import event_fingerprint, normalize_event_type
from packages.shared.schemas import BillRecord, SourceReference


class Congress:
    last_recent_error = None
    def __init__(self, bill): self.bill = bill
    async def list_recent_bills(self, limit=10, offset=0): return [self.bill] if offset == 0 else []


class Monitor:
    async def run(self, bill): return {"topic": bill.topic, "relevant": False}


def session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)()


def test_event_fingerprint_is_stable_and_normalized():
    assert event_fingerprint("HR-1-119", "introduced", None, " Bill  introduced ") == event_fingerprint("hr-1-119", "introduced", None, "bill introduced")


def test_event_type_normalizes_high_significance_official_actions():
    assert normalize_event_type("passed", "Passed the House", fallback="status_changed") == "passed_house"


def test_repeated_poll_updates_existing_bill_without_duplicate_event():
    db = session()
    db.add_all([Bill(congress_bill_id="hr-1-119", title="Old", latest_action="Introduced", status="introduced", topic="Energy"), BillMonitoring(congress_bill_id="hr-1-119", processed=True)])
    db.commit()
    candidate = BillRecord(congress_bill_id="hr-1-119", title="Test", summary="", sponsor="", latest_action="Referred to the Committee on Energy", status="introduced", topic="Energy", sources=[SourceReference(label="Congress.gov", url="https://congress.gov/bill/1")])
    first = asyncio.run(poll_new_bills(db, workflow=Monitor(), congress_client=Congress(candidate)))
    second = asyncio.run(poll_new_bills(db, workflow=Monitor(), congress_client=Congress(candidate)))
    assert first["events_created"] == 1
    assert first["bills_updated"] == 1
    assert second["events_created"] == 0
    assert db.query(BillChangeEvent).count() == 1
    assert db.query(Bill).filter_by(congress_bill_id="hr-1-119").one().latest_action == candidate.latest_action


def test_poll_backfills_official_action_date_for_existing_event():
    db = session()
    description = "Referred to the House Committee on Energy."
    db.add_all([Bill(congress_bill_id="hr-2-119", title="Energy Act", latest_action=description, status="introduced", topic="Energy"), BillMonitoring(congress_bill_id="hr-2-119", processed=True), BillChangeEvent(congress_bill_id="hr-2-119", event_type="introduced", event_date=None, title="Energy Act", description=description, source_label="Congress.gov", topic="Energy", raw_payload={}, fingerprint=event_fingerprint("hr-2-119", "introduced", None, description))])
    db.commit()
    candidate = BillRecord(congress_bill_id="hr-2-119", title="Energy Act", summary="", sponsor="", latest_action=description, latest_action_date=date(2026, 7, 9), status="introduced", topic="Energy")
    asyncio.run(poll_new_bills(db, workflow=Monitor(), congress_client=Congress(candidate)))
    assert db.query(BillChangeEvent).one().event_date.date() == date(2026, 7, 9)


def test_detailed_bill_lookup_backfills_date_when_recent_feed_omits_it():
    db = session()
    description = "Referred to the House Committee on Energy."
    db.add(BillChangeEvent(congress_bill_id="hr-3-119", event_type="committee_activity", event_date=None, title="Energy Act", description=description, source_label="Congress.gov", topic="Energy", raw_payload={}, fingerprint=event_fingerprint("hr-3-119", "committee_activity", None, description)))
    db.commit()

    class DetailedCongress:
        async def get_bill(self, bill_id):
            return BillRecord(congress_bill_id=bill_id, title="Energy Act", summary="", sponsor="", latest_action=description, latest_action_date=date(2026, 7, 10), status="introduced", topic="Energy")

    count = asyncio.run(backfill_missing_event_dates(db, DetailedCongress()))
    assert count == 1
    assert db.query(BillChangeEvent).one().event_date.date() == date(2026, 7, 10)
