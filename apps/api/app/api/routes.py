import logging

import httpx
from fastapi import APIRouter, Depends, Header, HTTPException
from fastapi.responses import JSONResponse
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
from packages.db import get_session
from packages.db.models import Bill, BillMonitoring, GeneratedReport, User, UserProfile, UserSession, UserTopicPreference
from packages.ingestion.census import CensusGeocoderClient
from packages.ingestion.congress import CongressClient
from packages.ingestion.search import SearchResult, SerpApiClient
from packages.jobs.poll_new_bills import poll_new_bills
from packages.shared.config import get_settings
from packages.shared.schemas import (
    BillLookupRequest,
    BillLookupResponse,
    MonitoringBill,
    MonitoringRecentResponse,
    RepresentativeBillSignal,
    RepresentativeRecord,
    SourceReference,
    UserProfileResponse,
)

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


class ProfileLocationRequest(BaseModel):
    street_address: str = ""
    address_line_2: str = ""
    city: str = ""
    state: str = ""
    zip_code: str


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
async def lookup_bill(
    payload: BillLookupRequest,
    db: Session = Depends(get_session),
    authorization: str | None = Header(default=None),
):
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
    if user := optional_user_from_authorization(db, authorization):
        response.representative_context = await representative_context_for_bill(db, user, response)
    return response


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
    cosponsor_ids = {
        item.get("bioguideId")
        for item in cosponsors
        if isinstance(item, dict) and item.get("bioguideId")
    }
    sponsor_name = response.bill.sponsor.casefold()

    signals: list[RepresentativeBillSignal] = []
    for representative in representatives:
        rep_name = representative.name.casefold()
        vote_signal = await representative_vote_signal(response.bill.congress_bill_id, representative, house_votes)
        if vote_signal:
            signal, detail = vote_signal
        elif rep_name and (rep_name in sponsor_name or sponsor_name in rep_name):
            signal = "Sponsor"
            detail = "Your representative is listed as the bill sponsor, which is a formal support signal."
        elif representative.bioguide_id and representative.bioguide_id in cosponsor_ids:
            signal = "Cosponsor"
            detail = "Your representative is listed as a cosponsor, which is a formal support signal."
        else:
            signal = "No direct signal found"
            detail = "No sponsor or cosponsor relationship was found in the available Congress.gov data."
        signal, detail, sources = await enrich_representative_position_signal(
            bill=response.bill.model_dump(mode="json"),
            representative=representative,
            signal=signal,
            detail=detail,
        )
        signals.append(
            RepresentativeBillSignal(
                representative=representative,
                signal=signal,
                detail=detail,
                sources=sources,
            )
        )
    return signals


async def representative_vote_signal(
    bill_id: str,
    representative: RepresentativeRecord,
    house_votes: list[dict[str, object]],
) -> tuple[str, str] | None:
    if representative.chamber != "House" or not house_votes:
        return None

    for vote in preferred_house_votes(house_votes):
        member_vote = await safe_house_member_vote(vote, representative)
        if not member_vote:
            continue
        vote_cast = str(member_vote.get("vote_cast", "")).strip()
        if not vote_cast:
            continue
        signal = vote_signal_label(vote_cast)
        question = member_vote.get("vote_question") or "the recorded House vote"
        result = member_vote.get("result") or "recorded"
        roll_call = member_vote.get("roll_call_number")
        detail = (
            f"Your representative voted {vote_cast} on {question}. "
            f"The House vote result was {result}"
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
) -> tuple[str, str, list[SourceReference]]:
    search_results = await search_representative_position(bill, representative)
    if not search_results:
        return signal, detail, []

    reason = await OpenAIReportGenerator().generate_representative_position_reason(
        bill=bill,
        representative=representative.model_dump(mode="json"),
        signal=signal,
        search_results=[search_result_payload(item) for item in search_results],
    )
    if not reason or not reason.get("reason"):
        return (
            public_search_reviewed_signal(signal),
            public_search_reviewed_detail(detail, search_results),
            fallback_position_sources(search_results),
        )

    enriched_signal = public_position_signal(signal, str(reason.get("position", "")))

    sources = formatted_position_sources(reason, search_results, representative)
    return enriched_signal, representative_context_detail(detail, str(reason["reason"])), sources


