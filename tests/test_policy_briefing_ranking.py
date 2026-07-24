from datetime import datetime, timedelta, timezone

from packages.agents.policy_briefing.ranking import significance_label, significance_score


def test_significance_ranking_is_deterministic():
    now = datetime.now(timezone.utc)
    assert significance_score("became_law", now, now=now) > significance_score("introduced", now, now=now)
    assert significance_label(80) == "major"
    assert significance_label(45) == "notable"
    assert significance_score("introduced", now - timedelta(days=8), now=now) < significance_score("introduced", now, now=now)


def test_representative_relevance_bonus_is_twenty_points():
    now = datetime.now(timezone.utc)
    base = significance_score("introduced", now, now=now)
    assert significance_score("introduced", now, representative_relevant=True, now=now) == base + 20
