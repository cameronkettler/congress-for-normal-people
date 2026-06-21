import json
import logging
from datetime import datetime, timedelta, timezone
from urllib.parse import urlparse

import httpx
from fastapi import APIRouter, Depends, Header, HTTPException
from fastapi.responses import JSONResponse, StreamingResponse
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
from packages.agents.bill_lookup import BillLookupWorkflow, ProviderLookupError
from packages.agents.bill_lookup.input_resolver import BillInputResolutionError
from packages.agents.bill_lookup.report_generator import OpenAIReportGenerator
from packages.agents.bill_monitoring import BillMonitoringWorkflow
from packages.agents.representative_deep_dive import RepresentativeDeepDiveWorkflow
from packages.db import get_session
from packages.db.models import Bill, BillMonitoring, BillPositionSearchCache, GeneratedReport, ReportCache, RepresentativeDeepDiveCache, RepresentativeSearchCache, User, UserProfile, UserSession, UserTopicPreference
from packages.ingestion.congress import CongressClient
from packages.ingestion.search import SearchResult, SerpApiClient
from packages.jobs.poll_new_bills import poll_new_bills
from packages.shared.config import get_settings
from packages.ingestion.census import CensusGeocoderClient, CensusGeometryClient
from packages.shared.schemas import (
    BillRecord,
    BillLookupRequest,
    BillLookupResponse,
    HotTopicBill,
    HotTopicsResponse,
    MonitoringBill,
    MonitoringRecentResponse,
    RepresentativeBillSignal,
    RepresentativeDeepDive,
    RepresentativeDeepDiveResponse,
    RepresentativeRecord,
    SourceReference,
    UserProfileResponse,
    RepresentativeMapGeometryResponse,
)

router = APIRouter()
logger = logging.getLogger(__name__)


HOT_TOPIC_BILLS = [
    HotTopicBill(
        congress_bill_id="hr-8800-119",
        title="National Defense Authorization Act for Fiscal Year 2027",
        topic="Defense",
        reason="Annual defense-policy vehicle with military, national security, and federal contracting stakes.",
        year=2026,
    ),
    HotTopicBill(
        congress_bill_id="hr-7148-119",
        title="Consolidated Appropriations Act, 2026",
        topic="Tax & Budget",
        reason="Government funding package that affects agency budgets, programs, and national spending priorities.",
        year=2026,
    ),
    HotTopicBill(
        congress_bill_id="hr-22-119",
        title="SAVE Act",
        topic="Elections",
        reason="High-profile election-administration bill centered on documentary proof of citizenship for voter registration.",
        year=2025,
    ),
    HotTopicBill(
        congress_bill_id="hr-1-119",
        title="One Big Beautiful Bill Act",
        topic="Tax & Budget",
        reason="Major reconciliation law tied to taxes, spending, border security, energy, and other national policy fights.",
        year=2025,
    ),
    HotTopicBill(
        congress_bill_id="s-1582-119",
        title="GENIUS Act",
        topic="Financial Regulation",
        reason="Nationally watched digital-asset and stablecoin regulation package.",
        year=2025,
    ),
    HotTopicBill(
        congress_bill_id="hr-4405-119",
        title="Epstein Files Transparency Act",
        topic="Government Operations",
        reason="Transparency bill with unusually broad public attention and accountability implications.",
        year=2025,
    ),
    HotTopicBill(
        congress_bill_id="s-5-119",
        title="Laken Riley Act",
        topic="Immigration",
        reason="Prominent immigration and criminal-enforcement law from the opening weeks of the 119th Congress.",
        year=2025,
    ),
]


class AuthRequest(BaseModel):
    email: str
    password: str
    street_address: str = ""
    address_line_2: str = ""
    city: str = ""
    state: str = ""
    zip_code: str = ""


class AuthResponse(BaseModel):
    token: str
    user: dict[str, str | int]


class InterestUpdate(BaseModel):
    enabled: bool


class ProfileLocationRequest(BaseModel):
    street_address: str = ""
    address_line_2: str = ""
    city: str = ""
    state: str = ""
    zip_code: str


class RepresentativeContextRequest(BaseModel):
    bill: BillRecord
    representative_name: str


@router.post("/auth/register", response_model=AuthResponse)
async def register(payload: AuthRequest, db: Session = Depends(get_session)):
    email = normalize_email(payload.email)
    if len(payload.password) < 8:
        raise HTTPException(status_code=422, detail="Password must be at least 8 characters.")
    if db.query(User).filter(User.email == email).one_or_none() is not None:
        raise HTTPException(status_code=409, detail="An account with that email already exists.")

    resolved_location = None
    if registration_includes_location(payload):
        try:
            resolved_location = await CensusGeocoderClient().resolve_location(
                street_address=payload.street_address,
                address_line_2=payload.address_line_2,
                city=payload.city,
                state=payload.state,
                zip_code=payload.zip_code,
            )
        except (httpx.TimeoutException, httpx.HTTPError, ValueError) as exc:
            raise HTTPException(
                status_code=422,
                detail=(
                    "Could not resolve that address to a congressional district. "
                    "Try using the USPS street abbreviation, e.g. S Pearl Expy."
                ),
            ) from exc

    user = User(email=email, password_hash=hash_password(payload.password))
    db.add(user)
    db.flush()
    ensure_topic_preferences(db, user)
    if resolved_location is not None:
        profile = UserProfile(user_id=user.id)
        apply_profile_location(profile, payload, resolved_location)
        db.add(profile)
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
async def lookup_bill(
    payload: BillLookupRequest,
    db: Session = Depends(get_session),
    authorization: str | None = Header(default=None),
):
    user = optional_user_from_authorization(db, authorization)
    if cached_response := cached_report_response(db, payload.bill_id, user):
        return cached_response

    try:
        response = await BillLookupWorkflow().run(payload.bill_id)
    except BillInputResolutionError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except ProviderLookupError as exc:
        log_lookup_failure(payload.bill_id, exc.provider, exc)
        return lookup_error_response(exc.provider)
    except httpx.TimeoutException as exc:
        log_lookup_failure(payload.bill_id, "External provider", exc)
        return lookup_error_response("External provider")
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code == 404:
            raise HTTPException(
                status_code=404,
                detail="Congress.gov did not find that bill number. Check the bill type, number, and Congress.",
            ) from exc
        log_lookup_failure(payload.bill_id, "External provider", exc)
        return lookup_error_response("External provider")
    except httpx.HTTPError as exc:
        log_lookup_failure(payload.bill_id, "External provider", exc)
        return lookup_error_response("External provider")
    except Exception as exc:
        log_lookup_failure(payload.bill_id, "Application", exc)
        return lookup_error_response("Application")
    try:
        bill = upsert_bill(db, response)
        db.add(
            GeneratedReport(
                bill_id=bill.id,
                generated_summary=response.generated_summary,
                generated_analysis=response.generated_analysis,
            )
        )
        db.commit()
    except Exception as exc:
        db.rollback()
        log_lookup_failure(payload.bill_id, "Application", exc)
        return lookup_error_response("Application")
    if user:
        response.representative_context = await representative_context_for_bill(db, user, response)
    save_report_cache(db, response, user)
    return response


