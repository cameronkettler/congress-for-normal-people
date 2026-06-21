from datetime import date
from typing import Any, TypedDict

import httpx
from pydantic import ValidationError

from packages.agents.bill_lookup.report_generator import OpenAIReportGenerator
from packages.ingestion.congress import CongressClient
from packages.ingestion.fec import FECClient
from packages.shared.config import Settings, get_settings
from packages.shared.schemas import (
    RepresentativeActivityItem,
    RepresentativeDeepDive,
    RepresentativeRecord,
    SourceReference,
)

try:
    from langgraph.graph import END, StateGraph
except ImportError:  # pragma: no cover
    END = "__end__"
    StateGraph = None


class RepresentativeDeepDiveState(TypedDict, total=False):
    representative: RepresentativeRecord
    watchlist_topics: list[str]
    congress_profile: dict[str, Any]
    recent_legislation: list[dict[str, Any]]
    finance: dict[str, Any]
    web_context: dict[str, Any] | None
    result: RepresentativeDeepDive


class RepresentativeDeepDiveWorkflow:
    def __init__(
        self,
        congress_client: CongressClient | None = None,
        fec_client: FECClient | None = None,
        report_generator: OpenAIReportGenerator | None = None,
        settings: Settings | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.congress = congress_client or CongressClient(self.settings)
        self.fec = fec_client or FECClient(self.settings)
        self.report_generator = report_generator or OpenAIReportGenerator(self.settings)
        self.graph = self._build_graph()

    async def run(
        self,
        *,
        representative: RepresentativeRecord,
        watchlist_topics: list[str],
    ) -> RepresentativeDeepDive:
        initial: RepresentativeDeepDiveState = {
            "representative": representative,
            "watchlist_topics": watchlist_topics,
        }
        if self.graph is None:
            state = await self._run_fallback(initial)
        else:
            state = await self.graph.ainvoke(initial)
        return state["result"]

    async def run_with_progress(
        self,
        *,
        representative: RepresentativeRecord,
        watchlist_topics: list[str],
    ):
        state: RepresentativeDeepDiveState = {
            "representative": representative,
            "watchlist_topics": watchlist_topics,
        }
        for step_name, label, detail, step in self._progress_steps():
            yield {
                "type": "progress",
                "step": step_name,
                "representative": representative.name,
                "label": label,
                "detail": detail,
            }
            state.update(await step(state))
        yield {"type": "item", "data": state["result"]}

    def _progress_steps(self):
        return (
            (
                "retrieve_congress_profile",
                "Reading official member profile",
                "Checking Congress.gov member data, service dates, and committees.",
                self.retrieve_congress_profile,
            ),
            (
                "retrieve_legislation",
                "Reviewing recent legislative activity",
                "Looking for sponsored legislation and policy areas tied to this member.",
                self.retrieve_legislation,
            ),
            (
                "retrieve_finance",
                "Checking campaign-finance coverage",
                "Looking for public campaign-finance records that can add context.",
                self.retrieve_finance,
            ),
            (
                "generate_public_context",
                "Running AI-assisted public research",
                "Using web search to summarize public themes, watchlist overlap, and caveats.",
                self.generate_public_context,
            ),
            (
                "assemble_deep_dive",
                "Organizing the deep dive",
                "Combining official data, finance coverage, and public-source context.",
                self.assemble_deep_dive,
            ),
        )

    def _build_graph(self):
        if StateGraph is None:
            return None
        workflow = StateGraph(RepresentativeDeepDiveState)
        workflow.add_node("retrieve_congress_profile", self.retrieve_congress_profile)
        workflow.add_node("retrieve_legislation", self.retrieve_legislation)
        workflow.add_node("retrieve_finance", self.retrieve_finance)
        workflow.add_node("generate_public_context", self.generate_public_context)
        workflow.add_node("assemble_deep_dive", self.assemble_deep_dive)
        workflow.set_entry_point("retrieve_congress_profile")
        workflow.add_edge("retrieve_congress_profile", "retrieve_legislation")
        workflow.add_edge("retrieve_legislation", "retrieve_finance")
        workflow.add_edge("retrieve_finance", "generate_public_context")
        workflow.add_edge("generate_public_context", "assemble_deep_dive")
        workflow.add_edge("assemble_deep_dive", END)
        return workflow.compile()

    async def _run_fallback(self, state: RepresentativeDeepDiveState) -> RepresentativeDeepDiveState:
        for step in (
            self.retrieve_congress_profile,
            self.retrieve_legislation,
            self.retrieve_finance,
            self.generate_public_context,
            self.assemble_deep_dive,
        ):
            state.update(await step(state))
        return state

    async def retrieve_congress_profile(self, state: RepresentativeDeepDiveState) -> RepresentativeDeepDiveState:
        try:
            return {
                "congress_profile": await self.congress.get_member_profile(state["representative"])
            }
        except (httpx.TimeoutException, httpx.HTTPError, Exception):
            return {"congress_profile": {"terms": [], "committees": [], "serving_since": None}}

    async def retrieve_legislation(self, state: RepresentativeDeepDiveState) -> RepresentativeDeepDiveState:
        try:
            return {
                "recent_legislation": await self.congress.list_member_sponsored_legislation(
                    state["representative"],
                    limit=5,
                )
            }
        except (httpx.TimeoutException, httpx.HTTPError, Exception):
            return {"recent_legislation": []}

    async def retrieve_finance(self, state: RepresentativeDeepDiveState) -> RepresentativeDeepDiveState:
        try:
            return {
                "finance": await self.fec.get_candidate_finance_patterns(state["representative"].name)
            }
        except (httpx.TimeoutException, httpx.HTTPError, Exception):
            return {
                "finance": {
                    "source": "openfec_unavailable",
                    "candidate_matches": [],
                    "patterns": [],
                    "confidence": "low",
                    "warning": "Campaign finance data unavailable or timed out.",
                }
            }

    async def generate_public_context(self, state: RepresentativeDeepDiveState) -> RepresentativeDeepDiveState:
        try:
            web_context = await self.report_generator.generate_representative_deep_dive_context(
                representative=state["representative"].model_dump(mode="json"),
                congress_profile=state.get("congress_profile", {}),
                recent_legislation=state.get("recent_legislation", []),
                finance=state.get("finance", {}),
                watchlist_topics=state.get("watchlist_topics", []),
            )
            return {"web_context": web_context}
        except Exception:
            return {"web_context": None}

    async def assemble_deep_dive(self, state: RepresentativeDeepDiveState) -> RepresentativeDeepDiveState:
        representative = state["representative"]
        congress_profile = state.get("congress_profile", {})
        web_context = state.get("web_context") or {}
        recent_legislation = self._recent_legislation_items(state.get("recent_legislation", []))
        sources = self._sources(representative, web_context)
        result = RepresentativeDeepDive(
            representative=representative,
            serving_since=web_context.get("serving_since") or congress_profile.get("serving_since"),
            next_election=web_context.get("next_election") or self._next_election(representative, congress_profile),
            committees=congress_profile.get("committees", [])[:6],
            recent_legislation=recent_legislation[:5],
            finance=state.get("finance", {}),
            money_context=web_context.get("money_context") or self._fallback_money_context(state.get("finance", {})),
            public_themes=web_context.get("public_themes", []) or self._fallback_themes(recent_legislation),
            watchlist_alignment=web_context.get("watchlist_alignment", []) or self._watchlist_alignment(
                state.get("watchlist_topics", []),
                recent_legislation,
            ),
            summary=web_context.get("summary") or self._fallback_summary(representative, recent_legislation),
            caveats=web_context.get("caveats", []) or self._fallback_caveats(),
            sources=sources,
        )
        return {"result": result}

    def _recent_legislation_items(self, items: list[dict[str, Any]]) -> list[RepresentativeActivityItem]:
        normalized: list[RepresentativeActivityItem] = []
        for item in items:
            if not isinstance(item, dict) or not item.get("title"):
                continue
            try:
                normalized.append(RepresentativeActivityItem(**item))
            except (TypeError, ValidationError):
                continue
        return normalized

    def _next_election(
        self,
        representative: RepresentativeRecord,
        congress_profile: dict[str, Any],
    ) -> str:
        terms = congress_profile.get("terms", [])
        if terms:
            latest = terms[-1] if isinstance(terms[-1], dict) else {}
            end_year = latest.get("endYear") or latest.get("endDate")
            if end_year:
                return str(end_year)[:4]
        current_year = date.today().year
        if representative.chamber == "House":
            return str(current_year if current_year % 2 == 0 else current_year + 1)
        return "Senate term cycle unavailable from current data"

    def _fallback_themes(self, recent_legislation: list[RepresentativeActivityItem]) -> list[str]:
        topics = [item.policy_area for item in recent_legislation if item.policy_area]
        return [f"Recent sponsored legislation touches {topic}." for topic in topics[:3]]

    def _watchlist_alignment(
        self,
        watchlist_topics: list[str],
        recent_legislation: list[RepresentativeActivityItem],
    ) -> list[str]:
        alignments: list[str] = []
        lowered_topics = {topic.lower() for topic in watchlist_topics}
        for item in recent_legislation:
            haystack = f"{item.title} {item.policy_area}".lower()
            for topic in lowered_topics:
                if topic and topic in haystack:
                    alignments.append(f"{item.title} overlaps with your {topic.title()} watchlist topic.")
                    break
        return alignments[:4]

    def _fallback_summary(
        self,
        representative: RepresentativeRecord,
        recent_legislation: list[RepresentativeActivityItem],
    ) -> str:
        if recent_legislation:
            return (
                f"{representative.name} has recent sponsored legislation available from Congress.gov. "
                "Use the listed bills as a starting point for issue activity."
            )
        return (
            f"{representative.name}'s basic congressional profile is available, but recent issue activity "
            "was limited in the current source set."
        )

    def _fallback_caveats(self) -> list[str]:
        return [
            "Stock-trading disclosures are not included because no clean free provider is configured.",
            "Election timing is estimated when Congress.gov term data is incomplete.",
        ]

    def _fallback_money_context(self, finance: dict[str, Any]) -> str:
        matches = finance.get("candidate_matches", [])
        confidence = finance.get("confidence", "low")
        if matches:
            return (
                f"Campaign-finance lookup found candidate committee matches with {confidence} coverage. "
                "Review source records before treating this as a detailed fundraising profile."
            )
        if finance.get("warning"):
            return str(finance["warning"])
        return "No detailed campaign-finance profile was available from the current source set."

    def _sources(
        self,
        representative: RepresentativeRecord,
        web_context: dict[str, Any],
    ) -> list[SourceReference]:
        sources = [
            SourceReference(
                label="Congress.gov member data",
                url=representative.official_url or "https://api.congress.gov/",
                confidence="high" if representative.bioguide_id else "medium",
                description="Official congressional member and legislation data.",
            )
        ]
        for source in web_context.get("sources", []):
            if not isinstance(source, dict):
                continue
            title = str(source.get("title") or "").strip()
            url = str(source.get("url") or "").strip()
            description = str(source.get("description") or "").strip()
            if not title or not url:
                continue
            sources.append(
                SourceReference(
                    label=title,
                    url=url,
                    confidence="medium",
                    description=description or "Public source used by the AI web-search pass.",
                )
            )
            if len(sources) == 4:
                break
        return sources
