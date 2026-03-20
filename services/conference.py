"""Conference bridge business logic.

Orchestrates 3-way PSTN conferences: Seb ↔ Lead ↔ Carrier.
Uses Twilio Conferences API (via twilio_client.py).
"""

import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Optional

import httpx
from sqlalchemy import desc, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from config import get_settings
from db.models import ConferenceSession
from services import twilio_client

logger = logging.getLogger("falconconnect.conference")

# Seb's 19 Close phone numbers (pre-populated for caller ID verification)
CLOSE_NUMBERS = [
    "+14809999040",
    "+14066463344",
    "+19808909888",
    "+12078881046",
    "+12078087772",
    "+19133793347",
    "+19719993141",
    "+15419195227",
    "+18323042324",
    "+14699492579",
    "+12156077444",
    "+19843685120",
    "+12076067024",
    "+17862548006",
    "+17867677634",
    "+18322420926",
    "+18326482428",
    "+19727341666",
]

# Default hold music (Twilio's built-in)
HOLD_MUSIC_URL = "http://twimlets.com/holdmusic?Bucket=com.twilio.music.classical"


def _generate_conference_name() -> str:
    """Generate a unique conference friendly name."""
    return f"fc-bridge-{uuid.uuid4().hex[:12]}"


async def start_conference(
    session: AsyncSession,
    lead_phone: str,
    carrier_phone: str,
    seb_close_number: str,
    lead_id: Optional[str] = None,
    base_url: str = "",
) -> Dict[str, Any]:
    """Start a 3-way conference bridge.

    Sequence:
    1. Create conference + dial Seb first (on his selected Close number)
    2. Seb picks up on Close → dial Lead
    3. Lead picks up → Seb + Lead connected
    4. Carrier dialed later via separate action (or automatically after lead connects)

    Returns the conference session dict.
    """
    settings = get_settings()
    conference_name = _generate_conference_name()

    # Create DB record
    conf_session = ConferenceSession(
        lead_phone=lead_phone,
        carrier_phone=carrier_phone,
        seb_phone=seb_close_number,
        lead_id=lead_id or "",
        status="initiating",
        started_at=datetime.now(timezone.utc),
    )
    session.add(conf_session)
    await session.flush()
    conf_id = str(conf_session.id)

    status_callback = f"{base_url}/api/conference/twiml/status"
    twiml_url = f"{base_url}/api/conference/twiml/conference?conference_name={conference_name}&conf_id={conf_id}"

    # Step 1: Dial Seb on his Close number
    # Caller ID = FC bridge Twilio number (or verified Close number if available)
    try:
        seb_result = await twilio_client.create_participant(
            conference_name=conference_name,
            to=seb_close_number,
            from_=settings.twilio_from_number,
            status_callback_url=status_callback,
            twiml_url=twiml_url,
            label="seb",
            timeout=30,
        )
        conf_session.seb_participant_sid = seb_result.get("call_sid", "")
    except Exception as e:
        logger.error("Failed to dial Seb: %s", e)
        conf_session.status = "seb_no_answer"
        await session.commit()
        raise

    # Step 2: Dial Lead
    try:
        lead_result = await twilio_client.create_participant(
            conference_name=conference_name,
            to=lead_phone,
            from_=settings.twilio_from_number,  # FC bridge number — caller ID verification not yet active
            status_callback_url=status_callback,
            twiml_url=twiml_url,
            label="lead",
            timeout=30,
        )
        conf_session.lead_participant_sid = lead_result.get("call_sid", "")
    except Exception as e:
        logger.error("Failed to dial lead: %s", e)
        conf_session.status = "lead_no_answer"
        await session.commit()
        raise

    # Conference is now initiating — Seb and Lead will join when they answer
    conf_session.status = "active"
    conf_session.conference_sid = conference_name  # Store the friendly name; real SID comes from status callback
    await session.commit()

    return {
        "conf_id": conf_id,
        "conference_name": conference_name,
        "conference_sid": conference_name,
        "status": "active",
        "seb_call_sid": conf_session.seb_participant_sid,
        "lead_call_sid": conf_session.lead_participant_sid,
    }