@router.post("/bills/lookup/stream")
async def lookup_bill_stream(
    payload: BillLookupRequest,
    db: Session = Depends(get_session),
    authorization: str | None = Header(default=None),
):
    return StreamingResponse(
        lookup_bill_events(payload=payload, db=db, authorization=authorization),
        media_type="application/x-ndjson",
    )


async def lookup_bill_events(
    *,
    payload: BillLookupRequest,
    db: Session,
    authorization: str | None,
):
    user = optional_user_from_authorization(db, authorization)
    if cached_response := cached_report_response(db, payload.bill_id, user):
        yield stream_event(
            {
                "type": "progress",
                "step": "cache_hit",
                "message": "Loading saved report",
                "detail": "This bill report was generated in the last 24 hours, so expensive research was skipped.",
            }
        )
        yield stream_event({"type": "result", "data": cached_response.model_dump(mode="json")})
        return

    workflow = BillLookupWorkflow()
    try:
        response: BillLookupResponse | None = None
        async for event in workflow.run_with_progress(payload.bill_id):
            if event.get("type") == "result":
                response = event["data"]
                break
            yield stream_event(event)

        if response is None:
            yield stream_event(
                {
                    "type": "error",
                    "status": 502,
                    "detail": "Lookup finished without a generated report.",
                }
            )
            return

        yield stream_event(
            {
                "type": "progress",
                "step": "save_report",
                "message": "Saving generated report",
                "detail": "Caching the report so the dashboard and recent bills can reuse it.",
            }
        )
        bill = upsert_bill(db, response)
        db.add(
            GeneratedReport(
                bill_id=bill.id,
                generated_summary=response.generated_summary,
                generated_analysis=response.generated_analysis,
            )
        )
        db.commit()

        if user:
            yield stream_event(
                {
                    "type": "progress",
                    "step": "representative_context",
                    "message": "Checking your representatives and senators",
                    "detail": "Combining official votes, sponsorship records, public search, and AI-assisted context.",
                }
            )
            response.representative_context = await representative_context_for_bill(db, user, response)

        save_report_cache(db, response, user)
        yield stream_event(
            {
                "type": "result",
                "data": response.model_dump(mode="json"),
            }
        )
    except BillInputResolutionError as exc:
        yield stream_event({"type": "error", "status": 422, "detail": str(exc)})
    except ProviderLookupError as exc:
        log_lookup_failure(payload.bill_id, exc.provider, exc)
        yield stream_lookup_error(exc.provider)
    except httpx.TimeoutException as exc:
        log_lookup_failure(payload.bill_id, "External provider", exc)
        yield stream_lookup_error("External provider")
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code == 404:
            yield stream_event(
                {
                    "type": "error",
                    "status": 404,
                    "detail": "Congress.gov did not find that bill number. Check the bill type, number, and Congress.",
                }
            )
            return
        log_lookup_failure(payload.bill_id, "External provider", exc)
        yield stream_lookup_error("External provider")
    except httpx.HTTPError as exc:
        log_lookup_failure(payload.bill_id, "External provider", exc)
        yield stream_lookup_error("External provider")
    except Exception as exc:
        db.rollback()
        log_lookup_failure(payload.bill_id, "Application", exc)
        yield stream_lookup_error("Application")


def stream_lookup_error(provider: str) -> str:
    return stream_event(
        {
            "type": "error",
            "status": 502,
            "error": "Bill lookup failed",
            "provider": provider,
            "detail": "External data source unavailable or timed out",
        }
    )


def stream_event(event: dict[str, object]) -> str:
    return f"{json.dumps(event, default=str)}\n"


@router.post("/bills/representative-context", response_model=RepresentativeBillSignal)
async def representative_context_lookup(
    payload: RepresentativeContextRequest,
    user: User = Depends(current_user),
    db: Session = Depends(get_session),
):
    representative = await representative_from_user_or_name(db, user, payload.representative_name)
    cosponsors = await safe_bill_cosponsors(payload.bill.congress_bill_id)
    house_votes = await safe_house_votes(payload.bill.congress_bill_id)
    senate_votes = await safe_senate_votes(payload.bill.congress_bill_id)
    return await representative_signal_for_bill(
        bill=payload.bill,
        representative=representative,
        cosponsors=cosponsors,
        house_votes=house_votes,
        senate_votes=senate_votes,
        db=db,
    )


@router.get("/representatives/deep-dive", response_model=RepresentativeDeepDiveResponse)
async def representative_deep_dive(
    user: User = Depends(current_user),
    db: Session = Depends(get_session),
):
    try:
        profile = db.query(UserProfile).filter(UserProfile.user_id == user.id).one_or_none()
        if profile is None:
            return RepresentativeDeepDiveResponse(
                items=[],
                warning="Add an address to see representative deep dives.",
            )

        representatives, warning = await representatives_for_profile(profile)
        topics = sorted(enabled_topics_for_user(db, user))
        if cached_response := cached_representative_deep_dive_response(db, user, topics):
            return cached_response
        workflow = RepresentativeDeepDiveWorkflow()
        items = [
            await workflow.run(representative=representative, watchlist_topics=topics)
            for representative in representatives
        ]
        response = RepresentativeDeepDiveResponse(items=items, warning=warning)
        save_representative_deep_dive_cache(db, user, topics, response)
        return response
    except Exception as exc:
        logger.exception(
            "representative deep dive failed",
            extra={"endpoint": "/api/representatives/deep-dive", "user_id": user.id},
        )
        return RepresentativeDeepDiveResponse(
            items=[],
            warning="Representative deep dives are temporarily unavailable.",
        )


@router.get("/representatives/deep-dive/stream")
async def representative_deep_dive_stream(
    user: User = Depends(current_user),
    db: Session = Depends(get_session),
):
    return StreamingResponse(
        stream_representative_deep_dive(user=user, db=db),
        media_type="application/x-ndjson",
    )


