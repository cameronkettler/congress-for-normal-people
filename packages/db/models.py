from datetime import datetime

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
from sqlalchemy import JSON, Column, DateTime, Integer, String, Text, func

class Base(DeclarativeBase):
    pass


class Bill(Base):
    __tablename__ = "bills"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    congress_bill_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    title: Mapped[str] = mapped_column(Text)
    summary: Mapped[str] = mapped_column(Text, default="")
    sponsor: Mapped[str] = mapped_column(String(255), default="")
    introduced_date: Mapped[datetime | None] = mapped_column(Date, nullable=True)
    latest_action: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(80), default="introduced")
    topic: Mapped[str] = mapped_column(String(120), index=True, default="Uncategorized")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    reports: Mapped[list["GeneratedReport"]] = relationship(back_populates="bill")


class BillMonitoring(Base):
    __tablename__ = "bill_monitoring"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    congress_bill_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    processed: Mapped[bool] = mapped_column(Boolean, default=False)
    first_seen: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    notification_sent: Mapped[bool] = mapped_column(Boolean, default=False)


class BillChangeEvent(Base):
    __tablename__ = "bill_change_events"
    __table_args__ = (
        UniqueConstraint("fingerprint", name="uq_bill_change_event_fingerprint"),
        Index("ix_bill_change_events_topic_observed", "topic", "observed_at"),
        Index("ix_bill_change_events_bill_observed", "congress_bill_id", "observed_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    congress_bill_id: Mapped[str] = mapped_column(String(64), index=True)
    event_type: Mapped[str] = mapped_column(String(48), index=True)
    event_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)
    title: Mapped[str] = mapped_column(Text)
    description: Mapped[str] = mapped_column(Text)
    source_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_label: Mapped[str] = mapped_column(String(160), default="Congress.gov")
    topic: Mapped[str] = mapped_column(String(120), index=True)
    raw_payload: Mapped[dict] = mapped_column(JSON, default=dict)
    fingerprint: Mapped[str] = mapped_column(String(64), unique=True, index=True)


class PolicyBriefing(Base):
    __tablename__ = "policy_briefings"
    __table_args__ = (
        UniqueConstraint("user_id", "period_start", "period_end", "topics_key", "version", name="uq_policy_briefing_generation"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    period_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    period_end: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    generated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    status: Mapped[str] = mapped_column(String(24), default="complete")
    warning: Mapped[str] = mapped_column(Text, default="")
    topics_key: Mapped[str] = mapped_column(Text)
    version: Mapped[str] = mapped_column(String(64))
    response_json: Mapped[dict] = mapped_column(JSON, default=dict)


class PolicyBriefingItem(Base):
    __tablename__ = "policy_briefing_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    briefing_id: Mapped[int] = mapped_column(ForeignKey("policy_briefings.id"), index=True)
    topic: Mapped[str] = mapped_column(String(120), index=True)
    headline: Mapped[str] = mapped_column(Text)
    change_summary: Mapped[str] = mapped_column(Text)
    why_it_matters: Mapped[str] = mapped_column(Text)
    significance: Mapped[str] = mapped_column(String(24))
    significance_score: Mapped[int] = mapped_column(Integer)
    confidence: Mapped[str] = mapped_column(String(24))
    display_order: Mapped[int] = mapped_column(Integer)
    bill_ids_json: Mapped[list[str]] = mapped_column(JSON, default=list)
    event_ids_json: Mapped[list[int]] = mapped_column(JSON, default=list)
    sources_json: Mapped[list[dict]] = mapped_column(JSON, default=list)
    caveats_json: Mapped[list[str]] = mapped_column(JSON, default=list)


class RepresentativeSearchCache(Base):
    __tablename__ = "representative_search_cache"

    id = Column(Integer, primary_key=True)
    representative_name = Column(String, nullable=False, index=True)
    bill_id = Column(String, nullable=False, index=True)
    query = Column(Text, nullable=False)
    results_json = Column(JSON, nullable=False)
    created_at = Column(DateTime, server_default=func.now(), nullable=False)


class BillPositionSearchCache(Base):
    __tablename__ = "bill_position_search_cache"

    id = Column(Integer, primary_key=True)

    bill_id = Column(String, nullable=False, unique=True, index=True)

    results_json = Column(JSON, nullable=False)

    created_at = Column(
        DateTime,
        server_default=func.now(),
        nullable=False,
    )


class ReportCache(Base):
    __tablename__ = "report_cache"
    __table_args__ = (
        UniqueConstraint("congress_bill_id", "profile_key", name="uq_report_cache_bill_profile"),
    )

    id = Column(Integer, primary_key=True)
    congress_bill_id = Column(String(64), nullable=False, index=True)
    profile_key = Column(String(160), nullable=False, index=True)
    response_json = Column(JSON, nullable=False)
    created_at = Column(DateTime, server_default=func.now(), nullable=False)


class RepresentativeDeepDiveCache(Base):
    __tablename__ = "representative_deep_dive_cache"
    __table_args__ = (
        UniqueConstraint("profile_key", "topics_key", name="uq_representative_deep_dive_profile_topics"),
    )

    id = Column(Integer, primary_key=True)
    profile_key = Column(String(160), nullable=False, index=True)
    topics_key = Column(Text, nullable=False)
    response_json = Column(JSON, nullable=False)
    created_at = Column(DateTime, server_default=func.now(), nullable=False)


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(512))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    sessions: Mapped[list["UserSession"]] = relationship(back_populates="user")
    topic_preferences: Mapped[list["UserTopicPreference"]] = relationship(back_populates="user")
    profile: Mapped["UserProfile"] = relationship(back_populates="user", uselist=False)


class UserSession(Base):
    __tablename__ = "user_sessions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    token: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    user: Mapped[User] = relationship(back_populates="sessions")


class UserInterest(Base):
    __tablename__ = "user_interests"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    topic: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)


class UserTopicPreference(Base):
    __tablename__ = "user_topic_preferences"
    __table_args__ = (UniqueConstraint("user_id", "topic", name="uq_user_topic_preference"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    topic: Mapped[str] = mapped_column(String(120), index=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)

    user: Mapped[User] = relationship(back_populates="topic_preferences")


class UserProfile(Base):
    __tablename__ = "user_profiles"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), unique=True, index=True)
    street_address: Mapped[str] = mapped_column(Text, default="")
    address_line_2: Mapped[str] = mapped_column(Text, default="")
    city: Mapped[str] = mapped_column(String(120), default="")
    state: Mapped[str] = mapped_column(String(2), default="")
    zip_code: Mapped[str] = mapped_column(String(10), default="")
    congressional_district: Mapped[str] = mapped_column(String(8), default="")
    location_confidence: Mapped[str] = mapped_column(String(40), default="unknown")
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    user: Mapped[User] = relationship(back_populates="profile")


class GeneratedReport(Base):
    __tablename__ = "generated_reports"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    bill_id: Mapped[int] = mapped_column(ForeignKey("bills.id"), index=True)
    generated_summary: Mapped[str] = mapped_column(Text)
    generated_analysis: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    bill: Mapped[Bill] = relationship(back_populates="reports")
