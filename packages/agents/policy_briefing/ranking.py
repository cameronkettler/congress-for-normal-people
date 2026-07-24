from datetime import datetime, timezone

BASE_SCORES = {
    "became_law": 100, "sent_to_president": 90, "passed_senate": 80,
    "passed_house": 80, "committee_activity": 55, "status_changed": 45,
    "latest_action_changed": 30, "introduced": 20, "other": 10,
    "vetoed": 90, "cosponsor_change": 20,
}


def significance_score(event_type: str, observed_at: datetime, *, representative_relevant: bool = False, event_count: int = 1, has_source: bool = True, now: datetime | None = None) -> int:
    now = now or datetime.now(timezone.utc)
    observed = observed_at if observed_at.tzinfo else observed_at.replace(tzinfo=timezone.utc)
    age = now - observed
    score = BASE_SCORES.get(event_type, 10)
    score += 20 if representative_relevant else 0
    score += 10 if event_count > 1 else 0
    score += 10 if age.total_seconds() <= 86400 else 0
    score -= 20 if age.days > 7 else 0
    score -= 30 if not has_source else 0
    return score


def significance_label(score: int) -> str:
    if score >= 80:
        return "major"
    if score >= 45:
        return "notable"
    return "routine"