async def stream_representative_deep_dive(user: User, db: Session):
    items = []
    warning = None
    try:
        yield stream_event(
            {
                "type": "progress",
                "step": "load_profile",
                "label": "Loading saved address",
                "detail": "Checking your profile for the address used to find your House representative and senators.",
            }
        )
        profile = db.query(UserProfile).filter(UserProfile.user_id == user.id).one_or_none()
        if profile is None:
            yield stream_event(
                {
                    "type": "result",
                    "data": RepresentativeDeepDiveResponse(
                        items=[],
                        warning="Add an address to see representative deep dives.",
                    ).model_dump(mode="json"),
                }
            )
            return

        yield stream_event(
            {
                "type": "progress",
                "step": "resolve_representatives",
                "label": "Resolving your representatives",
                "detail": "Using your saved district to load your House representative and two senators.",
            }
        )
        representatives, warning = await representatives_for_profile(profile)
        topics = sorted(enabled_topics_for_user(db, user))
        if cached_response := cached_representative_deep_dive_response(db, user, topics):
            yield stream_event(
                {
                    "type": "progress",
                    "step": "cache_hit",
                    "label": "Loaded cached representative deep dive",
                    "detail": "Using a saved deep dive from the last 24 hours.",
                }
            )
            yield stream_event({"type": "result", "data": cached_response.model_dump(mode="json")})
            return
        workflow = RepresentativeDeepDiveWorkflow()
        seen_representatives = set()

        for representative in representatives:
            representative_key = (
                representative.bioguide_id
                or f"{representative.chamber}-{representative.state}-{representative.district}-{representative.name}"
            )
            if representative_key in seen_representatives:
                continue
            seen_representatives.add(representative_key)
            yield stream_event(
                {
                    "type": "progress",
                    "step": "start_representative",
                    "representative": representative.name,
                    "label": f"Starting {representative.name}",
                    "detail": "Building a profile from official records, finance coverage, and public-source research.",
                }
            )
            try:
                async for event in workflow.run_with_progress(
                    representative=representative,
                    watchlist_topics=topics,
                ):
                    if event.get("type") == "item":
                        item = event["data"]
                        items.append(item)
                        yield stream_event(
                            {
                                "type": "item",
                                "data": item.model_dump(mode="json"),
                            }
                        )
                    else:
                        yield stream_event(event)
            except Exception:
                logger.exception(
                    "representative deep dive item failed",
                    extra={
                        "endpoint": "/api/representatives/deep-dive/stream",
                        "user_id": user.id,
                        "representative": representative.name,
                    },
                )
                warning = "Some representative deep dives were unavailable; showing the results that completed."
                fallback_item = RepresentativeDeepDive(
                    representative=representative,
                    summary=(
                        f"A full deep dive for {representative.name} could not be completed. "
                        "Official representative details are still shown, but public-theme and money-context research should be retried."
                    ),
                    money_context="Money-context research did not complete for this representative.",
                    caveats=["This profile is incomplete because one research step failed."],
                )
                items.append(fallback_item)
                yield stream_event(
                    {
                        "type": "item",
                        "data": fallback_item.model_dump(mode="json"),
                    }
                )
                yield stream_event(
                    {
                        "type": "progress",
                        "step": "representative_unavailable",
                        "representative": representative.name,
                        "label": f"Skipped {representative.name}",
                        "detail": "This representative's deep dive could not be completed, so the available results will still be shown.",
                    }
                )

        response = RepresentativeDeepDiveResponse(
            items=items,
            warning=warning,
        )
        save_representative_deep_dive_cache(db, user, topics, response)
        yield stream_event(
            {
                "type": "result",
                "data": response.model_dump(mode="json"),
            }
        )
    except Exception as exc:
        logger.exception(
            "representative deep dive stream failed",
            extra={"endpoint": "/api/representatives/deep-dive/stream", "user_id": user.id},
        )
        yield stream_event(
            {
                "type": "error",
                "status": 502,
                "detail": "Representative deep dives are temporarily unavailable.",
            }
        )


def lookup_error_response(provider: str) -> JSONResponse:
    return JSONResponse(
        status_code=502,
        content={
            "error": "Bill lookup failed",
            "provider": provider,
            "detail": "External data source unavailable or timed out",
        },
    )


def log_lookup_failure(bill_query: str, provider: str, exc: Exception) -> None:
    logger.exception(
        "bill lookup provider failure",
        extra={
            "endpoint": "/api/bills/lookup",
            "bill_query": bill_query,
            "provider": provider,
            "error_type": exc.__class__.__name__,
        },
    )


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


@router.get("/monitoring/hot-topics", response_model=HotTopicsResponse)
def hot_topics(db: Session = Depends(get_session)):
    items = list(HOT_TOPIC_BILLS)
    seen = {item.congress_bill_id for item in items}
    rows = db.query(Bill).order_by(Bill.created_at.desc()).limit(25).all()
    for row in rows:
        if row.congress_bill_id in seen or not is_hot_topic_candidate(row):
            continue
        items.append(
            HotTopicBill(
                congress_bill_id=row.congress_bill_id,
                title=row.title,
                topic=row.topic,
                reason="Recently surfaced in monitoring and tied to a nationally salient policy area.",
                year=(row.introduced_date.year if row.introduced_date else 2026),
            )
        )
        seen.add(row.congress_bill_id)
        if len(items) >= 10:
            break
    return HotTopicsResponse(items=items[:10])


def is_hot_topic_candidate(row: Bill) -> bool:
    return row.topic in {
        "Defense",
        "Elections",
        "Healthcare",
        "Immigration",
        "Tax & Budget",
        "Energy",
        "Technology",
        "Financial Regulation",
        "Government Operations",
    }


async def representative_context_for_bill(
    db: Session,
    user: User,
    response: BillLookupResponse,
) -> list[RepresentativeBillSignal]:
    profile = db.query(UserProfile).filter(UserProfile.user_id == user.id).one_or_none()
    if profile is None:
        return []

    representatives, _ = await representatives_for_profile(profile)
    cosponsors = await safe_bill_cosponsors(response.bill.congress_bill_id)
    house_votes = await safe_house_votes(response.bill.congress_bill_id)
    senate_votes = await safe_senate_votes(response.bill.congress_bill_id)
    sponsor_name = response.bill.sponsor.casefold()

    signals: list[RepresentativeBillSignal] = []
    for representative in representatives:
        signals.append(
            await representative_signal_for_bill(
                bill=response.bill,
                representative=representative,
                cosponsors=cosponsors,
                house_votes=house_votes,
                senate_votes=senate_votes,
                sponsor_name=sponsor_name,
                db=db,
            )
        )
    return signals


async def representative_from_user_or_name(
    db: Session,
    user: User,
    representative_name: str,
) -> RepresentativeRecord:
    requested = representative_name.strip()
    if not requested:
        raise HTTPException(status_code=422, detail="Representative name is required.")

    profile = db.query(UserProfile).filter(UserProfile.user_id == user.id).one_or_none()
    if profile is not None:
        representatives, _ = await representatives_for_profile(profile)
        for representative in representatives:
            if names_refer_to_same_person(representative.name, requested):
                return representative
        for representative in await current_state_members(profile.state):
            if names_refer_to_same_person(representative.name, requested):
                return representative

    state = profile.state if profile is not None else ""
    return RepresentativeRecord(
        name=requested,
        chamber="Unknown",
        party="Unknown",
        state=state,
    )


