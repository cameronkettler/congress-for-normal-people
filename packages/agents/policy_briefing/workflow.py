from dataclasses import dataclass
from datetime import datetime, timezone
import re
from typing import TypedDict

from sqlalchemy.orm import Session

from packages.agents.policy_briefing.ranking import significance_label, significance_score
from packages.db.models import Bill, BillChangeEvent, UserProfile, UserTopicPreference
from packages.shared.bills import display_bill_id
from packages.shared.config import Settings, get_settings
from packages.shared.topics import TOPIC_KEYWORDS
from packages.jobs.poll_new_bills.events import normalize_event_type
from packages.shared.schemas import BillBriefReference, PolicyBriefingItem, PolicyBriefingResponse, PolicyBriefingTopicGroup, PolicyChangeEvidence, SourceReference

try:
    from langgraph.graph import END, StateGraph
except ImportError:  # deterministic execution remains available without LangGraph
    END = None
    StateGraph = None


class PolicyBriefingState(TypedDict, total=False):
    user_id: int
    enabled_topics: list[str]
    warning: str | None


@dataclass(frozen=True)
class PolicyBriefingRequest:
    user_id: int
    period_start: datetime
    period_end: datetime
    max_items: int = 6
    topic_limit: int = 3
    force_refresh: bool = False


