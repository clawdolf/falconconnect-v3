"""Conference bridge router — PSTN 3-way calling (Seb + Lead + Carrier).

Endpoints for starting/managing conferences, TwiML webhooks, and caller ID verification.
"""

import base64
import hashlib
import hmac
import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import Response
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from sqlalchemy import select

from db.database import get_session
from db.models import ConferenceSession
from middleware.auth import require_auth
from config import get_settings
from services import conference as conf_service
from services import twilio_client
from utils.rate_limit import limiter, user_or_ip_key


async def _assert_conf_ownership(
    session: AsyncSession, conf_id: str, user: dict
) -> None:
    """Raise 403/404 if `conf_id` does not belong to the caller."""
    result = await session.execute(
        select(ConferenceSession.user_id).where(ConferenceSession.id == conf_id)
    )
    owner = result.scalar_one_or_none()
    if owner is None:
        raise HTTPException(status_code=404, detail="Conference not found")
    caller = user.get("user_id") or user.get("sub")
    if owner != caller:
        raise HTTPException(status_code=403, detail="Not your conference session")

logger = logging.getLogger("falconconnect.router.conference")

router = APIRouter()


# ── Request/Response Models ──


class StartConferenceRequest(BaseModel):
    lead_phone: str
    carrier_phone: str
    seb_close_number: str
    lead_id: Optional[str] = None


class StartBridgeRequest(BaseModel):
    lead_phone: str
    lead_id: Optional[str] = None


class StartBridgeResponse(BaseModel):
    conf_id: str
    status: str
    lead_phone: str
    lead_id: str
    bridge_number: str
    seb_phone: str
    conference_name: str
    transfer_instructions: str


class CarrierRequest(BaseModel):
    carrier_phone: str
    carrier_label: str = "Carrier"


class DialCarrierRequest(BaseModel):
    pass  # No body needed — carrier_phone is on the session


class CallerIdVerifyRequest(BaseModel):
    phone_number: str


class CallerIdConfirmRequest(BaseModel):
    phone_number: str
    code: str


# ── Conference Management Endpoints ──


# ── Static routes FIRST (before parameterized {conf_id} routes) ──


@router.get("/conference/health")
@limiter.limit("10/minute")
async def conference_health(request: Request, user=Depends(require_auth)):
    """Debug: confirm Twilio creds are loaded. Authenticated only — SID is sensitive."""
    from config import get_settings
    s = get_settings()
    sid = s.twilio_account_sid
    return {
        "twilio_account_sid": f"{sid[:8]}...{sid[-4:]}" if len(sid) > 12 else ("EMPTY" if not sid else sid),
        "twilio_auth_token_set": bool(s.twilio_auth_token),
        "twilio_from_number": s.twilio_from_number,
    }


@router.get("/conference/sessions")
async def list_sessions(
    session: AsyncSession = Depends(get_session),
    user=Depends(require_auth),
):
    """List recent conference sessions (last 10), scoped to the caller."""
    return await conf_service.list_sessions(
        session, user_id=user.get("user_id") or user.get("sub")
    )


@router.post("/conference/start")
@limiter.limit("10/hour;50/day", key_func=user_or_ip_key)
async def start_conference(
    req: StartConferenceRequest,
    request: Request,
    session: AsyncSession = Depends(get_session),
    user=Depends(require_auth),
):
    """Start a 3-way conference bridge. Dials Seb first, then Lead.

    Per-user quota: 10/hour, 50/day. Twilio bills per-minute for outbound
    PSTN; this caps the bleed if a single account is compromised.
    """
    base_url = _get_public_url(request)

    try:
        result = await conf_service.start_conference(
            session=session,
            lead_phone=req.lead_phone,
            carrier_phone=req.carrier_phone,
            seb_close_number=req.seb_close_number,
            user_id=user.get("user_id") or user.get("sub"),
            lead_id=req.lead_id,
            base_url=base_url,
        )
        return result
    except Exception as e:
        logger.error("Failed to start conference: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/conference/bridge/start", response_model=StartBridgeResponse)