async def current_state_members(state: str) -> list[RepresentativeRecord]:
    if not state:
        return []
    congress = CongressClient()
    try:
        senators = await congress.list_current_senators(state)
        representatives: list[RepresentativeRecord] = []
        for district in range(1, 54):
            member = await congress.get_current_house_member(state, str(district))
            if member is not None:
                representatives.append(member)
        return [*representatives, *senators]
    except Exception:
        logger.warning(
            "state member lookup failed",
            extra={"state": state},
        )
        return []


def names_refer_to_same_person(left: str, right: str) -> bool:
    normalized_left = normalized_person_name(left)
    normalized_right = normalized_person_name(right)
    if not normalized_left or not normalized_right:
        return False
    left_parts = set(normalized_left.split())
    right_parts = set(normalized_right.split())
    return (
        normalized_left == normalized_right
        or normalized_left in normalized_right
        or normalized_right in normalized_left
        or (left_parts == right_parts and bool(left_parts))
        or (len(left_parts) >= 2 and left_parts.issubset(right_parts))
        or (len(right_parts) >= 2 and right_parts.issubset(left_parts))
    )


# representative_signal_for_bill signature
async def representative_signal_for_bill(
    *,
    bill: BillRecord,
    representative: RepresentativeRecord,
    cosponsors: list[dict[str, object]],
    house_votes: list[dict[str, object]],
    senate_votes: list[dict[str, object]] | None = None,
    sponsor_name: str | None = None,
    db: Session | None = None,
) -> RepresentativeBillSignal:
    rep_name = representative.name.casefold()
    sponsor = sponsor_name if sponsor_name is not None else bill.sponsor.casefold()
    vote_signal = await representative_vote_signal(
        bill.congress_bill_id,
        representative,
        house_votes,
        senate_votes or [],
    )
    if vote_signal:
        signal, detail = vote_signal
    elif rep_name and (rep_name in sponsor or sponsor in rep_name):
        signal = "Sponsor"
        detail = "This member is listed as the bill sponsor, which is a formal support signal."
    elif representative_is_cosponsor(representative, cosponsors):
        signal = "Cosponsor"
        detail = "This member is listed as a cosponsor, which is a formal support signal."
    else:
        signal = "No direct signal found"
        detail = "No sponsor or cosponsor relationship was found in the available Congress.gov data."
    signal, detail, sources, ai_context = await enrich_representative_position_signal(
        bill=bill.model_dump(mode="json"),
        representative=representative,
        signal=signal,
        detail=detail,
        db=db,
    )
    return RepresentativeBillSignal(
        representative=representative,
        signal=signal,
        detail=detail,
        ai_context=ai_context,
        sources=sources,
    )


def representative_is_cosponsor(
    representative: RepresentativeRecord,
    cosponsors: list[dict[str, object]],
) -> bool:
    for cosponsor in cosponsors:
        if cosponsor_matches_representative(cosponsor, representative):
            return True
    return False


def cosponsor_matches_representative(
    cosponsor: dict[str, object],
    representative: RepresentativeRecord,
) -> bool:
    if representative.bioguide_id and representative.bioguide_id == cosponsor_bioguide_id(cosponsor):
        return True

    cosponsor_name = normalized_person_name(cosponsor_display_name(cosponsor))
    representative_name = normalized_person_name(representative.name)
    if not cosponsor_name or not representative_name:
        return False
    return cosponsor_name == representative_name or cosponsor_name in representative_name or representative_name in cosponsor_name


def cosponsor_bioguide_id(cosponsor: dict[str, object]) -> str:
    for key in ("bioguideId", "bioguideID", "bioguide_id", "bioguide"):
        value = cosponsor.get(key)
        if value:
            return str(value)
    return ""


def cosponsor_display_name(cosponsor: dict[str, object]) -> str:
    for key in ("fullName", "name", "directOrderName", "invertedOrderName"):
        value = cosponsor.get(key)
        if value:
            return str(value)
    return " ".join(
        str(cosponsor.get(key) or "")
        for key in ("firstName", "middleName", "lastName")
        if cosponsor.get(key)
    )


def normalized_person_name(name: str) -> str:
    normalized = name.replace(",", " ").replace(".", " ")
    normalized = " ".join(part for part in normalized.casefold().split() if part not in {"rep", "representative"})
    return normalized


async def representative_vote_signal(
    bill_id: str,
    representative: RepresentativeRecord,
    house_votes: list[dict[str, object]],
    senate_votes: list[dict[str, object]] | None = None,
) -> tuple[str, str] | None:
    if representative.chamber == "House":
        votes = house_votes
        chamber = "House"
        member_vote_lookup = safe_house_member_vote
    elif representative.chamber == "Senate":
        votes = senate_votes or []
        chamber = "Senate"
        member_vote_lookup = safe_senate_member_vote
    else:
        return None
    if not votes:
        return None

    for vote in preferred_chamber_votes(votes):
        member_vote = await member_vote_lookup(vote, representative)
        if not member_vote:
            continue
        vote_cast = str(member_vote.get("vote_cast", "")).strip()
        if not vote_cast:
            continue
        signal = vote_signal_label(vote_cast)
        question = member_vote.get("vote_question") or f"the recorded {chamber} vote"
        result = member_vote.get("result") or "recorded"
        roll_call = member_vote.get("roll_call_number")
        detail = (
            f"Your representative voted {vote_cast} on {question}. "
            f"The {chamber} vote result was {result}"
            f"{f' (roll call {roll_call})' if roll_call else ''}."
        )
        return signal, detail
    return None


async def enrich_representative_position_signal(
    *,
    bill: dict[str, object],
    representative: RepresentativeRecord,
    signal: str,
    detail: str,
    db: Session | None = None,
) -> tuple[str, str, list[SourceReference], str | None]:
    search_results = await search_representative_position(
        bill,
        representative,
        db,
    )
    if reported_cosponsor := public_reported_cosponsor_signal(signal, search_results, representative):
        reported_signal, reported_detail, reported_sources = reported_cosponsor
        return reported_signal, reported_detail, reported_sources, None

    generator = OpenAIReportGenerator()
    serpapi_payloads = [search_result_payload(item) for item in search_results]
    web_reason = None
    if web_context_generator := getattr(generator, "generate_representative_web_context", None):
        web_reason = await web_context_generator(
            bill=bill,
            representative=representative.model_dump(mode="json"),
            signal=signal,
            search_results=serpapi_payloads,
        )

    reason = await generator.generate_representative_position_reason(
        bill=bill,
        representative=representative.model_dump(mode="json"),
        signal=signal,
        search_results=representative_context_payloads(serpapi_payloads, web_reason),
    )
    if not reason and web_reason:
        reason = web_reason

    if not reason or not reason.get("reason"):
        if not search_results:
            return signal, detail, [], None
        if signal != "No direct signal found":
            return signal, detail, fallback_position_sources(search_results, representative), None
        return (
            public_search_reviewed_signal(signal),
            public_search_reviewed_detail(detail),
            fallback_position_sources(search_results, representative),
            None,
        )

    position = str(reason.get("position", ""))
    enriched_signal = public_position_signal(signal, position)
    if position == "unclear":
        enriched_signal = public_search_reviewed_signal(signal)

    sources = merge_source_references(
        formatted_position_sources(reason, search_results, representative),
        web_context_sources(web_reason),
    )
    return enriched_signal, representative_context_detail(detail), sources, str(reason["reason"])


