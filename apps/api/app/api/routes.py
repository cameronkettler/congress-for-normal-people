import logging

import httpx
from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from apps.api.app.auth import (
    create_session,
    current_user,
    ensure_topic_preferences,
    hash_password,
    normalize_email,
    verify_password,
)
from packages.agents.bill_lookup import BillLookupWorkflow
from packages.agents.bill_lookup.input_resolver import BillInputResolutionError
from packages.agents.bill_monitoring import BillMonitoringWorkflow
from packages.db import get_session
from packages.db.models import Bill, BillMonitoring, GeneratedReport, User, UserSession, UserTopicPreference
from packages.ingestion.congress import CongressClient
from packages.jobs.poll_new_bills import poll_new_bills
from packages.shared.config import get_settings
from packages.shared.schemas import BillLookupRequest, BillLookupResponse, MonitoringBill, MonitoringRecentResponse

router = APIRouter()
logger = logging.getLogger(__name__)


class AuthRequest(BaseModel):
    email: str
    password: str


class AuthResponse(BaseModel):
    token: str
    user: dict[str, str | int]


class InterestUpdate(BaseModel):
    enabled: bool


@router.post("/auth/register", response_model=AuthResponse)
def register(payload: AuthRequest, db: Session = Depends(get_session)):
    email = normalize_email(payload.email)
    if len(payload.password) < 8:
        raise HTTPException(status_code=422, detail="Password must be at least 8 characters.")
    if db.query(User).filter(User.email == email).one_or_none() is not None:
        raise HTTPException(status_code=409, detail="An account with that email already exists.")

    user = User(email=email, password_hash=hash_password(payload.password))
    db.add(user)
    db.flush()
    ensure_topic_preferences(db, user)
    session = create_session(db, user)
    db.commit()
    return auth_response(user, session.token)


@router.post("/auth/login", response_model=AuthResponse)
def login(payload: AuthRequest, db: Session = Depends(get_session)):
    email = normalize_email(payload.email)
    user = db.query(User).filter(User.email == email).one_or_none()
    if user is None or not verify_password(payload.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Email or password is incorrect.")

    ensure_topic_preferences(db, user)
    session = create_session(db, user)
    db.commit()
    return auth_response(user, session.token)


@router.get("/auth/me")
def me(user: User = Depends(current_user)):
    return {"id": user.id, "email": user.email}


@router.post("/auth/logout")
def logout(
    user: User = Depends(current_user),
    db: Session = Depends(get_session),
    authorization: str | None = Header(default=None),
):
    if authorization and authorization.startswith("Bearer "):
        token = authorization.removeprefix("Bearer ").strip()
        db.query(UserSession).filter(UserSession.user_id == user.id, UserSession.token == token).delete()
        db.commit()
    return {"ok": True}


@router.post("/bills/lookup", response_model=BillLookupResponse)
async def lookup_bill(payload: BillLookupRequest, db: Session = Depends(get_session)):
    try:
        response = await BillLookupWorkflow().run(payload.bill_id)
    except BillInputResolutionError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code == 404:
            raise HTTPException(
                status_code=404,
                detail="Congress.gov did not find that bill number. Check the bill type, number, and Congress.",
            ) from exc
        raise
    bill = upsert_bill(db, response)
    db.add(
        GeneratedReport(
            bill_id=bill.id,
            generated_summary=response.generated_summary,
            generated_analysis=response.generated_analysis,
        )
    )
    db.commit()
    return response


@router.get("/monitoring/recent", response_model=MonitoringRecentResponse)
async def recent_bills(db: Session = Depends(get_session)):
    rows = db.query(Bill).order_by(Bill.created_at.desc()).limit(25).all()
    if rows:
        return MonitoringRecentResponse(items=monitoring_bill_rows(rows))

    warning = "No cached bills yet. Run polling to populate recent bills."
    logger.warning("recent bills cache empty", extra={"warning": warning})
    return MonitoringRecentResponse(
        items=[],
        warning=warning,
    )


def monitoring_bill_rows(rows: list[Bill]) -> list[MonitoringBill]:
    return [
        MonitoringBill(
            congress_bill_id=row.congress_bill_id,
            title=row.title,
            topic=row.topic,
            summary=row.summary,
            introduced_date=row.introduced_date,
            alert_status="sent",
        )
        for row in rows
    ]


@router.post("/monitoring/poll")
async def poll_monitoring(user: User = Depends(current_user), db: Session = Depends(get_session)):
    topics = enabled_topics_for_user(db, user)
    result = await poll_new_bills(
        db=db,
        workflow=BillMonitoringWorkflow(monitored_topics=topics, email_to=user.email),
        monitored_topics=topics,
        email_to=user.email,
    )
    return result


@router.post("/jobs/poll-new-bills")
async def poll_monitoring_job(
    x_job_token: str | None = Header(default=None),
    db: Session = Depends(get_session),
):
    settings = get_settings()
    if settings.job_token and x_job_token != settings.job_token:
        raise HTTPException(status_code=401, detail="Invalid job token.")
    result = await poll_new_bills(db=db, workflow=BillMonitoringWorkflow())
    return result


@router.get("/interests")
def list_interests(user: User = Depends(current_user), db: Session = Depends(get_session)):
    ensure_topic_preferences(db, user)
    db.commit()
    return (
        db.query(UserTopicPreference)
        .filter(UserTopicPreference.user_id == user.id)
        .order_by(UserTopicPreference.topic.asc())
        .all()
    )


@router.patch("/interests/{topic}")
def update_interest(
    topic: str,
    payload: InterestUpdate,
    user: User = Depends(current_user),
    db: Session = Depends(get_session),
):
    interest = (
        db.query(UserTopicPreference)
        .filter(UserTopicPreference.user_id == user.id, UserTopicPreference.topic == topic)
        .one_or_none()
    )
    if interest is None:
        interest = UserTopicPreference(user_id=user.id, topic=topic, enabled=payload.enabled)
        db.add(interest)
    else:
        interest.enabled = payload.enabled
    db.commit()
    db.refresh(interest)
    return interest


def auth_response(user: User, token: str) -> AuthResponse:
    return AuthResponse(token=token, user={"id": user.id, "email": user.email})


def enabled_topics_for_user(db: Session, user: User) -> set[str]:
    ensure_topic_preferences(db, user)
    return {
        row.topic
        for row in db.query(UserTopicPreference)
        .filter(UserTopicPreference.user_id == user.id, UserTopicPreference.enabled.is_(True))
        .all()
    }


def upsert_bill(db: Session, response: BillLookupResponse) -> Bill:
    record = response.bill
    bill = db.query(Bill).filter(Bill.congress_bill_id == record.congress_bill_id).one_or_none()
    if bill is None:
        bill = Bill(congress_bill_id=record.congress_bill_id)
        db.add(bill)

    bill.title = record.title
    bill.summary = record.summary
    bill.sponsor = record.sponsor
    bill.introduced_date = record.introduced_date
    bill.latest_action = record.latest_action
    bill.status = record.status
    bill.topic = record.topic
    db.flush()
    return bill