async def dial_carrier(
    session: AsyncSession,
    conf_id: str,
    base_url: str = "",
) -> Dict[str, Any]:
    """Dial the carrier into an existing conference.

    Called when Seb is ready to bring in the carrier (after muting lead).
    """
    result = await session.execute(
        select(ConferenceSession).where(ConferenceSession.id == conf_id)
    )
    conf = result.scalar_one_or_none()
    if not conf:
        raise ValueError(f"Conference {conf_id} not found")

    settings = get_settings()
    status_callback = f"{base_url}/api/conference/twiml/status"
    twiml_url = f"{base_url}/api/conference/twiml/conference?conference_name={conf.conference_sid}&conf_id={conf_id}"

    try:
        carrier_result = await twilio_client.create_participant(
            conference_name=conf.conference_sid,
            to=conf.carrier_phone,
            from_=settings.twilio_from_number,
            status_callback_url=status_callback,
            twiml_url=twiml_url,
            label="carrier",
            timeout=60,  # Longer timeout for IVR navigation
        )
        conf.carrier_participant_sid = carrier_result.get("call_sid", "")
        await session.commit()
        return {
            "carrier_call_sid": conf.carrier_participant_sid,
            "status": "dialing_carrier",
        }
    except Exception as e:
        logger.error("Failed to dial carrier: %s", e)
        raise


async def mute_participant(
    session: AsyncSession,
    conf_id: str,
    participant: str,
) -> Dict[str, Any]:
    """Mute a participant (seb|lead|carrier)."""
    conf = await _get_conference(session, conf_id)
    call_sid = _get_participant_sid(conf, participant)
    if not call_sid:
        raise ValueError(f"No call SID for participant {participant}")

    await twilio_client.update_participant(
        conf.conference_sid, call_sid, muted=True
    )
    return {"participant": participant, "muted": True}


async def unmute_participant(
    session: AsyncSession,
    conf_id: str,
    participant: str,
) -> Dict[str, Any]:
    """Unmute a participant."""
    conf = await _get_conference(session, conf_id)
    call_sid = _get_participant_sid(conf, participant)
    if not call_sid:
        raise ValueError(f"No call SID for participant {participant}")

    await twilio_client.update_participant(
        conf.conference_sid, call_sid, muted=False
    )
    return {"participant": participant, "muted": False}


async def hold_participant(
    session: AsyncSession,
    conf_id: str,
    participant: str,
) -> Dict[str, Any]:
    """Put a participant on hold with music."""
    conf = await _get_conference(session, conf_id)
    call_sid = _get_participant_sid(conf, participant)
    if not call_sid:
        raise ValueError(f"No call SID for participant {participant}")

    await twilio_client.update_participant(
        conf.conference_sid, call_sid, hold=True, hold_url=HOLD_MUSIC_URL
    )
    return {"participant": participant, "on_hold": True}


async def unhold_participant(
    session: AsyncSession,
    conf_id: str,
    participant: str,
) -> Dict[str, Any]:
    """Take a participant off hold."""
    conf = await _get_conference(session, conf_id)
    call_sid = _get_participant_sid(conf, participant)
    if not call_sid:
        raise ValueError(f"No call SID for participant {participant}")

    await twilio_client.update_participant(
        conf.conference_sid, call_sid, hold=False
    )
    return {"participant": participant, "on_hold": False}


async def end_conference_session(
    session: AsyncSession,
    conf_id: str,
) -> Dict[str, Any]:
    """End the conference — hang up all participants, log to Close."""
    conf = await _get_conference(session, conf_id)

    # End the Twilio conference (hangs up all legs)
    try:
        await twilio_client.end_conference(conf.conference_sid)
    except Exception as e:
        logger.warning("Error ending Twilio conference: %s", e)

    # Calculate duration
    now = datetime.now(timezone.utc)
    duration = None
    if conf.started_at:
        duration = int((now - conf.started_at).total_seconds())

    conf.status = "ended"
    conf.ended_at = now
    conf.call_duration_seconds = duration

    # Log to Close
    try:
        await _log_to_close(conf)
        conf.close_activity_logged = True
    except Exception as e:
        logger.error("Failed to log conference to Close: %s", e)

    await session.commit()

    return {
        "conf_id": conf_id,
        "status": "ended",
        "duration_seconds": duration,
        "close_logged": conf.close_activity_logged,
    }