def representative_context_detail(base_detail: str) -> str:
    if base_detail.startswith("No sponsor or cosponsor relationship"):
        return "No formal sponsor, cosponsor, or recorded-vote signal was found in the available Congress.gov data."
    return base_detail


def formatted_position_sources(
    reason: dict[str, object],
    search_results: list[SearchResult],
    representative: RepresentativeRecord,
) -> list[SourceReference]:
    allowed = relevant_position_sources(search_results, representative)
    allowed_by_url = {item.link: item for item in allowed}
    sources: list[SourceReference] = []
    for source in reason.get("sources", []):
        if not isinstance(source, dict):
            continue
        url = str(source.get("url") or "")
        item = allowed_by_url.get(url)
        if not item:
            continue
        sources.append(source_reference(item, representative, confidence="medium"))
        if len(sources) == 2:
            break

    if not sources and allowed:
        sources.append(source_reference(allowed[0], representative, confidence="low"))
    if not sources and len(search_results) == 1 and source_quality_score(search_results[0]) >= 0:
        sources.append(source_reference(search_results[0], representative, confidence="low"))
    return sources


def representative_context_payloads(
    serpapi_payloads: list[dict[str, str]],
    web_reason: dict[str, object] | None,
) -> list[dict[str, str]]:
    payloads = list(serpapi_payloads)
    if not web_reason or not web_reason.get("reason"):
        return payloads

    payloads.append(
        {
            "title": "OpenAI web search synthesis",
            "url": "",
            "snippet": str(web_reason["reason"]),
            "source": "OpenAI web search",
        }
    )
    for source in web_reason.get("sources", []):
        if not isinstance(source, dict):
            continue
        title = str(source.get("title") or "").strip()
        url = str(source.get("url") or "").strip()
        if not title or not url:
            continue
        payloads.append(
            {
                "title": title,
                "url": url,
                "snippet": "Source found by OpenAI web search for representative-position context.",
                "source": "OpenAI web search",
            }
        )
    return payloads


def web_context_sources(web_reason: dict[str, object] | None) -> list[SourceReference]:
    if not web_reason:
        return []
    confidence = str(web_reason.get("confidence") or "low")
    sources: list[SourceReference] = []
    for source in web_reason.get("sources", []):
        if not isinstance(source, dict):
            continue
        title = str(source.get("title") or "").strip()
        url = str(source.get("url") or "").strip()
        if not title or not url:
            continue
        sources.append(
            SourceReference(
                label=compact_source_title(title),
                url=url,
                confidence=confidence,
                description="Public source found by the AI web-search pass for representative context.",
            )
        )
        if len(sources) == 2:
            break
    return sources


def merge_source_references(
    primary: list[SourceReference],
    secondary: list[SourceReference],
) -> list[SourceReference]:
    merged: list[SourceReference] = []
    seen_urls: set[str] = set()
    for source in [*primary, *secondary]:
        if source.url in seen_urls:
            continue
        seen_urls.add(source.url)
        merged.append(source)
        if len(merged) == 3:
            break
    return merged


def fallback_position_sources(
    search_results: list[SearchResult],
    representative: RepresentativeRecord,
) -> list[SourceReference]:
    candidates = relevant_position_sources(search_results, representative) or [
        item for item in search_results if source_quality_score(item) >= 0
    ]
    return [
        source_reference(item, representative, confidence="low")
        for item in candidates[:2]
    ]


def relevant_position_sources(
    search_results: list[SearchResult],
    representative: RepresentativeRecord,
) -> list[SearchResult]:
    rep_terms = representative_name_terms(representative.name)
    return [
        item
        for item in search_results
        if result_mentions_representative(item, rep_terms) and source_quality_score(item) >= 0
    ]


def representative_name_terms(name: str) -> set[str]:
    normalized = name.replace(",", " ")
    parts = [part.casefold() for part in normalized.split() if len(part) > 2]
    return set(parts)


def result_mentions_representative(item: SearchResult, rep_terms: set[str]) -> bool:
    text = f"{item.title} {item.snippet} {item.source} {item.link}".casefold()
    return any(term in text for term in rep_terms)


def source_reference(
    item: SearchResult,
    representative: RepresentativeRecord,
    *,
    confidence: str,
) -> SourceReference:
    return SourceReference(
        label=source_label(item),
        url=source_url(item, representative),
        confidence=confidence,
        description=source_description(item),
    )


def source_label(item: SearchResult) -> str:
    text = position_search_text(item)
    source = item.source or item.link
    if "lcv.org" in text:
        return "LCV vote summary"
    if "congress.gov" in text:
        return "Congress.gov bill page"
    if "tiktok.com" in text:
        return "Public video clip"
    if "facebook.com" in text:
        return "Public Facebook post"
    if "instagram.com" in text:
        return "Public Instagram post"
    if "house.gov" in text or ".gov" in text:
        return "Official public source"
    if "roll-call" in text or "scorecard" in text:
        return "Vote summary"
    return compact_source_title(item.title or source)


def source_url(item: SearchResult, representative: RepresentativeRecord) -> str:
    text = position_search_text(item)
    if "lcv.org/roll-call-vote" in text:
        return f"https://www.lcv.org/moc/{representative_slug(representative.name)}/"
    return item.link


def source_description(item: SearchResult) -> str:
    text = position_search_text(item)
    if "lcv.org" in text:
        return "Advocacy-group vote summary or member scorecard context for this vote."
    if "congress.gov" in text:
        return "Official bill page with text, actions, sponsors, and legislative status."
    if "tiktok.com" in text or "instagram.com" in text or "facebook.com" in text:
        return "Public social-media source surfaced by search; useful as context, not an official record."
    if ".gov" in text:
        return "Official public source from a government domain."
    return "Public search result used as context for the representative's position."


def representative_slug(name: str) -> str:
    if "," in name:
        last, first = [part.strip() for part in name.split(",", 1)]
        name = f"{first} {last}"
    parts = [part.strip().casefold() for part in name.split() if part.strip()]
    return "-".join(parts)


def compact_source_title(title: str) -> str:
    cleaned = " ".join(title.split())
    if len(cleaned) <= 90:
        return cleaned
    return f"{cleaned[:87].rstrip()}..."


