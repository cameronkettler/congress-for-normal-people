from datetime import date, datetime
from typing import Any

from pydantic import BaseModel, Field


class SourceReference(BaseModel):
    label: str
    url: str | None = None
    confidence: str = "medium"
    description: str = ""


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


class RepresentativeRecord(BaseModel):
    name: str
    chamber: str
    party: str = "Unknown"
    state: str
    district: str | None = None
    bioguide_id: str | None = None
    official_url: str | None = None


class RepresentativeBillSignal(BaseModel):
    representative: RepresentativeRecord
    signal: str
    detail: str
    ai_context: str | None = None
    ai_context_label: str = "AI-assisted context"
    sources: list[SourceReference] = Field(default_factory=list)


class UserProfileResponse(BaseModel):
    street_address: str = ""
    address_line_2: str = ""
    city: str = ""
    state: str = ""
    zip_code: str = ""
    congressional_district: str = ""
    location_confidence: str = "unknown"
    representatives: list[RepresentativeRecord] = Field(default_factory=list)
    warning: str | None = None


class StakeholderInsight(BaseModel):
    name: str
    context: str = "Related lobbying disclosure found for this bill title or policy terms."
    takeaway: str | None = None
    issue_area: str | None = None
    registrant_name: str | None = None
    filing_year: int | None = None
    filing_type: str | None = None
    recency: str | None = None
    relevance: str | None = None


class BillLookupResponse(BaseModel):
    bill: BillRecord
    sponsor: dict[str, Any]
    finance: dict[str, Any]
    lobbying: dict[str, Any]
    generated_summary: str
    generated_analysis: str
    analysis_sections: dict[str, str] = Field(default_factory=dict)
    stakeholders: dict[str, list[StakeholderInsight]]
    caveats: list[str]
    confidence: str
    representative_context: list[RepresentativeBillSignal] = Field(default_factory=list)


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