async def get_conference_status(
    session: AsyncSession,
    conf_id: str,
) -> Dict[str, Any]:
    """Get live conference status including participant states."""
    conf = await _get_conference(session, conf_id)

    # Get live participant info from Twilio
    participants = {}
    if conf.status == "active" and conf.conference_sid:
        try:
            twilio_participants = await twilio_client.list_conference_participants(
                conf.conference_sid
            )
            for p in twilio_participants:
                label = p.get("label", "")
                participants[label] = {
                    "call_sid": p.get("call_sid"),
                    "muted": p.get("muted", False),
                    "hold": p.get("hold", False),
                    "status": p.get("status", "unknown"),
                }
        except Exception as e:
            logger.warning("Could not fetch Twilio participants: %s", e)

    return {
        "conf_id": str(conf.id),
        "conference_sid": conf.conference_sid or "",
        "lead_phone": conf.lead_phone,
        "carrier_phone": conf.carrier_phone,
        "seb_phone": conf.seb_phone,
        "lead_id": conf.lead_id or "",
        "status": conf.status,
        "started_at": conf.started_at.isoformat() if conf.started_at else None,
        "ended_at": conf.ended_at.isoformat() if conf.ended_at else None,
        "duration_seconds": conf.call_duration_seconds,
        "close_logged": conf.close_activity_logged,
        "participants": {
            "seb": participants.get("seb", {"call_sid": conf.seb_participant_sid, "status": "unknown"}),
            "lead": participants.get("lead", {"call_sid": conf.lead_participant_sid, "status": "unknown"}),
            "carrier": participants.get("carrier", {"call_sid": conf.carrier_participant_sid, "status": "unknown"}),
        },
    }


async def list_sessions(
    session: AsyncSession,
    limit: int = 10,
) -> list:
    """List recent conference sessions."""
    result = await session.execute(
        select(ConferenceSession)
        .order_by(desc(ConferenceSession.started_at))
        .limit(limit)
    )
    sessions = result.scalars().all()
    return [
        {
            "conf_id": str(s.id),
            "lead_phone": s.lead_phone,
            "carrier_phone": s.carrier_phone,
            "seb_phone": s.seb_phone,
            "status": s.status,
            "started_at": s.started_at.isoformat() if s.started_at else None,
            "ended_at": s.ended_at.isoformat() if s.ended_at else None,
            "duration_seconds": s.call_duration_seconds,
            "close_logged": s.close_activity_logged,
        }
        for s in sessions
    ]


async def update_conference_sid(
    session: AsyncSession,
    conf_id: str,
    conference_sid: str,
) -> None:
    """Update the real Twilio conference SID from a status callback."""
    await session.execute(
        update(ConferenceSession)
        .where(ConferenceSession.id == conf_id)
        .values(conference_sid=conference_sid)
    )
    await session.commit()


# ── Private helpers ──


async def _get_conference(session: AsyncSession, conf_id: str) -> ConferenceSession:
    result = await session.execute(
        select(ConferenceSession).where(ConferenceSession.id == conf_id)
    )
    conf = result.scalar_one_or_none()
    if not conf:
        raise ValueError(f"Conference {conf_id} not found")
    return conf


def _get_participant_sid(conf: ConferenceSession, participant: str) -> Optional[str]:
    mapping = {
        "seb": conf.seb_participant_sid,
        "lead": conf.lead_participant_sid,
        "carrier": conf.carrier_participant_sid,
    }
    return mapping.get(participant)


async def _log_to_close(conf: ConferenceSession) -> None:
    """Log the conference call to Close as a call activity."""
    settings = get_settings()
    if not settings.close_api_key:
        logger.warning("No CLOSE_API_KEY — skipping Close call log")
        return

    if not conf.lead_id:
        logger.warning("No lead_id on conference %s — skipping Close log", conf.id)
        return

    duration = conf.call_duration_seconds or 0
    note = (
        f"3-way carrier conference via FC Bridge. "
        f"Carrier: {conf.carrier_phone}. "
        f"Participants: Seb ({conf.seb_phone}), Lead ({conf.lead_phone}), Carrier."
    )

    payload = {
        "lead_id": conf.lead_id,
        "direction": "outbound",
        "duration": duration,
        "note": note,
        "status": "completed",
    }

    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.post(
            "https://api.close.com/api/v1/activity/call/",
            json=payload,
            auth=(settings.close_api_key, ""),
        )
        resp.raise_for_status()
        logger.info("Logged conference %s to Close: %s", conf.id, resp.json().get("id"))