def public_search_reviewed_signal(existing_signal: str) -> str:
    if existing_signal == "No direct signal found":
        return "Public search reviewed"
    return existing_signal


def public_search_reviewed_detail(detail: str) -> str:
    return (
        f"{detail} Public search surfaced related sources for this bill and representative; "
        "review the source links below for public context."
    )


def public_position_signal(existing_signal: str, position: str) -> str:
    if existing_signal != "No direct signal found":
        return existing_signal
    if position == "supports":
        return "Publicly supported"
    if position == "criticizes":
        return "Publicly criticized"
    return existing_signal


async def search_representative_position(
    bill: dict[str, object],
    representative: RepresentativeRecord,
    session: Session | None = None,
) -> list[SearchResult]:
    bill_id = str(bill.get("congress_bill_id") or "")
    title = str(bill.get("title") or "")
    rep_name = representative.name
    queries = representative_position_queries(
        rep_name=rep_name,
        bill_id=bill_id,
        title=title,
        official_url=representative.official_url,
    )
    query_fingerprint = "\n".join(queries)

    if session is not None:
        cached = (
            session.query(RepresentativeSearchCache)
            .filter(
                RepresentativeSearchCache.bill_id == bill_id,
                RepresentativeSearchCache.representative_name == rep_name,
                RepresentativeSearchCache.query == query_fingerprint,
            )
            .first()
        )

        if cached:
            logger.info(
                "representative position cache hit",
                extra={"representative": rep_name, "bill_id": bill_id},
            )
            return [SearchResult(**result) for result in cached.results_json]

    client = SerpApiClient()
    results: list[SearchResult] = []
    seen_links: set[str] = set()

    for query in queries:
        query_results = await client.search(
            query,
            num=max(get_settings().rep_position_search_results, 5),
        )

        logger.info(
            "representative position search completed",
            extra={
                "provider": "SerpAPI",
                "representative": rep_name,
                "bill_id": bill_id,
                "query": query,
                "query_results": len(query_results),
            },
        )

        for item in query_results:
            if item.link in seen_links:
                continue
            seen_links.add(item.link)
            results.append(item)

    ranked_results = ranked_position_search_results(results)[
        : get_settings().rep_position_search_results
    ]

    if session is not None:
        session.add(
            RepresentativeSearchCache(
                representative_name=rep_name,
                bill_id=bill_id,
                query=query_fingerprint,
                results_json=[search_result_to_json(result) for result in ranked_results],
            )
        )
        session.commit()

    return ranked_results

def representative_position_query(
    *,
    rep_name: str,
    bill_id: str,
    title: str,
    official_url: str | None = None,
) -> str:
    return representative_position_queries(
        rep_name=rep_name,
        bill_id=bill_id,
        title=title,
        official_url=official_url,
    )[0]


def representative_position_queries(
    *,
    rep_name: str,
    bill_id: str,
    title: str,
    official_url: str | None = None,
) -> list[str]:
    bill_number = bill_id.rsplit("-", 1)[0] if bill_id else ""
    official_domain = official_site_domain(official_url)

    bill_terms = " ".join(
        part
        for part in (
            f'"{title}"' if title else "",
            f'"{bill_id}"' if bill_id else "",
            f'"{bill_number}"' if bill_number and bill_number != bill_id else "",
        )
        if part
    )

    official_sites = "site:house.gov OR site:senate.gov OR site:congress.gov"
    if official_domain:
        official_sites = f"site:{official_domain} OR {official_sites}"

    official_query = (
        f'"{rep_name}" ({bill_terms}) '
        f"({official_sites}) "
        "(statement OR press release OR voted OR vote OR support OR oppose OR cosponsor)"
    )

    return [
        query
        for query in (official_query,)
        if '""' not in query
    ]


def official_site_domain(official_url: str | None) -> str:
    if not official_url:
        return ""
    parsed = urlparse(official_url)
    domain = parsed.netloc or parsed.path.split("/", 1)[0]
    if not domain:
        return ""
    return domain.removeprefix("www.")


def public_reported_cosponsor_signal(
    existing_signal: str,
    search_results: list[SearchResult],
    representative: RepresentativeRecord,
) -> tuple[str, str, list[SourceReference]] | None:
    if existing_signal != "No direct signal found":
        return None

    sources = [
        source_reference(item, representative, confidence="low")
        for item in relevant_position_sources(search_results, representative)
        if result_mentions_cosponsorship(item)
    ][:2]
    if not sources:
        return None

    return (
        "Reported cosponsor",
        (
            "Public search results identify your representative as a cosponsor. "
            "This should be treated as a support signal, but verify against the official bill cosponsor list."
        ),
        sources,
    )


def result_mentions_cosponsorship(item: SearchResult) -> bool:
    text = position_search_text(item)
    return any(term in text for term in ("cosponsor", "cosponsored", "co-sponsor", "co-sponsored"))


def ranked_position_search_results(results: list[SearchResult]) -> list[SearchResult]:
    def score(item: SearchResult) -> int:
        text = position_search_text(item)
        value = source_quality_score(item)
        for term in (
            "voter suppression",
            "disenfranchise",
            "voting rights",
            "proof of citizenship",
            "documentary proof",
            "eligible voters",
            "oppose",
            "opposed",
            "criticized",
            "support",
            "supported",
        ):
            if term in text:
                value += 3
        return value

    return sorted(results, key=score, reverse=True)


def source_quality_score(item: SearchResult) -> int:
    text = position_search_text(item)
    value = 0
    for low_value_domain in ("congress.gov", "instagram.com", "tiktok.com", "facebook.com"):
        if low_value_domain in text:
            value -= 4
    if "facebook.com/rep" in text or "instagram.com/rep" in text:
        value += 2
    return value


def position_search_text(item: SearchResult) -> str:
    return f"{item.title} {item.snippet} {item.source} {item.link}".casefold()


def search_result_payload(item: SearchResult) -> dict[str, str]:
    return {
        "title": item.title,
        "url": item.link,
        "snippet": item.snippet,
        "source": item.source,
    }

def search_result_to_json(result: SearchResult) -> dict[str, str]:
    return {
        "title": result.title,
        "link": result.link,
        "snippet": result.snippet,
        "source": result.source,
    }


def preferred_chamber_votes(votes: list[dict[str, object]]) -> list[dict[str, object]]:
    def score(vote: dict[str, object]) -> tuple[int, str]:
        question = str(vote.get("voteQuestion", "")).casefold()
        is_final = any(term in question for term in ("pass", "agree", "concur", "suspend"))
        return (1 if is_final else 0, str(vote.get("startDate", "")))

    return sorted(votes, key=score, reverse=True)


