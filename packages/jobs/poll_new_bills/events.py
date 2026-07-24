import hashlib
import re
from datetime import date, datetime, timezone

from packages.db.models import Bill
from packages.shared.schemas import BillRecord


EVENT_TYPES = {
    "introduced", "latest_action_changed", "status_changed", "committee_activity",
    "passed_house", "passed_senate", "sent_to_president", "became_law", "vetoed",
    "cosponsor_change", "other",
}


def normalize_event_type(status: str, description: str, *, fallback: str) -> str:
    text = f"{status} {description}".lower()
    patterns = (
        ("became_law", r"became (public|private) law|signed by (the )?president"),
        ("vetoed", r"veto"),
        ("sent_to_president", r"presented to president|sent to (the )?president"),
        ("passed_house", r"passed (the )?house|agreed to in house"),
        ("passed_senate", r"passed (the )?senate|agreed to in senate"),
        ("committee_activity", r"committee|referred to|reported by"),
    )
    for event_type, pattern in patterns:
        if re.search(pattern, text):
            return event_type
    return fallback if fallback in EVENT_TYPES else "other"


def event_fingerprint(bill_id: str, event_type: str, event_date: date | datetime | None, description: str) -> str:
    normalized_description = " ".join(description.lower().split())
    normalized_date = event_date.isoformat() if event_date else ""
    value = "|".join((bill_id.lower().strip(), event_type.lower().strip(), normalized_date, normalized_description))
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def detect_bill_changes(existing: Bill | None, candidate: BillRecord) -> list[dict[str, object]]:
    source = candidate.sources[0] if candidate.sources else None
    action_date = candidate.latest_action_date or candidate.introduced_date
    event_date = datetime.combine(action_date, datetime.min.time(), timezone.utc) if action_date else None
    common = {
        "congress_bill_id": candidate.congress_bill_id,
        "event_date": event_date,
        "title": candidate.title,
        "source_url": source.url if source else None,
        "source_label": source.label if source else "Congress.gov",
        "topic": candidate.topic,
        "raw_payload": candidate.model_dump(mode="json"),
    }
    changes: list[dict[str, object]] = []
    if existing is None:
        description = candidate.latest_action or f"{candidate.title} was introduced."
        changes.append({**common, "event_type": "introduced", "description": description})
        return changes
    if (existing.latest_action or "").strip() != (candidate.latest_action or "").strip():
        description = candidate.latest_action or "The latest official action changed."
        changes.append({**common, "event_type": normalize_event_type(candidate.status, description, fallback="latest_action_changed"), "description": description})
    if (existing.status or "").strip().lower() != (candidate.status or "").strip().lower():
        description = f"Status changed from {existing.status or 'unknown'} to {candidate.status or 'unknown'}."
        event_type = normalize_event_type(candidate.status, candidate.latest_action, fallback="status_changed")
        if not any(change["event_type"] == event_type for change in changes):
            changes.append({**common, "event_type": event_type, "description": description})
    return changes