@limiter.limit("10/hour;50/day", key_func=user_or_ip_key)
async def start_bridge_session(
    req: StartBridgeRequest,
    request: Request,
    session: AsyncSession = Depends(get_session),
    user=Depends(require_auth),
):
    """Create a pending 3 Way Bridge transfer session. Does not dial the lead."""
    try:
        return await conf_service.start_bridge_session(
            session=session,
            lead_phone=req.lead_phone,
            lead_id=req.lead_id,
            user_id=user.get("user_id") or user.get("sub"),
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error("Failed to create bridge session: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


# ── Parameterized routes ──


@router.post("/conference/{conf_id}/dial-seb")
async def dial_seb(
    conf_id: str,
    request: Request,
    session: AsyncSession = Depends(get_session),
    user=Depends(require_auth),
):
    """Dial Seb's Close number into the conference. Called after lead picks up."""
    await _assert_conf_ownership(session, conf_id, user)
    base_url = _get_public_url(request)
    try:
        result = await conf_service.dial_seb(session, conf_id, base_url=base_url)
        return result
    except Exception as e:
        logger.error("Failed to dial Seb: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/conference/{conf_id}/dial-carrier")
async def dial_carrier(
    conf_id: str,
    request: Request,
    session: AsyncSession = Depends(get_session),
    user=Depends(require_auth),
):
    """Dial the carrier into an existing conference."""
    await _assert_conf_ownership(session, conf_id, user)
    base_url = _get_public_url(request)
    try:
        result = await conf_service.dial_carrier(session, conf_id, base_url=base_url)
        return result
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.error("Failed to dial carrier: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/conference/{conf_id}/upgrade")
async def upgrade_conference(
    conf_id: str,
    request: Request,
    session: AsyncSession = Depends(get_session),
    user=Depends(require_auth),
):
    """Redirect the Close child leg into conference first."""
    await _assert_conf_ownership(session, conf_id, user)
    base_url = _get_public_url(request)
    try:
        return await conf_service.upgrade_to_conference(
            session=session,
            conf_id=conf_id,
            base_url=base_url,
        )
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e))
    except Exception as e:
        logger.error("Failed to upgrade conference: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/conference/{conf_id}/carrier")