def vote_signal_label(vote_cast: str) -> str:
    normalized = vote_cast.strip().casefold()
    if normalized in {"aye", "yea", "yes"}:
        return "Voted for"
    if normalized in {"nay", "no"}:
        return "Voted against"
    if normalized == "present":
        return "Voted present"
    if normalized == "not voting":
        return "Did not vote"
    return f"Voted {vote_cast}"


async def safe_bill_cosponsors(bill_id: str) -> list[dict[str, object]]:
    try:
        return await CongressClient().list_bill_cosponsors(bill_id)
    except (httpx.TimeoutException, httpx.HTTPError, Exception):
        return []


async def safe_house_votes(bill_id: str) -> list[dict[str, object]]:
    try:
        return await CongressClient().list_house_votes_for_bill(bill_id)
    except (httpx.TimeoutException, httpx.HTTPError, Exception):
        return []


async def safe_senate_votes(bill_id: str) -> list[dict[str, object]]:
    try:
        return await CongressClient().list_senate_votes_for_bill(bill_id)
    except (httpx.TimeoutException, httpx.HTTPError, Exception):
        return []


async def safe_house_member_vote(
    vote: dict[str, object],
    representative: RepresentativeRecord,
) -> dict[str, object] | None:
    try:
        return await CongressClient().get_house_member_vote(vote, representative)
    except (httpx.TimeoutException, httpx.HTTPError, Exception):
        return None


async def safe_senate_member_vote(
    vote: dict[str, object],
    representative: RepresentativeRecord,
) -> dict[str, object] | None:
    try:
        return await CongressClient().get_senate_member_vote(vote, representative)
    except (httpx.TimeoutException, httpx.HTTPError, Exception):
        return None


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


@router.get("/profile", response_model=UserProfileResponse)
async def get_profile(user: User = Depends(current_user), db: Session = Depends(get_session)):
    profile = db.query(UserProfile).filter(UserProfile.user_id == user.id).one_or_none()
    if profile is None:
        return UserProfileResponse(warning="Add an address to see your representatives.")
    return await profile_response(profile)


@router.put("/profile/location", response_model=UserProfileResponse)
async def update_profile_location(
    payload: ProfileLocationRequest,
    user: User = Depends(current_user),
    db: Session = Depends(get_session),
):
    try:
        resolved = await CensusGeocoderClient().resolve_location(
            street_address=payload.street_address,
            address_line_2=payload.address_line_2,
            city=payload.city,
            state=payload.state,
            zip_code=payload.zip_code,
        )
    except (httpx.TimeoutException, httpx.HTTPError, ValueError) as exc:
        logger.warning(
            "profile location resolution failed",
            extra={
                "endpoint": "/api/profile/location",
                "user_id": user.id,
                "city": payload.city,
                "state": payload.state,
                "zip_code": payload.zip_code,
                "error_type": exc.__class__.__name__,
            },
        )
        raise HTTPException(
            status_code=422,
            detail=(
                "Could not resolve that address to a congressional district. "
                "Try using the USPS street abbreviation, e.g. S Pearl Expy."
            ),
        ) from exc

    profile = db.query(UserProfile).filter(UserProfile.user_id == user.id).one_or_none()
    if profile is None:
        profile = UserProfile(user_id=user.id)
        db.add(profile)

    apply_profile_location(profile, payload, resolved)
    db.commit()
    db.refresh(profile)
    return await profile_response(profile)


def registration_includes_location(payload: AuthRequest) -> bool:
    return any(
        value.strip()
        for value in (
            payload.street_address,
            payload.city,
            payload.state,
            payload.zip_code,
        )
    )


def apply_profile_location(profile: UserProfile, payload: AuthRequest | ProfileLocationRequest, resolved: object) -> None:
    profile.street_address = payload.street_address.strip()
    profile.address_line_2 = payload.address_line_2.strip()
    profile.city = payload.city.strip()
    profile.state = str(getattr(resolved, "state"))
    profile.zip_code = payload.zip_code.strip()
    profile.congressional_district = str(getattr(resolved, "congressional_district"))
    profile.location_confidence = str(getattr(resolved, "confidence"))


async def profile_response(profile: UserProfile) -> UserProfileResponse:
    representatives, warning = await representatives_for_profile(profile)
    return UserProfileResponse(
        street_address=profile.street_address,
        address_line_2=profile.address_line_2,
        city=profile.city,
        state=profile.state,
        zip_code=profile.zip_code,
        congressional_district=profile.congressional_district,
        location_confidence=profile.location_confidence,
        representatives=representatives,
        warning=warning,
    )


async def representatives_for_profile(profile: UserProfile) -> tuple[list[RepresentativeRecord], str | None]:
    congress = CongressClient()
    representatives: list[RepresentativeRecord] = []
    try:
        house = await congress.get_current_house_member(profile.state, profile.congressional_district)
        if house:
            representatives.append(house)
        representatives.extend(await congress.list_current_senators(profile.state))
    except (httpx.TimeoutException, httpx.HTTPError, Exception):
        return representatives, "Representative lookup is temporarily unavailable."
    return representatives, None

@router.get("/profile/map-geometry", response_model=RepresentativeMapGeometryResponse)
async def get_profile_map_geometry(
    user: User = Depends(current_user),
    db: Session = Depends(get_session),
):
    profile = db.query(UserProfile).filter(UserProfile.user_id == user.id).one_or_none()

    if profile is None:
        return RepresentativeMapGeometryResponse(
            warning="Add an address to see your congressional district map."
        )

    if not profile.state or not profile.congressional_district:
        return RepresentativeMapGeometryResponse(
            state=profile.state or "",
            congressional_district=profile.congressional_district or "",
            warning="Save a resolved address to see your congressional district map.",
        )

    client = CensusGeometryClient()
    warnings: list[str] = []

    try:
        house_geometry = await client.congressional_district_geometry(
            state=profile.state,
            district=profile.congressional_district,
        )
    except (httpx.TimeoutException, httpx.HTTPError, ValueError) as exc:
        logger.warning(
            "congressional district geometry lookup failed",
            extra={
                "endpoint": "/api/profile/map-geometry",
                "user_id": user.id,
                "state": profile.state,
                "district": profile.congressional_district,
                "error_type": exc.__class__.__name__,
            },
        )
        house_geometry = {"type": "FeatureCollection", "features": []}
        warnings.append("Could not load congressional district boundary.")

    try:
        state_geometry = await client.state_geometry(state=profile.state)
    except (httpx.TimeoutException, httpx.HTTPError, ValueError) as exc:
        logger.warning(
            "state geometry lookup failed",
            extra={
                "endpoint": "/api/profile/map-geometry",
                "user_id": user.id,
                "state": profile.state,
                "error_type": exc.__class__.__name__,
            },
        )
        state_geometry = {"type": "FeatureCollection", "features": []}
        warnings.append("Could not load state boundary.")

    return RepresentativeMapGeometryResponse(
        state=profile.state,
        congressional_district=profile.congressional_district,
        house_geometry=house_geometry,
        state_geometry=state_geometry,
        warning=" ".join(warnings) if warnings else None,
    )

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


