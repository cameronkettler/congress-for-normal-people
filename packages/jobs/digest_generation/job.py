from packages.shared.config import get_settings
from html import escape

from packages.shared.schemas import MonitoringBill, PolicyBriefingResponse


def build_daily_digest(bills: list[MonitoringBill]) -> str:
    if not bills:
        return "No new monitored bills matched your interests today."

    lines = [f"{get_settings().app_name} daily digest", ""]
    for bill in bills:
        lines.append(f"- {bill.congress_bill_id} | {bill.topic} | {bill.title}")
    return "\n".join(lines)


def build_policy_briefing_email(briefing: PolicyBriefingResponse) -> tuple[str, str, str]:
    """Render email from the same grounded response used by the homepage."""
    topic_label = ", ".join(briefing.topics[:3]) or "your interests"
    subject = f"Your Congress briefing: {briefing.total_items} changes across {topic_label}"
    text = [subject, ""]
    html = [f"<h1>{escape(subject)}</h1>"]
    for group in briefing.groups:
        if not group.items:
            continue
        text.extend([group.topic, ""])
        html.append(f"<h2>{escape(group.topic)}</h2>")
        for item in group.items:
            bill_labels = ", ".join(bill.display_id for bill in item.bills)
            text.extend([item.headline, f"What changed: {item.change_summary}", f"Why it matters: {item.why_it_matters}", f"Underlying bills: {bill_labels}", ""])
            links = ", ".join(f'<a href="{escape(bill.url or "#")}">{escape(bill.display_id)}</a>' for bill in item.bills)
            html.append(f"<article><h3>{escape(item.headline)}</h3><p><strong>What changed:</strong> {escape(item.change_summary)}</p><p><strong>Why it matters:</strong> {escape(item.why_it_matters)}</p><p><strong>Underlying bills:</strong> {links}</p></article>")
    html.append("<p>Manage briefing interests and email preferences in your account before enabling delivery.</p>")
    return subject, "\n".join(text), "\n".join(html)
