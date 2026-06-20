from datetime import date, datetime
from typing import Any

from pydantic import BaseModel, Field


class SourceReference(BaseModel):
    label: str
    url: str | None = None
    confidence: str = "medium"


class BillRecord(BaseModel):
    congress_bill_id: str
    title: str
    summary: str
    sponsor: str
    introduced_date: date | None = None
    latest_action: str
    status: str
    topic: str = "Uncategorized"
    sources: list[SourceReference] = Field(default_factory=list)


class BillLookupRequest(BaseModel):
    bill_id: str = Field(..., examples=["hr-1234-118"])


class StakeholderInsight(BaseModel):
    name: str
    context: str = "Related lobbying disclosure found for this bill title or policy terms."


class BillLookupResponse(BaseModel):
    bill: BillRecord
    sponsor: dict[str, Any]
    finance: dict[str, Any]
    lobbying: dict[str, Any]
    generated_summary: str
    generated_analysis: str
    stakeholders: dict[str, list[StakeholderInsight]]
    caveats: list[str]
    confidence: str


class MonitoringBill(BaseModel):
    congress_bill_id: str
    title: str
    topic: str
    summary: str
    introduced_date: date | None = None
    alert_status: str = "queued"


class MonitoringRecentResponse(BaseModel):
    items: list[MonitoringBill]
    warning: str | None = None


class NotificationPayload(BaseModel):
    recipient: str
    subject: str
    html_body: str
    text_body: str
    bill_id: str
    topic: str
    created_at: datetime = Field(default_factory=datetime.utcnow)
