from datetime import date, datetime, timedelta, timezone

from sqlalchemy.orm import Session

from packages.agents.bill_monitoring import BillMonitoringWorkflow
from packages.db.models import Bill, BillChangeEvent, BillMonitoring
from packages.jobs.poll_new_bills.events import detect_bill_changes, event_fingerprint
from packages.ingestion.congress import CongressClient
from packages.shared.config import get_settings
from packages.shared.schemas import BillRecord


async def poll_new_bills(
    db: Session,
    workflow: BillMonitoringWorkflow | None = None,
    congress_client: CongressClient | None = None,
    monitored_topics: set[str] | None = None,
    email_to: str | None = None,
) -> dict[str, int | str | None]:
    settings = get_settings()
    congress = congress_client or CongressClient(settings)
    monitor = workflow or BillMonitoringWorkflow(
        congress_client=congress,
        settings=settings,
        monitored_topics=monitored_topics,
        email_to=email_to,
    )
    page_limit = max(1, settings.monitoring_poll_limit)
    max_fetch = max(page_limit, settings.monitoring_poll_max_fetch)
    candidates: list[BillRecord] = []
    scanned = 0
    offset = 0
    warning: str | None = None
    action_cutoff = date.today() - timedelta(days=max(1, settings.monitoring_poll_lookback_days))

    while offset < max_fetch:
        limit = min(page_limit, max_fetch - offset)
        page = await congress.list_recent_bills(limit=limit, offset=offset)
        scanned += len(page)
        warning = getattr(congress, "last_recent_error", None)
        candidates.extend(
            candidate
            for candidate in page
            if candidate.latest_action_date is None or candidate.latest_action_date >= action_cutoff
        )
        if warning or len(page) < limit:
            break
        offset += limit

    fetched = len(candidates)
    already_seen = 0
    discovered = 0
    processed = 0
    matched_topics = 0
    notifications = 0
    changes_detected = 0
    events_created = 0
    bills_updated = 0
    seen_candidate_ids: set[str] = set()

    if fetched == 0 and warning is None:
        warning = "Congress.gov returned no recent bills for this poll window."

    for candidate in candidates:
        if candidate.congress_bill_id in seen_candidate_ids:
            continue
        seen_candidate_ids.add(candidate.congress_bill_id)

        monitoring = (
            db.query(BillMonitoring)
            .filter(BillMonitoring.congress_bill_id == candidate.congress_bill_id)
            .one_or_none()
        )
        if monitoring is not None:
            already_seen += 1
        bill = db.query(Bill).filter(Bill.congress_bill_id == candidate.congress_bill_id).one_or_none()
        state = await monitor.run(candidate)
        candidate.topic = str(state.get("topic", candidate.topic))
        if candidate.latest_action_date:
            missing_dates = db.query(BillChangeEvent).filter(
                BillChangeEvent.congress_bill_id == candidate.congress_bill_id,
                BillChangeEvent.event_date.is_(None),
                BillChangeEvent.description == candidate.latest_action,
            ).all()
            for event in missing_dates:
                event.event_date = datetime.combine(candidate.latest_action_date, datetime.min.time(), timezone.utc)
        changes = detect_bill_changes(bill, candidate)
        changes_detected += len(changes)
        for change in changes:
            fingerprint = event_fingerprint(candidate.congress_bill_id, str(change["event_type"]), change["event_date"], str(change["description"]))
            if db.query(BillChangeEvent).filter(BillChangeEvent.fingerprint == fingerprint).one_or_none() is None:
                db.add(BillChangeEvent(**change, fingerprint=fingerprint))
                events_created += 1

        if monitoring is None:
            discovered += 1
            notification_sent = bool(state.get("relevant"))
            matched_topics += int(notification_sent)
            notifications += int(notification_sent)
            db.add(BillMonitoring(congress_bill_id=candidate.congress_bill_id, processed=True, notification_sent=notification_sent))
        if bill is None:
            bill = Bill(congress_bill_id=candidate.congress_bill_id)
            db.add(bill)
        else:
            if changes:
                bills_updated += 1
        bill.title = candidate.title
        bill.summary = candidate.summary
        bill.sponsor = candidate.sponsor
        bill.introduced_date = candidate.introduced_date
        bill.latest_action = candidate.latest_action
        bill.status = candidate.status
        bill.topic = state.get("topic", candidate.topic)
        if monitoring is None:
            processed += 1

    dates_backfilled = await backfill_missing_event_dates(
        db,
        congress,
        limit=settings.briefing_max_candidates,
    )
    db.commit()
    return {
        "fetched": fetched,
        "scanned": scanned,
        "already_seen": already_seen,
        "discovered": discovered,
        "processed": processed,
        "matched_topics": matched_topics,
        "notifications": notifications,
        "changes_detected": changes_detected,
        "events_created": events_created,
        "bills_updated": bills_updated,
        "dates_backfilled": dates_backfilled,
        "warning": warning,
    }


async def backfill_missing_event_dates(
    db: Session,
    congress: CongressClient,
    *,
    limit: int = 30,
) -> int:
    """Repair legacy events using detailed bill records, which reliably include action dates."""
    if not hasattr(congress, "get_bill"):
        return 0
    missing = (
        db.query(BillChangeEvent)
        .filter(BillChangeEvent.event_date.is_(None))
        .order_by(BillChangeEvent.observed_at.desc())
        .limit(max(1, limit))
        .all()
    )
    by_bill: dict[str, list[BillChangeEvent]] = {}
    for event in missing:
        by_bill.setdefault(event.congress_bill_id, []).append(event)

    backfilled = 0
    for bill_id, events in by_bill.items():
        try:
            detailed = await congress.get_bill(bill_id)
        except Exception:
            continue
        action_date = detailed.latest_action_date
        for event in events:
            same_action = " ".join(event.description.casefold().split()) == " ".join(detailed.latest_action.casefold().split())
            resolved_date = action_date if same_action else detailed.introduced_date if event.event_type == "introduced" else None
            if resolved_date:
                event.event_date = datetime.combine(resolved_date, datetime.min.time(), timezone.utc)
                backfilled += 1
    return backfilled