def optional_user_from_authorization(db: Session, authorization: str | None) -> User | None:
    if not isinstance(authorization, str) or not authorization.startswith("Bearer "):
        return None
    token = authorization.removeprefix("Bearer ").strip()
    session = db.query(UserSession).filter(UserSession.token == token).one_or_none()
    return session.user if session else None


def enabled_topics_for_user(db: Session, user: User) -> set[str]:
    ensure_topic_preferences(db, user)
    return {
        row.topic
        for row in db.query(UserTopicPreference)
        .filter(UserTopicPreference.user_id == user.id, UserTopicPreference.enabled.is_(True))
        .all()
    }


REPORT_CACHE_TTL = timedelta(days=1)
REPRESENTATIVE_DEEP_DIVE_CACHE_TTL = timedelta(days=1)


def cached_report_response(
    db: Session,
    bill_query: str,
    user: User | None,
) -> BillLookupResponse | None:
    profile_key = report_profile_key(db, user)
    candidate_ids = report_cache_bill_ids(bill_query)
    if not candidate_ids:
        return None

    try:
        record = (
            db.query(ReportCache)
            .filter(
                ReportCache.congress_bill_id.in_(candidate_ids),
                ReportCache.profile_key == profile_key,
            )
            .order_by(ReportCache.created_at.desc())
            .first()
        )
    except Exception:
        logger.debug(
            "report cache lookup skipped",
            extra={"bill_query": bill_query, "profile_key": profile_key},
        )
        return None
    if record is None or not report_cache_is_fresh(record.created_at):
        return None

    try:
        return BillLookupResponse.model_validate(record.response_json)
    except Exception:
        logger.warning(
            "cached report could not be parsed",
            extra={
                "bill_query": bill_query,
                "profile_key": profile_key,
                "cache_id": getattr(record, "id", None),
            },
        )
        return None


def save_report_cache(db: Session, response: BillLookupResponse, user: User | None) -> None:
    profile_key = report_profile_key(db, user)
    congress_bill_id = response.bill.congress_bill_id
    response_json = response.model_dump(mode="json")
    record = (
        db.query(ReportCache)
        .filter(
            ReportCache.congress_bill_id == congress_bill_id,
            ReportCache.profile_key == profile_key,
        )
        .one_or_none()
    )
    if record is None:
        db.add(
            ReportCache(
                congress_bill_id=congress_bill_id,
                profile_key=profile_key,
                response_json=response_json,
                created_at=datetime.now(timezone.utc),
            )
        )
    else:
        record.response_json = response_json
        record.created_at = datetime.now(timezone.utc)
    db.commit()


def report_profile_key(db: Session, user: User | None) -> str:
    if user is None:
        return "anonymous"
    profile = db.query(UserProfile).filter(UserProfile.user_id == user.id).one_or_none()
    if profile is None or not profile.state or not profile.congressional_district:
        return f"user:{user.id}:no-location"
    return f"{profile.state.upper()}-{profile.congressional_district}"


def report_cache_bill_ids(bill_query: str) -> list[str]:
    normalized = bill_query.strip().casefold().replace("_", "-")
    if not normalized:
        return []
    values = [normalized]
    pieces = normalized.split("-")
    if len(pieces) >= 3 and pieces[-1].isdigit():
        values.append("-".join(pieces[:-1]))
    elif len(pieces) == 2 and pieces[-1].isdigit():
        values.append(f"{normalized}-119")
    return list(dict.fromkeys(values))


def report_cache_is_fresh(created_at: datetime | None) -> bool:
    if created_at is None:
        return False
    if created_at.tzinfo is None:
        created_at = created_at.replace(tzinfo=timezone.utc)
    return datetime.now(timezone.utc) - created_at <= REPORT_CACHE_TTL


def cached_representative_deep_dive_response(
    db: Session,
    user: User,
    topics: list[str],
) -> RepresentativeDeepDiveResponse | None:
    profile_key = report_profile_key(db, user)
    topics_key = representative_deep_dive_topics_key(topics)
    try:
        record = (
            db.query(RepresentativeDeepDiveCache)
            .filter(
                RepresentativeDeepDiveCache.profile_key == profile_key,
                RepresentativeDeepDiveCache.topics_key == topics_key,
            )
            .order_by(RepresentativeDeepDiveCache.created_at.desc())
            .first()
        )
    except Exception:
        logger.debug(
            "representative deep dive cache lookup skipped",
            extra={"profile_key": profile_key, "topics_key": topics_key},
        )
        return None
    if record is None or not representative_deep_dive_cache_is_fresh(record.created_at):
        return None
    try:
        return RepresentativeDeepDiveResponse.model_validate(record.response_json)
    except Exception:
        logger.warning(
            "cached representative deep dive could not be parsed",
            extra={"profile_key": profile_key, "cache_id": getattr(record, "id", None)},
        )
        return None


def save_representative_deep_dive_cache(
    db: Session,
    user: User,
    topics: list[str],
    response: RepresentativeDeepDiveResponse,
) -> None:
    if not representative_deep_dive_response_is_cacheable(response):
        return
    profile_key = report_profile_key(db, user)
    topics_key = representative_deep_dive_topics_key(topics)
    response_json = response.model_dump(mode="json")
    record = (
        db.query(RepresentativeDeepDiveCache)
        .filter(
            RepresentativeDeepDiveCache.profile_key == profile_key,
            RepresentativeDeepDiveCache.topics_key == topics_key,
        )
        .one_or_none()
    )
    if record is None:
        db.add(
            RepresentativeDeepDiveCache(
                profile_key=profile_key,
                topics_key=topics_key,
                response_json=response_json,
                created_at=datetime.now(timezone.utc),
            )
        )
    else:
        record.response_json = response_json
        record.created_at = datetime.now(timezone.utc)
    db.commit()


def representative_deep_dive_topics_key(topics: list[str]) -> str:
    return json.dumps(sorted({topic.strip().casefold() for topic in topics if topic.strip()}))


def representative_deep_dive_cache_is_fresh(created_at: datetime | None) -> bool:
    if created_at is None:
        return False
    if created_at.tzinfo is None:
        created_at = created_at.replace(tzinfo=timezone.utc)
    return datetime.now(timezone.utc) - created_at <= REPRESENTATIVE_DEEP_DIVE_CACHE_TTL


def representative_deep_dive_response_is_cacheable(response: RepresentativeDeepDiveResponse) -> bool:
    if response.warning or not response.items:
        return False
    for item in response.items:
        if item.caveats and any("research step failed" in caveat.casefold() for caveat in item.caveats):
            return False
        if len(item.sources) <= 1 and not item.money_context:
            return False
    return True


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
