from datetime import date
from typing import Any, TypedDict

import httpx

from packages.ingestion.congress import CongressClient
from packages.ingestion.fec import FECClient
from packages.ingestion.lobbying import LobbyingDisclosureClient
from packages.shared.config import Settings, get_settings
from packages.shared.schemas import BillLookupResponse, BillRecord, StakeholderInsight

from .input_resolver import BillInputResolution, BillInputResolver
from .report_generator import OpenAIReportGenerator

try:
    from langgraph.graph import END, StateGraph
except ImportError:  # pragma: no cover - exercised only when optional dependency is absent
    END = "__end__"
    StateGraph = None


class ProviderLookupError(Exception):
    def __init__(self, provider: str, detail: str = "External data source unavailable or timed out") -> None:
        super().__init__(detail)
        self.provider = provider
        self.detail = detail


class BillLookupState(TypedDict, total=False):
    bill_id: str
    resolved_input: BillInputResolution
    bill: BillRecord
    sponsor: dict[str, Any]
    finance: dict[str, Any]
    lobbying: dict[str, Any]
    generated_summary: str
    generated_analysis: str
    analysis_sections: dict[str, str]
    stakeholders: dict[str, list[StakeholderInsight]]
    caveats: list[str]
    confidence: str


class BillLookupWorkflow:
    def __init__(
        self,
        congress_client: CongressClient | None = None,
        fec_client: FECClient | None = None,
        lobbying_client: LobbyingDisclosureClient | None = None,
        input_resolver: BillInputResolver | None = None,
        report_generator: OpenAIReportGenerator | None = None,
        settings: Settings | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.congress = congress_client or CongressClient(self.settings)
        self.fec = fec_client or FECClient(self.settings)
        self.lobbying = lobbying_client or LobbyingDisclosureClient(self.settings)
        self.input_resolver = input_resolver or BillInputResolver(self.settings)
        self.report_generator = report_generator or OpenAIReportGenerator(self.settings)
        self.graph = self._build_graph()

    async def run(self, bill_id: str) -> BillLookupResponse:
        initial: BillLookupState = {"bill_id": bill_id}
        if self.graph is None:
            state = await self._run_fallback(initial)
        else:
            state = await self.graph.ainvoke(initial)
        return BillLookupResponse(**state)

    def _build_graph(self):
        if StateGraph is None:
            return None

        workflow = StateGraph(BillLookupState)
        workflow.add_node("resolve_input", self.resolve_input)
        workflow.add_node("retrieve_bill", self.retrieve_bill)
        workflow.add_node("retrieve_sponsor", self.retrieve_sponsor)
        workflow.add_node("retrieve_finance", self.retrieve_finance)
        workflow.add_node("retrieve_lobbying", self.retrieve_lobbying)
        workflow.add_node("aggregate_findings", self.aggregate_findings)
        workflow.add_node("generate_report", self.generate_report)

        workflow.set_entry_point("resolve_input")
        workflow.add_edge("resolve_input", "retrieve_bill")
        workflow.add_edge("retrieve_bill", "retrieve_sponsor")
        workflow.add_edge("retrieve_sponsor", "retrieve_finance")
        workflow.add_edge("retrieve_finance", "retrieve_lobbying")
        workflow.add_edge("retrieve_lobbying", "aggregate_findings")
        workflow.add_edge("aggregate_findings", "generate_report")
        workflow.add_edge("generate_report", END)
        return workflow.compile()

    async def _run_fallback(self, state: BillLookupState) -> BillLookupState:
        for step in (
            self.resolve_input,
            self.retrieve_bill,
            self.retrieve_sponsor,
            self.retrieve_finance,
            self.retrieve_lobbying,
            self.aggregate_findings,
            self.generate_report,
        ):
            state.update(await step(state))
        return state

    async def resolve_input(self, state: BillLookupState) -> BillLookupState:
        resolution = await self.input_resolver.resolve(state["bill_id"])
        return {"resolved_input": resolution, "bill_id": resolution.bill_id}

    async def retrieve_bill(self, state: BillLookupState) -> BillLookupState:
        try:
            return {"bill": await self.congress.get_bill(state["bill_id"])}
        except (httpx.TimeoutException, httpx.HTTPStatusError, httpx.HTTPError, Exception) as exc:
            raise ProviderLookupError("Congress.gov") from exc

    async def retrieve_sponsor(self, state: BillLookupState) -> BillLookupState:
        try:
            return {"sponsor": await self.congress.get_sponsor(state["bill"].sponsor)}
        except (httpx.TimeoutException, httpx.HTTPStatusError, httpx.HTTPError, Exception):
            return {
                "sponsor": {
                    "name": state["bill"].sponsor,
                    "party": "Unknown",
                    "state": "Unknown",
                    "committees": ["Sponsor detail unavailable from Congress.gov."],
                    "confidence": "low",
                }
            }

    async def retrieve_finance(self, state: BillLookupState) -> BillLookupState:
        try:
            return {"finance": await self.fec.get_candidate_finance_patterns(state["bill"].sponsor)}
        except (httpx.TimeoutException, httpx.HTTPStatusError, httpx.HTTPError, Exception):
            return {
                "finance": {
                    "source": "openfec_unavailable",
                    "sponsor": state["bill"].sponsor,
                    "candidate_matches": [],
                    "patterns": [],
                    "confidence": "low",
                    "warning": "Campaign finance data unavailable or timed out.",
                }
            }

    async def retrieve_lobbying(self, state: BillLookupState) -> BillLookupState:
        try:
            return {"lobbying": await self.lobbying.search_activity(state["bill"].title)}
        except (httpx.TimeoutException, httpx.HTTPStatusError, httpx.HTTPError, Exception):
            return {
                "lobbying": {
                    "source": "lobbying_disclosure_unavailable",
                    "query": state["bill"].title,
                    "registrations": [],
                    "confidence": "low",
                    "warning": "Lobbying disclosure data unavailable or timed out.",
                }
            }

    async def aggregate_findings(self, state: BillLookupState) -> BillLookupState:
        lobbying_clients = self._stakeholder_insights(
            state.get("lobbying", {}).get("registrations", [])
        )
        return {
            "stakeholders": {
                "possible_supporters": lobbying_clients[:1],
                "possible_opponents": lobbying_clients[1:],
            },
            "caveats": [
                "Provider data can lag official filings and should be verified before publication.",
                "Stakeholder posture is inferred from disclosed activity and bill subject matter.",
            ],
            "confidence": self._confidence(state),
        }

    def _stakeholder_insights(self, registrations: list[dict[str, Any]]) -> list[StakeholderInsight]:
        insights: list[StakeholderInsight] = []
        seen: set[str] = set()
        for item in registrations:
            name = (
                item.get("client_name")
                or item.get("registrant_name")
                or self._nested_name(item.get("client"))
                or self._nested_name(item.get("registrant"))
            )
            if not name:
                continue
            normalized = name.strip()
            key = normalized.casefold()
            if normalized and key not in seen:
                insights.append(
                    StakeholderInsight(
                        name=normalized,
                        context=self._stakeholder_context(item),
                        takeaway=self._stakeholder_takeaway(item),
                        issue_area=self._short_issue_area(item),
                        registrant_name=self._as_string(item.get("registrant_name")),
                        filing_year=self._as_int(item.get("filing_year")),
                        filing_type=self._as_string(item.get("filing_type_display")),
                        recency=self._filing_recency(item),
                        relevance=self._stakeholder_relevance(item),
                    )
                )
                seen.add(key)
        return insights

    def _nested_name(self, value: Any) -> str | None:
        if isinstance(value, dict):
            name = value.get("name")
            return name if isinstance(name, str) else None
        return None

    def _stakeholder_context(self, item: dict[str, Any]) -> str:
        issue = self._short_issue_area(item)
        if issue:
            return f"Disclosure topic match: {issue}."
        return "Related lobbying disclosure found for this bill title or policy terms."

    def _stakeholder_takeaway(self, item: dict[str, Any]) -> str:
        issue = self._short_issue_area(item)
        recency = self._filing_recency(item)
        if issue:
            return (
                f"This surfaced because a lobbying disclosure mentioned {issue.lower()} topics; "
                f"{recency.lower()} makes it context, not proof of a position on this bill."
            )
        return "This surfaced from broad disclosure matching and should not be read as support or opposition."

    def _stakeholder_relevance(self, item: dict[str, Any]) -> str:
        if self._filing_recency(item) == "Historical filing":
            return "Historical context only; not evidence of current support or opposition."
        return "Topic overlap only; not evidence of support or opposition."

    def _short_issue_area(self, item: dict[str, Any]) -> str | None:
        issue = self._as_string(item.get("issue"))
        if not issue:
            return None
        pieces = [piece.strip() for piece in issue.split(",") if piece.strip()]
        return ", ".join(pieces[:3]) if pieces else None

    def _filing_recency(self, item: dict[str, Any]) -> str:
        filing_year = self._as_int(item.get("filing_year"))
        if filing_year is None:
            return "Unknown filing date"
        current_year = date.today().year
        if filing_year >= current_year - 1:
            return "Recent filing"
        if filing_year >= current_year - 4:
            return "Older filing"
        return "Historical filing"

    def _as_string(self, value: Any) -> str | None:
        return value.strip() if isinstance(value, str) and value.strip() else None

    def _as_int(self, value: Any) -> int | None:
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    async def generate_report(self, state: BillLookupState) -> BillLookupState:
        fallback = self._template_report(state)
        return await self.report_generator.generate(state=state, fallback=fallback)

    def _template_report(self, state: BillLookupState) -> BillLookupState:
        bill = state["bill"]
        supporters = ", ".join(item.name for item in state["stakeholders"]["possible_supporters"])
        opponents = ", ".join(item.name for item in state["stakeholders"]["possible_opponents"])
        summary = f"{bill.congress_bill_id}: {bill.title}. {bill.summary}"
        analysis = (
            f"{bill.title} is a {bill.topic} bill currently marked {bill.status}. "
            "The political stakes should be read from the bill summary and status first; finance and "
            "lobbying disclosures are context, not proof of influence."
        )
        return {
            "generated_summary": summary,
            "generated_analysis": analysis,
            "analysis_sections": {
                "What The Bill Does": bill.summary,
                "Why Supporters Want It": self._supporter_argument(bill),
                "Why Critics Are Concerned": self._critic_argument(bill),
                "How It Could Affect Daily Life": self._daily_life_impact(bill),
                "Political And Influence Read": (
                    f"Status: {bill.status}. Latest action: {bill.latest_action} "
                    f"Related disclosure matches: {supporters or opponents or 'none found'}. "
                    "Treat these matches as topic context unless a filing directly names this bill."
                ),
            },
            "caveats": state["caveats"],
            "confidence": state["confidence"],
        }

    def _supporter_argument(self, bill: BillRecord) -> str:
        text = f"{bill.title} {bill.summary}".lower()
        if "voter" in text or "citizenship" in text or "election" in text:
            return (
                "Supporters are likely to frame this as an election-integrity bill: requiring proof "
                "of citizenship before registration is meant to reassure voters that federal voter "
                "rolls include only eligible citizens."
            )
        return "Supporters would likely argue the bill addresses a concrete problem in its policy area."

    def _critic_argument(self, bill: BillRecord) -> str:
        text = f"{bill.title} {bill.summary}".lower()
        if "voter" in text or "citizenship" in text or "election" in text:
            return (
                "Critics are likely to focus on access: documentary proof requirements can make "
                "registration harder for eligible voters who lack easy access to passports, birth "
                "certificates, or updated identity documents."
            )
        return "Critics may question cost, implementation burden, or uneven effects across communities."

    def _daily_life_impact(self, bill: BillRecord) -> str:
        text = f"{bill.title} {bill.summary}".lower()
        if "voter" in text or "citizenship" in text or "election" in text:
            return (
                "For voters, registration could require more paperwork and better access to citizenship "
                "documents. For election offices, it could mean new verification processes, list "
                "maintenance work, and more legal risk."
            )
        return "The day-to-day impact depends on how agencies implement the bill and who must comply."

    def _confidence(self, state: BillLookupState) -> str:
        confidences = {
            state.get("finance", {}).get("confidence", "low"),
            state.get("lobbying", {}).get("confidence", "low"),
        }
        return "medium" if "medium" in confidences else "low"