async def add_carrier(
    conf_id: str,
    req: CarrierRequest,
    request: Request,
    session: AsyncSession = Depends(get_session),
    user=Depends(require_auth),
):
    """Add the carrier as the third conference participant."""
    await _assert_conf_ownership(session, conf_id, user)
    base_url = _get_public_url(request)
    try:
        return await conf_service.add_carrier(
            session=session,
            conf_id=conf_id,
            carrier_phone=req.carrier_phone,
            carrier_label=req.carrier_label,
            base_url=base_url,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error("Failed to add carrier: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/conference/{conf_id}")
async def get_conference(
    conf_id: str,
    session: AsyncSession = Depends(get_session),
    user=Depends(require_auth),
):
    """Get live conference status including participant states."""
    await _assert_conf_ownership(session, conf_id, user)
    try:
        return await conf_service.get_conference_status(session, conf_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post("/conference/{conf_id}/mute/{participant}")
async def mute_participant(
    conf_id: str,
    participant: str,
    session: AsyncSession = Depends(get_session),
    user=Depends(require_auth),
):
    """Mute a participant (seb|lead|carrier)."""
    await _assert_conf_ownership(session, conf_id, user)
    _validate_participant(participant)
    try:
        return await conf_service.mute_participant(session, conf_id, participant)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post("/conference/{conf_id}/unmute/{participant}")
async def unmute_participant(
    conf_id: str,
    participant: str,
    session: AsyncSession = Depends(get_session),
    user=Depends(require_auth),
):
    """Unmute a participant."""
    await _assert_conf_ownership(session, conf_id, user)
    _validate_participant(participant)
    try:
        return await conf_service.unmute_participant(session, conf_id, participant)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post("/conference/{conf_id}/hold/{participant}")
async def hold_participant(
    conf_id: str,
    participant: str,
    session: AsyncSession = Depends(get_session),
    user=Depends(require_auth),
):
    """Put a participant on hold with music."""
    await _assert_conf_ownership(session, conf_id, user)
    _validate_participant(participant)
    try:
        return await conf_service.hold_participant(session, conf_id, participant)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post("/conference/{conf_id}/unhold/{participant}")
async def unhold_participant(
    conf_id: str,
    participant: str,
    session: AsyncSession = Depends(get_session),
    user=Depends(require_auth),
):
    """Take a participant off hold."""
    await _assert_conf_ownership(session, conf_id, user)
    _validate_participant(participant)
    try:
        return await conf_service.unhold_participant(session, conf_id, participant)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post("/conference/{conf_id}/drop/{participant}")
async def drop_participant(
    conf_id: str,
    participant: str,
    session: AsyncSession = Depends(get_session),
    user=Depends(require_auth),
):
    """Drop one participant call leg without ending the whole conference."""
    await _assert_conf_ownership(session, conf_id, user)
    _validate_participant(participant)
    try:
        return await conf_service.drop_participant(session, conf_id, participant)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post("/conference/{conf_id}/end")
async def end_conference(
    conf_id: str,
    session: AsyncSession = Depends(get_session),
    user=Depends(require_auth),
):
    """End a conference — hangs up all participants, logs to Close."""
    await _assert_conf_ownership(session, conf_id, user)
    try:
        return await conf_service.end_conference_session(session, conf_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


# ── Caller ID Verification (static routes — must be before {conf_id} routes) ──


@router.post("/conference/caller-id/verify")
@limiter.limit("5/hour;20/day", key_func=user_or_ip_key)
async def verify_caller_id(
    req: CallerIdVerifyRequest,
    request: Request,
    user=Depends(require_auth),
):
    """Initiate caller ID verification for a phone number.

    Twilio will call the number and play a 6-digit code. Per-user quota:
    5/hour, 20/day. Each call is billed at Twilio voice rates.
    """
    try:
        result = await twilio_client.initiate_caller_id_verification(req.phone_number)
        return {
            "phone_number": req.phone_number,
            "call_sid": result.get("call_sid"),
            "validation_code": result.get("validation_code"),
            "status": "verification_initiated",
        }
    except Exception as e:
        logger.error("Caller ID verification failed: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/conference/caller-id/confirm")
async def confirm_caller_id(
    req: CallerIdConfirmRequest,
    user=Depends(require_auth),
):
    """Confirm caller ID verification (not needed for Twilio — verification is automatic).

    Twilio verifies the number when the recipient enters the code during the call.
    This endpoint exists for UI flow — it checks if the number is now verified.
    """
    try:
        verified_ids = await twilio_client.list_verified_caller_ids()
        is_verified = any(
            v.get("phone_number") == req.phone_number
            for v in verified_ids
        )
        return {
            "phone_number": req.phone_number,
            "verified": is_verified,
        }
    except Exception as e:
        logger.error("Caller ID confirm check failed: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/conference/caller-id/list")
async def list_caller_ids(
    user=Depends(require_auth),
):
    """List all verified caller IDs and Seb's Close numbers with verification status."""
    try:
        verified_ids = await twilio_client.list_verified_caller_ids()
        verified_numbers = {v.get("phone_number") for v in verified_ids}

        # Build list of all Close numbers with verification status
        numbers = []
        for num in conf_service.CLOSE_NUMBERS:
            numbers.append({
                "phone_number": num,
                "verified": num in verified_numbers,
            })

        return {
            "numbers": numbers,
            "verified_count": sum(1 for n in numbers if n["verified"]),
            "total_count": len(numbers),
        }
    except Exception as e:
        logger.error("List caller IDs failed: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


# ── TwiML Webhooks (no auth — Twilio calls these) ──


@router.post("/conference/twiml/bridge-inbound")
async def twiml_bridge_inbound(
    request: Request,
    session: AsyncSession = Depends(get_session),
):
    """Inbound Twilio bridge webhook for the transferred Close lead call."""
    form = await _twilio_form(request)
    from_phone = form.get("From") or request.query_params.get("From", "")
    parent_call_sid = form.get("CallSid") or request.query_params.get("CallSid", "")
    base_url = _get_public_url(request)
    try:
        _, twiml = await conf_service.handle_bridge_inbound(
            session=session,
            from_phone=from_phone,
            parent_call_sid=parent_call_sid,
            base_url=base_url,
        )
    except Exception as e:
        logger.error("Bridge inbound failed: %s", e)
        twiml = """<?xml version="1.0" encoding="UTF-8"?><Response><Say>Bridge unavailable.</Say></Response>"""
    return Response(content=twiml, media_type="application/xml")


@router.post("/conference/twiml/number-status")
async def twiml_number_status(
    request: Request,
    session: AsyncSession = Depends(get_session),
):
    """Track the Close child call leg generated by inbound Dial Number."""
    form = await _twilio_form(request)
    await conf_service.handle_number_status(
        session=session,
        conf_id=request.query_params.get("conf_id", ""),
        call_sid=form.get("CallSid") or "",
        parent_call_sid=form.get("ParentCallSid") or "",
        call_status=form.get("CallStatus") or "",
    )
    return {"status": "ok"}


@router.post("/conference/twiml/dial-ended")
async def twiml_dial_ended(
    request: Request,
    session: AsyncSession = Depends(get_session),
):
    """Dial action callback. Moves the lead parent leg into conference after upgrade."""
    await _twilio_form(request)
    conf_id = request.query_params.get("conf_id", "")
    conf = await conf_service.should_join_lead_after_dial(session=session, conf_id=conf_id)
    if not conf:
        return Response(content='<?xml version="1.0" encoding="UTF-8"?><Response></Response>', media_type="application/xml")
    twiml = conf_service.conference_twiml(
        conference_name=conf.conference_sid,
        conf_id=str(conf.id),
        label="lead",
        base_url=_get_public_url(request),
    )
    return Response(content=twiml, media_type="application/xml")


@router.post("/conference/twiml/conference")
async def twiml_conference(request: Request):
    """TwiML endpoint — tells a participant to join the conference.

    Twilio calls this URL when a participant answers.
    Returns TwiML XML that joins them to the named conference.
    """
    await _twilio_form(request)
    conference_name = request.query_params.get("conference_name", "fc-bridge-default")
    conf_id = request.query_params.get("conf_id", "")
    label = request.query_params.get("label", "lead")

    twiml = conf_service.conference_twiml(
        conference_name=conference_name,
        conf_id=conf_id,
        label=label,
        base_url=_get_public_url(request),
    )

    return Response(content=twiml, media_type="application/xml")


@router.post("/conference/twiml/status")
async def twiml_status(
    request: Request,
    session: AsyncSession = Depends(get_session),
):
    """Twilio status callback — receives conference and participant events.

    No auth — Twilio sends POST form data.
    Events: participant-join, participant-leave, conference-start, conference-end
    """
    form = await _twilio_form(request)
    conf_id = request.query_params.get("conf_id", "")
    event = form.get("StatusCallbackEvent", "")
    conference_sid = form.get("ConferenceSid", "")
    call_sid = form.get("CallSid", "")

    logger.info(
        "Twilio status: event=%s conf_sid=%s call_sid=%s conf_id=%s",
        event, conference_sid, call_sid, conf_id,
    )

    # Update conference SID if we have one
    if conf_id and conference_sid:
        try:
            await conf_service.update_conference_sid(session, conf_id, conference_sid, event=event, call_sid=call_sid)
        except Exception as e:
            logger.warning("Could not update conference SID: %s", e)

    return {"status": "ok"}


@router.post("/conference/twiml/recording-status")
async def twiml_recording_status(
    request: Request,
    session: AsyncSession = Depends(get_session),
):
    """Capture recording callbacks without blocking the call flow."""
    form = await _twilio_form(request)
    await conf_service.capture_recording_callback(
        session=session,
        conf_id=request.query_params.get("conf_id", ""),
        recording_sid=form.get("RecordingSid") or "",
        recording_url=form.get("RecordingUrl") or "",
    )
    return {"status": "ok"}


# ── Helpers ──


def _validate_participant(participant: str) -> None:
    if participant not in ("seb", "lead", "carrier"):
        raise HTTPException(
            status_code=400,
            detail=f"Invalid participant '{participant}'. Must be seb, lead, or carrier.",
        )


async def _twilio_form(request: Request) -> dict:
    """Return Twilio form data after validating X-Twilio-Signature."""
    try:
        form = dict(await request.form())
    except Exception:
        form = {}
    _require_twilio_signature(request, form)
    return form


def _require_twilio_signature(request: Request, form: dict) -> None:
    """Validate Twilio's request signature before call-control side effects."""
    token = get_settings().twilio_auth_token
    signature = request.headers.get("X-Twilio-Signature", "")
    if not token:
        logger.error("TWILIO_AUTH_TOKEN is missing; refusing unauthenticated Twilio webhook")
        raise HTTPException(status_code=500, detail="Twilio webhook validation is not configured")
    if not signature:
        raise HTTPException(status_code=403, detail="Missing Twilio signature")

    query = request.url.query
    url = f"{_get_public_url(request)}{request.url.path}"
    if query:
        url = f"{url}?{query}"
    signed = url + "".join(f"{key}{value}" for key, value in sorted(form.items()))
    expected = base64.b64encode(
        hmac.new(token.encode("utf-8"), signed.encode("utf-8"), hashlib.sha1).digest()
    ).decode("ascii")
    if not hmac.compare_digest(expected, signature):
        logger.warning("Rejected invalid Twilio signature for %s", request.url.path)
        raise HTTPException(status_code=403, detail="Invalid Twilio signature")


def _get_public_url(request: Request) -> str:
    """Get the public-facing URL for Twilio callbacks — must always be https://."""
    host = request.headers.get("host", "")
    if "falconnect.org" in host:
        return "https://falconnect.org"
    if "onrender.com" in host:
        return f"https://{host}"
    # Fallback — force https regardless of what the proxy reports
    base = str(request.base_url).rstrip("/")
    return base.replace("http://", "https://")