def representative_context_detail(base_detail: str, reason: str) -> str:
    if base_detail.startswith("No sponsor or cosponsor relationship"):
        return f"Public-position context: {reason}"
    return f"{base_detail} Public-position context: {reason}"


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
        sources.append(SourceReference(label=source_label(item), url=item.link, confidence="medium"))
        if len(sources) == 2:
            break

    if not sources and allowed:
        sources.append(SourceReference(label=source_label(allowed[0]), url=allowed[0].link, confidence="low"))
    if not sources and len(search_results) == 1 and source_quality_score(search_results[0]) >= 0:
        sources.append(
            SourceReference(label=source_label(search_results[0]), url=search_results[0].link, confidence="low")
        )
    return sources


def fallback_position_sources(search_results: list[SearchResult]) -> list[SourceReference]:
    return [
        SourceReference(label=source_label(item), url=item.link, confidence="low")
        for item in search_results[:2]
        if source_quality_score(item) >= 0
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


def source_label(item: SearchResult) -> str:
    text = position_search_text(item)
    source = item.source or item.link
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


def compact_source_title(title: str) -> str:
    cleaned = " ".join(title.split())
    if len(cleaned) <= 90:
        return cleaned
    return f"{cleaned[:87].rstrip()}..."


def public_search_reviewed_signal(existing_signal: str) -> str:
    if existing_signal == "No direct signal found":
        return "Public search reviewed"
    return existing_signal


def public_search_reviewed_detail(detail: str, search_results: list[SearchResult]) -> str:
    top_results = search_results[:2]
    if not top_results:
        return detail
    result_text = "; ".join(f"{item.title} ({item.link})" for item in top_results)
    return (
        f"{detail} Public search surfaced related results, but the reviewed snippets did not "
        f"clearly establish support or criticism. Top result{'s' if len(top_results) > 1 else ''}: {result_text}"
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
) -> list[SearchResult]:
    bill_id = str(bill.get("congress_bill_id") or "")
    title = str(bill.get("title") or "")
    rep_name = representative.name
    bill_number = bill_id.rsplit("-", 1)[0] if bill_id else ""
    queries = [
        f'"{rep_name}" "{bill_id}"',
        f'"{rep_name}" "{bill_number}"',
        f'"{rep_name}" "{title}"',
        f'"{rep_name}" "{title}" "voter suppression"',
        f'"{rep_name}" "{title}" disenfranchise',
        f'"{rep_name}" "{title}" "proof of citizenship"',
        f'"{rep_name}" "{title}" support oppose',
    ]

    client = SerpApiClient()
    results: list[SearchResult] = []
    seen_links: set[str] = set()
    for query in queries:
        query_results = await client.search(query, num=3)
        logger.info(
            "representative position search completed",
            extra={
                "provider": "SerpAPI",
                "representative": rep_name,
                "bill_id": bill_id,
                "query_results": len(query_results),
            },
        )
        for item in query_results:
            if item.link in seen_links:
                continue
            seen_links.add(item.link)
            results.append(item)
    return ranked_position_search_results(results)[: get_settings().rep_position_search_results]


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


def preferred_house_votes(votes: list[dict[str, object]]) -> list[dict[str, object]]:
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


async def safe_house_member_vote(
    vote: dict[str, object],
    representative: RepresentativeRecord,
) -> dict[str, object] | None:
    try:
        return await CongressClient().get_house_member_vote(vote, representative)
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

    profile.street_address = payload.street_address.strip()
    profile.address_line_2 = payload.address_line_2.strip()
    profile.city = payload.city.strip()
    profile.state = resolved.state
    profile.zip_code = payload.zip_code.strip()
    profile.congressional_district = resolved.congressional_district
    profile.location_confidence = resolved.confidence
    db.commit()
    db.refresh(profile)
    return await profile_response(profile)


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
    if not authorization or not authorization.startswith("Bearer "):
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
