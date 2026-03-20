"""Conference bridge router — PSTN 3-way calling (Seb + Lead + Carrier).

Endpoints for starting/managing conferences, TwiML webhooks, and caller ID verification.
"""

import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import Response
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from db.database import get_session
from middleware.auth import require_auth
from services import conference as conf_service
from services import twilio_client

logger = logging.getLogger("falconconnect.router.conference")

router = APIRouter()


# ── Request/Response Models ──


class StartConferenceRequest(BaseModel):
    lead_phone: str
    carrier_phone: str
    seb_close_number: str
    lead_id: Optional[str] = None


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
async def conference_health():
    """Debug: confirm Twilio creds are loaded."""
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
    """List recent conference sessions (last 10)."""
    return await conf_service.list_sessions(session)


@router.post("/conference/start")
async def start_conference(
    req: StartConferenceRequest,
    request: Request,
    session: AsyncSession = Depends(get_session),
    user=Depends(require_auth),
):
    """Start a 3-way conference bridge. Dials Seb first, then Lead."""
    base_url = _get_public_url(request)

    try:
        result = await conf_service.start_conference(
            session=session,
            lead_phone=req.lead_phone,
            carrier_phone=req.carrier_phone,
            seb_close_number="+14809999040",  # Always Seb's Close main line — hardcoded so Close records inbound leg
            lead_id=req.lead_id,
            base_url=base_url,
        )
        return result
    except Exception as e:
        logger.error("Failed to start conference: %s", e)
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
    base_url = _get_public_url(request)
    try:
        result = await conf_service.dial_carrier(session, conf_id, base_url=base_url)
        return result
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.error("Failed to dial carrier: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/conference/{conf_id}")
async def get_conference(
    conf_id: str,
    session: AsyncSession = Depends(get_session),
    user=Depends(require_auth),
):
    """Get live conference status including participant states."""
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
    _validate_participant(participant)
    try:
        return await conf_service.unhold_participant(session, conf_id, participant)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post("/conference/{conf_id}/end")
async def end_conference(
    conf_id: str,
    session: AsyncSession = Depends(get_session),
    user=Depends(require_auth),
):
    """End a conference — hangs up all participants, logs to Close."""
    try:
        return await conf_service.end_conference_session(session, conf_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


# ── Caller ID Verification (static routes — must be before {conf_id} routes) ──


@router.post("/conference/caller-id/verify")
async def verify_caller_id(
    req: CallerIdVerifyRequest,
    user=Depends(require_auth),
):
    """Initiate caller ID verification for a phone number.

    Twilio will call the number and play a 6-digit code.
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


@router.post("/conference/twiml/conference")
async def twiml_conference(request: Request):
    """TwiML endpoint — tells a participant to join the conference.

    Twilio calls this URL when a participant answers.
    Returns TwiML XML that joins them to the named conference.
    """
    conference_name = request.query_params.get("conference_name", "fc-bridge-default")
    conf_id = request.query_params.get("conf_id", "")

    # Generate TwiML response — statusCallback MUST be absolute URL, Twilio won't follow relative paths
    public_base = "https://falconconnect.onrender.com"
    twiml = f"""<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Dial>
        <Conference
            statusCallback="{public_base}/api/conference/twiml/status?conf_id={conf_id}"
            statusCallbackEvent="start end join leave mute hold"
            record="record-from-start"
            waitUrl="http://twimlets.com/holdmusic?Bucket=com.twilio.music.classical"
            startConferenceOnEnter="true"
            endConferenceOnExit="false"
        >{conference_name}</Conference>
    </Dial>
</Response>"""

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
    try:
        form = await request.form()
    except Exception:
        form = {}
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
            await conf_service.update_conference_sid(session, conf_id, conference_sid)
        except Exception as e:
            logger.warning("Could not update conference SID: %s", e)

    return {"status": "ok"}


# ── Helpers ──


def _validate_participant(participant: str) -> None:
    if participant not in ("seb", "lead", "carrier"):
        raise HTTPException(
            status_code=400,
            detail=f"Invalid participant '{participant}'. Must be seb, lead, or carrier.",
        )


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
