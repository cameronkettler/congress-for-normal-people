from typing import TypedDict

from packages.ingestion.congress import CongressClient
from packages.notifications.email import EmailNotificationService
from packages.shared.config import Settings, get_settings
from packages.shared.schemas import BillRecord, NotificationPayload

try:
    from langgraph.graph import END, StateGraph
except ImportError:  # pragma: no cover
    END = "__end__"
    StateGraph = None


class BillMonitoringState(TypedDict, total=False):
    bill: BillRecord
    topic: str
    relevant: bool
    summary: str
    notification: NotificationPayload


class BillMonitoringWorkflow:
    def __init__(
        self,
        congress_client: CongressClient | None = None,
        notification_service: EmailNotificationService | None = None,
        settings: Settings | None = None,
        monitored_topics: set[str] | None = None,
        email_to: str | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.congress = congress_client or CongressClient(self.settings)
        self.notifications = notification_service or EmailNotificationService(self.settings)
        self.monitored_topics = monitored_topics
        self.email_to = email_to or self.settings.email_to
        self.graph = self._build_graph()

    async def run(self, bill: BillRecord) -> BillMonitoringState:
        state: BillMonitoringState = {"bill": bill}
        if self.graph is None:
            for step in (
                self.retrieve_bill,
                self.classify_topic,
                self.summarize_bill,
                self.determine_relevance,
                self.generate_email_content,
                self.queue_notification,
            ):
                state.update(await step(state))
            return state
        return await self.graph.ainvoke(state)

    def _build_graph(self):
        if StateGraph is None:
            return None

        workflow = StateGraph(BillMonitoringState)
        workflow.add_node("retrieve_bill", self.retrieve_bill)
        workflow.add_node("classify_topic", self.classify_topic)
        workflow.add_node("summarize_bill", self.summarize_bill)
        workflow.add_node("determine_relevance", self.determine_relevance)
        workflow.add_node("generate_email_content", self.generate_email_content)
        workflow.add_node("queue_notification", self.queue_notification)

        workflow.set_entry_point("retrieve_bill")
        workflow.add_edge("retrieve_bill", "classify_topic")
        workflow.add_edge("classify_topic", "summarize_bill")
        workflow.add_edge("summarize_bill", "determine_relevance")
        workflow.add_edge("determine_relevance", "generate_email_content")
        workflow.add_edge("generate_email_content", "queue_notification")
        workflow.add_edge("queue_notification", END)
        return workflow.compile()

    async def retrieve_bill(self, state: BillMonitoringState) -> BillMonitoringState:
        return {"bill": state["bill"]}

    async def classify_topic(self, state: BillMonitoringState) -> BillMonitoringState:
        topic = self.congress.classify_topic(f"{state['bill'].title} {state['bill'].summary}")
        return {"topic": topic}

    async def summarize_bill(self, state: BillMonitoringState) -> BillMonitoringState:
        bill = state["bill"]
        return {
            "summary": (
                f"{bill.title} was introduced with latest action: {bill.latest_action}. "
                f"Primary topic: {state['topic']}."
            )
        }

    async def determine_relevance(self, state: BillMonitoringState) -> BillMonitoringState:
        topics = self.monitored_topics or set(self.settings.topics)
        return {"relevant": state["topic"] in topics}

    async def generate_email_content(self, state: BillMonitoringState) -> BillMonitoringState:
        bill = state["bill"]
        subject = f"{self.settings.app_name} alert: {state['topic']} bill {bill.congress_bill_id}"
        text = f"{state['summary']}\n\nMonitor status: {'relevant' if state['relevant'] else 'FYI'}"
        html = f"<h1>{bill.title}</h1><p>{state['summary']}</p>"
        return {
            "notification": NotificationPayload(
                recipient=self.email_to,
                subject=subject,
                html_body=html,
                text_body=text,
                bill_id=bill.congress_bill_id,
                topic=state["topic"],
            )
        }

    async def queue_notification(self, state: BillMonitoringState) -> BillMonitoringState:
        if state["relevant"]:
            await self.notifications.queue(state["notification"])
        return state