class PolicyBriefingWorkflow:
    """Deterministic briefing workflow; nodes are kept explicit for optional graph orchestration."""

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self.graph = self._build_graph()

    def _build_graph(self):
        if StateGraph is None:
            return None
        graph = StateGraph(PolicyBriefingState)
        nodes = ["load_user_context", "load_change_events", "group_related_events", "rank_changes", "generate_explanations", "validate_grounding", "personalize_ordering", "persist_briefing", "build_response"]
        for name in nodes:
            graph.add_node(name, lambda state: state)
        graph.set_entry_point(nodes[0])
        for current, following in zip(nodes, nodes[1:]):
            graph.add_edge(current, following)
        graph.add_edge(nodes[-1], END)
        return graph.compile()

    def run(self, db: Session, request: PolicyBriefingRequest) -> PolicyBriefingResponse:
        topics, profile = self.load_user_context(db, request.user_id)
        if not topics:
            return self.build_response(request, [], [], "Choose at least one policy interest to create your briefing.")
        events, warning = self.load_change_events(db, topics, request)
        grouped = self.group_related_events(events)
        ranked = self.rank_changes(grouped, profile)
        items = self.generate_explanations(db, ranked[: request.max_items])
        items = [item for item in items if self.validate_grounding(item)]
        return self.build_response(request, topics, items, warning)

    def load_user_context(self, db: Session, user_id: int):
        topics = sorted(row.topic for row in db.query(UserTopicPreference).filter(UserTopicPreference.user_id == user_id, UserTopicPreference.enabled.is_(True)).all())
        profile = db.query(UserProfile).filter(UserProfile.user_id == user_id).one_or_none()
        return topics, profile

    def load_change_events(self, db: Session, topics: list[str], request: PolicyBriefingRequest):
        query = db.query(BillChangeEvent).filter(
            BillChangeEvent.topic.in_(topics),
            BillChangeEvent.event_date.is_not(None),
            BillChangeEvent.event_date >= request.period_start,
            BillChangeEvent.event_date <= request.period_end,
        ).order_by(BillChangeEvent.event_date.desc()).limit(self.settings.briefing_max_candidates)
        events = [event for event in query.all() if self.topic_match_confidence(event) >= 0.75]
        if events:
            return events, None
        any_events = db.query(BillChangeEvent.id).first()
        warning = (
            "No qualifying changes were captured across your topics in this period. "
            "This reflects the app's tracked Congress.gov records, not a claim that Congress had no activity."
            if any_events
            else "No tracked changes are available yet. Run the Congress.gov poll to begin tracking changes."
        )
        return [], warning

    def group_related_events(self, events):
        grouped: dict[str, list[BillChangeEvent]] = {}
        for event in events:
            grouped.setdefault(event.congress_bill_id, []).append(event)
        return list(grouped.values())

    def rank_changes(self, groups, profile):
        ranked = []
        for events in groups:
            primary = max(events, key=lambda event: significance_score(event.event_type, event.observed_at, event_count=len(events), has_source=bool(event.source_label)))
            effective_event_type = normalize_event_type("", primary.description, fallback=primary.event_type)
            score = significance_score(effective_event_type, primary.observed_at, event_count=len(events), has_source=bool(primary.source_label))
            ranked.append((score, primary.observed_at, events))
        return [events for _, _, events in sorted(ranked, key=lambda row: (row[0], row[1]), reverse=True)]

    def generate_explanations(self, db: Session, groups):
        items = []
        for events in groups:
            primary = max(events, key=lambda event: significance_score(event.event_type, event.observed_at, event_count=len(events), has_source=bool(event.source_label)))
            bill = db.query(Bill).filter(Bill.congress_bill_id == primary.congress_bill_id).one_or_none()
            if bill is None:
                continue
            effective_event_type = normalize_event_type("", primary.description, fallback=primary.event_type)
            score = significance_score(effective_event_type, primary.observed_at, event_count=len(events), has_source=bool(primary.source_label))
            source = SourceReference(label=primary.source_label, url=primary.source_url, confidence="high", description="Official legislative action data.")
            evidence = [PolicyChangeEvidence(event_id=event.id, event_type=event.event_type, event_date=event.event_date, description=event.description, source=SourceReference(label=event.source_label, url=event.source_url, confidence="high")) for event in events]
            items.append(PolicyBriefingItem(topic=primary.topic, headline=self.change_headline(bill.title, effective_event_type), change_summary=primary.description, why_it_matters=self.fallback_impact(effective_event_type), what_happens_next=self.next_step(effective_event_type), significance=significance_label(score), significance_score=score, confidence="high" if primary.source_url else "medium", bills=[BillBriefReference(congress_bill_id=bill.congress_bill_id, display_id=display_bill_id(bill.congress_bill_id), title=bill.title, status=bill.status, latest_action=bill.latest_action, url=primary.source_url)], evidence=evidence, sources=[source], caveats=["This explanation is based on official bill metadata."]))
        return items

    @staticmethod
    def topic_match_confidence(event: BillChangeEvent) -> float:
        """Conservative display gate: classified topic plus a visible lexical policy signal."""
        keywords = TOPIC_KEYWORDS.get(event.topic, [])
        payload = event.raw_payload or {}
        title = str(payload.get("title") or event.title).lower()
        details = " ".join((str(payload.get("summary") or ""), event.description)).lower()
        if any(PolicyBriefingWorkflow.keyword_matches(title, keyword) for keyword in keywords):
            return 1.0
        if any(PolicyBriefingWorkflow.keyword_matches(details, keyword) for keyword in keywords):
            return 0.8
        return 0.0

    @staticmethod
    def keyword_matches(text: str, keyword: str) -> bool:
        term = keyword.strip().lower()
        if not term:
            return False
        return re.search(rf"(?<![a-z0-9]){re.escape(term)}(?![a-z0-9])", text) is not None

    @staticmethod
    def change_headline(title: str, event_type: str) -> str:
        action = {"introduced": "introduced in Congress", "committee_activity": "sent to committee", "passed_house": "passed the House", "passed_senate": "passed the Senate", "sent_to_president": "sent to the president", "became_law": "signed into law", "vetoed": "vetoed"}.get(event_type, "received a new congressional action")
        return f"{title} {action}"

    @staticmethod
    def fallback_impact(event_type: str) -> str:
        if event_type == "became_law":
            return "This measure has become law. Its practical effects depend on the enacted text and implementation."
        if event_type in {"passed_house", "passed_senate"}:
            return "This advances the proposal through one chamber, but it does not by itself make the proposal law."
        if event_type == "sent_to_president":
            return "The proposal has cleared Congress and awaits presidential action. It is not law unless signed or otherwise enacted."
        if event_type == "committee_activity":
            return "The named committee now controls whether the proposal receives hearings, amendments, or a vote. This remains an early procedural step."
        if event_type == "introduced":
            return "The proposal has entered Congress but has not received committee or chamber approval."
        if event_type == "cosponsor_change":
            return "Recorded support has changed, though cosponsorship does not guarantee committee action or a vote."
        return "The official record changed, but this action alone does not make the proposal law."

    @staticmethod
    def next_step(event_type: str) -> str:
        if event_type in {"introduced", "committee_activity"}:
            return "A committee may hold hearings, amend or report the proposal, or take no further action."
        if event_type == "passed_house":
            return "The Senate must approve the same text before it can go to the president."
        if event_type == "passed_senate":
            return "The House must approve the same text before it can go to the president."
        if event_type == "sent_to_president":
            return "The president may sign or veto the measure, or allow it to become law without a signature."
        if event_type == "became_law":
            return "Agencies and affected parties may now begin implementation according to the law's effective dates."
        return "Congress may take another action, or the proposal may receive no further consideration."

    @staticmethod
    def validate_grounding(item: PolicyBriefingItem) -> bool:
        return bool(item.bills and item.evidence and item.sources and all(e.description for e in item.evidence))

    @staticmethod
    def build_response(request, topics, items, warning):
        groups = [PolicyBriefingTopicGroup(topic=topic, items=[item for item in items if item.topic == topic], has_major_change=any(item.significance == "major" for item in items if item.topic == topic)) for topic in topics]
        return PolicyBriefingResponse(period_start=request.period_start, period_end=request.period_end, generated_at=datetime.now(timezone.utc), topics=topics, groups=groups, total_items=len(items), is_personalized=bool(topics), warning=warning)
