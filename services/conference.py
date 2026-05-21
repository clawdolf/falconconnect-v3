"""Conference bridge business logic.

Implements the transfer-first 3 Way Bridge flow:
Close call -> Twilio bridge number -> Close child leg -> conference upgrade -> carrier.
"""

import logging
import re
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Optional
from urllib.parse import quote, urlencode

from sqlalchemy import desc, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from config import get_settings
from db.models import CarrierFavorite, ConferenceSession
from services import twilio_client

logger = logging.getLogger("falconconnect.conference")

HOLD_MUSIC_URL = "http://twimlets.com/holdmusic?Bucket=com.twilio.music.classical"

# Kept for existing caller ID endpoints. Runtime values come from environment.
CLOSE_NUMBERS: list[str] = []
AUTO_DETECTED_USER = "twilio-live-detected"
ACTIVE_BRIDGE_STATUSES = {
    "transfer_received",
    "close_connected",
    "upgrade_pending",
    "conference_live",
    "dialing_carrier",
    "carrier_connected",
}

def normalize_e164(phone: str) -> str:
    """Convert common US phone formats to E.164."""
    digits = re.sub(r"\D", "", phone or "")
    if len(digits) == 10:
        return f"+1{digits}"
    if len(digits) == 11 and digits.startswith("1"):
        return f"+{digits}"
    if (phone or "").startswith("+") and len(digits) >= 11:
        return f"+{digits}"
    raise ValueError(f"Cannot normalize phone number to E.164: {phone!r}")


def _generate_conference_name(conf_id: str) -> str:
    return f"fc-bridge-{conf_id[:8]}-{uuid.uuid4().hex[:6]}"


def _favorite_payload(fav: CarrierFavorite) -> Dict[str, Any]:
    return {
        "id": str(fav.id),
        "carrier_name": fav.carrier_name,
        "carrier_dept": fav.carrier_dept or "",
        "carrier_number": fav.carrier_number,
        "dial_instructions": fav.dial_instructions or "",
        "created_at": fav.created_at.isoformat() if fav.created_at else None,
        "updated_at": fav.updated_at.isoformat() if fav.updated_at else None,
    }


async def list_carrier_favorites(session: AsyncSession, user_id: str) -> list[Dict[str, Any]]:
    stmt = select(CarrierFavorite).where(CarrierFavorite.user_id == user_id).order_by(CarrierFavorite.carrier_name, CarrierFavorite.carrier_dept)
    result = await session.execute(stmt)
    return [_favorite_payload(fav) for fav in result.scalars().all()]


async def create_carrier_favorite(
    session: AsyncSession,
    *,
    user_id: str,
    carrier_name: str,
    carrier_dept: str,
    carrier_number: str,
    dial_instructions: str = "",
) -> Dict[str, Any]:
    fav = CarrierFavorite(
        user_id=user_id,
        carrier_name=carrier_name.strip(),
        carrier_dept=carrier_dept.strip(),
        carrier_number=normalize_e164(carrier_number),
        dial_instructions=dial_instructions.strip(),
    )
    if not fav.carrier_name:
        raise ValueError("Carrier name is required")
    if not fav.carrier_dept:
        raise ValueError("Carrier department is required")
    session.add(fav)
    await session.commit()
    await session.refresh(fav)
    return _favorite_payload(fav)


async def update_carrier_favorite(
    session: AsyncSession,
    *,
    favorite_id: str,
    user_id: str,
    carrier_name: str,
    carrier_dept: str,
    carrier_number: str,
    dial_instructions: str = "",
) -> Dict[str, Any]:
    fav = await _get_carrier_favorite(session, favorite_id, user_id)
    fav.carrier_name = carrier_name.strip()
    fav.carrier_dept = carrier_dept.strip()
    fav.carrier_number = normalize_e164(carrier_number)
    fav.dial_instructions = dial_instructions.strip()
    if not fav.carrier_name:
        raise ValueError("Carrier name is required")
    if not fav.carrier_dept:
        raise ValueError("Carrier department is required")
    await session.commit()
    await session.refresh(fav)
    return _favorite_payload(fav)


async def delete_carrier_favorite(session: AsyncSession, *, favorite_id: str, user_id: str) -> Dict[str, Any]:
    fav = await _get_carrier_favorite(session, favorite_id, user_id)
    await session.delete(fav)
    await session.commit()
    return {"deleted": True, "id": favorite_id}


async def _get_carrier_favorite(session: AsyncSession, favorite_id: str, user_id: str) -> CarrierFavorite:
    result = await session.execute(
        select(CarrierFavorite).where(CarrierFavorite.id == favorite_id, CarrierFavorite.user_id == user_id)
    )
    fav = result.scalar_one_or_none()
    if not fav:
        raise ValueError("Carrier favorite not found")
    return fav


async def start_bridge_session(
    session: AsyncSession,
    *,
    lead_phone: str,
    user_id: str,
    lead_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Create a pending transfer session without dialing the lead."""
    settings = get_settings()
    lead_phone = normalize_e164(lead_phone)
    conf = ConferenceSession(
        user_id=user_id,
        lead_phone=lead_phone,
        carrier_phone="",
        seb_phone=_seb_close_number(),
        lead_id=lead_id or "",
        status="waiting_for_transfer",
        started_at=datetime.now(timezone.utc),
    )
    session.add(conf)
    await session.flush()
    conf.conference_sid = _generate_conference_name(str(conf.id))
    await session.commit()
    return {
        "conf_id": str(conf.id),
        "status": conf.status,
        "lead_phone": conf.lead_phone,
        "lead_id": conf.lead_id or "",
        "bridge_number": settings.twilio_from_number,
        "seb_phone": conf.seb_phone,
        "conference_name": conf.conference_sid,
        "transfer_instructions": f"Transfer the active Close call to {settings.twilio_from_number}.",
    }


async def start_conference(
    session: AsyncSession,
    lead_phone: str,
    carrier_phone: str,
    seb_close_number: str,
    user_id: str,
    lead_id: Optional[str] = None,
    base_url: str = "",
) -> Dict[str, Any]:
    """Compatibility wrapper for older clients; creates a pending bridge session."""
    result = await start_bridge_session(
        session=session,
        lead_phone=lead_phone,
        lead_id=lead_id,
        user_id=user_id,
    )
    conf = await _get_conference(session, result["conf_id"])
    conf.carrier_phone = _safe_normalize(carrier_phone)
    conf.seb_phone = _safe_normalize(seb_close_number) or _seb_close_number()
    await session.commit()
    result["carrier_phone"] = conf.carrier_phone
    return result


async def dial_seb(session: AsyncSession, conf_id: str, base_url: str = "") -> Dict[str, Any]:
    """Seb is dialed by the inbound bridge TwiML in the new flow."""
    conf = await _get_conference(session, conf_id)
    return {"conf_id": conf_id, "status": conf.status, "seb_call_sid": conf.seb_participant_sid or ""}


async def handle_bridge_inbound(
    session: AsyncSession,
    *,
    from_phone: str,
    parent_call_sid: str,
    base_url: str,
) -> tuple[ConferenceSession, str]:
    """Capture the transferred lead leg and return TwiML that dials Seb's Close line."""
    lead_phone = _safe_normalize(from_phone)
    conf = await _find_pending_transfer(session, lead_phone)
    if not conf:
        conf = ConferenceSession(
            user_id=AUTO_DETECTED_USER,
            lead_phone=lead_phone or from_phone or "",
            carrier_phone="",
            seb_phone=_seb_close_number(),
            lead_id="",
            status="transfer_received",
            started_at=datetime.now(timezone.utc),
        )
        session.add(conf)
        await session.flush()
        conf.conference_sid = _generate_conference_name(str(conf.id))

    if lead_phone:
        conf.lead_phone = lead_phone
    conf.lead_participant_sid = parent_call_sid
    conf.status = "transfer_received"
    await session.commit()

    conf_id = str(conf.id)
    action_url = f"{base_url}/api/conference/twiml/dial-ended?conf_id={quote(conf_id)}"
    number_status_url = f"{base_url}/api/conference/twiml/number-status?conf_id={quote(conf_id)}"
    recording_url = f"{base_url}/api/conference/twiml/recording-status?conf_id={quote(conf_id)}"
    twiml = f"""<?xml version="1.0" encoding="UTF-8"?>
<Response>
  <Dial answerOnBridge="true" record="record-from-answer-dual" recordingStatusCallback="{recording_url}" action="{action_url}">
    <Number statusCallback="{number_status_url}" statusCallbackEvent="initiated ringing answered completed">{_seb_close_number()}</Number>
  </Dial>
</Response>"""
    return conf, twiml


async def handle_number_status(
    session: AsyncSession,
    *,
    conf_id: str,
    call_sid: str,
    parent_call_sid: str,
    call_status: str,
) -> Dict[str, Any]:
    """Track the Close child leg created by the inbound Dial Number."""
    conf = await _get_conference_by_hint(session, conf_id, parent_call_sid)
    if not conf:
        return {"status": "ignored"}

    if call_sid:
        conf.seb_participant_sid = call_sid
    if parent_call_sid and not conf.lead_participant_sid:
        conf.lead_participant_sid = parent_call_sid
    if call_status in {"in-progress", "answered"}:
        conf.status = "close_connected"
    elif call_status in {"completed", "busy", "failed", "no-answer", "canceled"} and conf.status not in {
        "upgrade_pending",
        "conference_live",
        "carrier_connected",
        "dialing_carrier",
    }:
        conf.status = f"close_{call_status.replace('-', '_')}"
    await session.commit()
    return {"status": "ok", "conf_id": str(conf.id)}


async def should_join_lead_after_dial(
    session: AsyncSession,
    *,
    conf_id: str,
) -> Optional[ConferenceSession]:
    """Return the session if the parent lead leg should now join the conference."""
    if not conf_id:
        return None
    conf = await _get_conference(session, conf_id)
    if conf.status not in {"upgrade_pending", "conference_live", "carrier_connected", "dialing_carrier"}:
        return None
    conf.status = "conference_live"
    await session.commit()
    return conf


async def upgrade_to_conference(
    session: AsyncSession,
    *,
    conf_id: str,
    base_url: str,
) -> Dict[str, Any]:
    """Redirect the Close child leg first, then let Dial action move the lead leg."""
    conf = await _get_conference(session, conf_id)
    if not conf.seb_participant_sid:
        raise ValueError("Close child call leg is not connected yet")
    if not conf.conference_sid:
        conf.conference_sid = _generate_conference_name(str(conf.id))
        await session.flush()

    conf.status = "upgrade_pending"
    await session.commit()
    params = urlencode(
        {
            "conference_name": conf.conference_sid,
            "conf_id": conf_id,
            "label": "seb",
        }
    )
    await twilio_client.update_call_url(
        conf.seb_participant_sid,
        f"{base_url}/api/conference/twiml/conference?{params}",
    )
    return {
        "conf_id": conf_id,
        "status": "upgrade_pending",
        "conference_name": conf.conference_sid,
        "redirected_call_sid": conf.seb_participant_sid,
    }


async def add_carrier(
    session: AsyncSession,
    *,
    conf_id: str,
    carrier_phone: str,
    carrier_label: str,
    base_url: str,
) -> Dict[str, Any]:
    conf = await _get_conference(session, conf_id)
    settings = get_settings()
    carrier_phone = normalize_e164(carrier_phone)
    conference_name = conf.conference_sid or _generate_conference_name(str(conf.id))
    conf.conference_sid = conference_name

    twiml_url = (
        f"{base_url}/api/conference/twiml/conference?"
        f"{urlencode({'conference_name': conference_name, 'conf_id': conf_id, 'label': 'carrier'})}"
    )
    carrier_result = await twilio_client.create_participant(
        conference_name=conference_name,
        to=carrier_phone,
        from_=settings.twilio_from_number,
        status_callback_url=f"{base_url}/api/conference/twiml/status?conf_id={quote(conf_id)}",
        twiml_url=twiml_url,
        label="carrier",
        timeout=60,
        beep="false",
        end_conference_on_exit=False,
    )
    conf.carrier_phone = carrier_phone
    conf.carrier_participant_sid = carrier_result.get("call_sid", "")
    conf.status = "dialing_carrier"
    await session.commit()
    return {
        "conf_id": conf_id,
        "carrier_phone": carrier_phone,
        "carrier_label": carrier_label,
        "carrier_call_sid": conf.carrier_participant_sid,
        "status": conf.status,
    }


async def dial_carrier(session: AsyncSession, conf_id: str, base_url: str = "") -> Dict[str, Any]:
    """Compatibility wrapper for the older route name."""
    conf = await _get_conference(session, conf_id)
    if not conf.carrier_phone:
        raise ValueError("No carrier phone is stored on this session")
    return await add_carrier(
        session,
        conf_id=conf_id,
        carrier_phone=conf.carrier_phone,
        carrier_label="Carrier",
        base_url=base_url,
    )


async def mute_participant(session: AsyncSession, conf_id: str, participant: str) -> Dict[str, Any]:
    conf = await _get_conference(session, conf_id)
    call_sid = _get_participant_sid(conf, participant)
    if not call_sid:
        raise ValueError(f"No call SID for participant {participant}")
    await twilio_client.update_participant(await _resolve_conference_sid(conf), call_sid, muted=True)
    return {"participant": participant, "muted": True}


async def unmute_participant(session: AsyncSession, conf_id: str, participant: str) -> Dict[str, Any]:
    conf = await _get_conference(session, conf_id)
    call_sid = _get_participant_sid(conf, participant)
    if not call_sid:
        raise ValueError(f"No call SID for participant {participant}")
    await twilio_client.update_participant(await _resolve_conference_sid(conf), call_sid, muted=False)
    return {"participant": participant, "muted": False}


async def hold_participant(session: AsyncSession, conf_id: str, participant: str) -> Dict[str, Any]:
    conf = await _get_conference(session, conf_id)
    call_sid = _get_participant_sid(conf, participant)
    if not call_sid:
        raise ValueError(f"No call SID for participant {participant}")
    await twilio_client.update_participant(await _resolve_conference_sid(conf), call_sid, hold=True, hold_url=HOLD_MUSIC_URL)
    return {"participant": participant, "on_hold": True}


async def unhold_participant(session: AsyncSession, conf_id: str, participant: str) -> Dict[str, Any]:
    conf = await _get_conference(session, conf_id)
    call_sid = _get_participant_sid(conf, participant)
    if not call_sid:
        raise ValueError(f"No call SID for participant {participant}")
    await twilio_client.update_participant(await _resolve_conference_sid(conf), call_sid, hold=False)
    return {"participant": participant, "on_hold": False}


async def drop_participant(session: AsyncSession, conf_id: str, participant: str) -> Dict[str, Any]:
    conf = await _get_conference(session, conf_id)
    call_sid = _get_participant_sid(conf, participant)
    if not call_sid:
        raise ValueError(f"No call SID for participant {participant}")
    await twilio_client.complete_call(call_sid)
    if participant == "carrier":
        conf.carrier_participant_sid = None
        conf.status = "conference_live"
    elif participant == "seb":
        conf.seb_participant_sid = None
    elif participant == "lead":
        conf.lead_participant_sid = None
    await session.commit()
    return {"participant": participant, "dropped": True, "call_sid": call_sid}


async def end_conference_session(session: AsyncSession, conf_id: str) -> Dict[str, Any]:
    conf = await _get_conference(session, conf_id)
    for call_sid in (conf.carrier_participant_sid, conf.seb_participant_sid, conf.lead_participant_sid):
        if call_sid:
            try:
                await twilio_client.complete_call(call_sid)
            except Exception as exc:
                logger.warning("Could not complete call %s: %s", call_sid, exc)
    await _finish_session(session, conf, log_to_close=True)
    return {"conf_id": conf_id, "status": "ended", "duration_seconds": conf.call_duration_seconds, "close_logged": conf.close_activity_logged}


async def get_conference_status(session: AsyncSession, conf_id: str) -> Dict[str, Any]:
    conf = await _get_conference(session, conf_id)
    await _mark_ended_if_no_connected_calls(session, conf)
    twilio_participants: Dict[str, Dict[str, Any]] = {}
    if conf.conference_sid and conf.status in {"conference_live", "carrier_connected", "dialing_carrier", "upgrade_pending"}:
        try:
            real_sid = await _resolve_conference_sid(conf)
            for p in await twilio_client.list_conference_participants(real_sid):
                label = p.get("label") or _label_for_call_sid(conf, p.get("call_sid"))
                if label:
                    twilio_participants[label] = {
                        "call_sid": p.get("call_sid"),
                        "muted": p.get("muted", False),
                        "hold": p.get("hold", False),
                        "status": p.get("status", "unknown"),
                    }
        except Exception as exc:
            logger.warning("Could not fetch Twilio participants for %s: %s", conf_id, exc)

    return {
        "conf_id": str(conf.id),
        "conference_sid": conf.conference_sid or "",
        "lead_phone": conf.lead_phone,
        "carrier_phone": conf.carrier_phone,
        "seb_phone": conf.seb_phone,
        "lead_id": conf.lead_id or "",
        "status": conf.status,
        "bridge_number": get_settings().twilio_from_number,
        "started_at": conf.started_at.isoformat() if conf.started_at else None,
        "ended_at": conf.ended_at.isoformat() if conf.ended_at else None,
        "duration_seconds": conf.call_duration_seconds,
        "close_logged": conf.close_activity_logged,
        "participants": {
            "lead": _participant_state(conf, twilio_participants, "lead", conf.lead_participant_sid, conf.lead_phone),
            "seb": _participant_state(conf, twilio_participants, "seb", conf.seb_participant_sid, conf.seb_phone),
            "carrier": _participant_state(conf, twilio_participants, "carrier", conf.carrier_participant_sid, conf.carrier_phone),
        },
    }


async def find_live_bridge(session: AsyncSession, user_id: str) -> Optional[Dict[str, Any]]:
    """Find the newest live bridge and claim signed Twilio auto-detected sessions for the caller."""
    stmt = (
        select(ConferenceSession)
        .where(ConferenceSession.status.in_(ACTIVE_BRIDGE_STATUSES))
        .where(or_(ConferenceSession.user_id == user_id, ConferenceSession.user_id == AUTO_DETECTED_USER))
        .order_by(desc(ConferenceSession.started_at))
        .limit(5)
    )
    result = await session.execute(stmt)
    for conf in result.scalars().all():
        if conf.user_id == AUTO_DETECTED_USER:
            conf.user_id = user_id
            await session.commit()
        status = await get_conference_status(session, str(conf.id))
        if status.get("status") in ACTIVE_BRIDGE_STATUSES:
            return status
    return None


async def list_sessions(session: AsyncSession, limit: int = 10, user_id: Optional[str] = None) -> list:
    stmt = select(ConferenceSession)
    if user_id:
        stmt = stmt.where(ConferenceSession.user_id == user_id)
    stmt = stmt.order_by(desc(ConferenceSession.started_at)).limit(limit)
    result = await session.execute(stmt)
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


async def update_conference_sid(session: AsyncSession, conf_id: str, conference_sid: str, event: str = "", call_sid: str = "") -> None:
    values: Dict[str, Any] = {"conference_sid": conference_sid}
    if event in {"participant-join", "conference-start"}:
        values["status"] = "conference_live"
    if event in {"conference-end", "participant-leave"}:
        conf = await _get_conference(session, conf_id)
        await _mark_ended_if_no_connected_calls(session, conf)
        if conf.status == "ended":
            return
    if event == "participant-join" and call_sid:
        conf = await _get_conference(session, conf_id)
        if call_sid == conf.carrier_participant_sid:
            values["status"] = "carrier_connected"
    await session.execute(update(ConferenceSession).where(ConferenceSession.id == conf_id).values(**values))
    await session.commit()


async def capture_recording_callback(session: AsyncSession, conf_id: str, recording_sid: str, recording_url: str) -> Dict[str, Any]:
    logger.info("Recording callback conf_id=%s recording_sid=%s url=%s", conf_id, recording_sid, recording_url)
    return {"status": "ok"}


def conference_twiml(*, conference_name: str, conf_id: str, label: str, base_url: str) -> str:
    """Build no-hold-music conference TwiML for a specific participant label."""
    participant_label = "lead" if label in {"lead", "client"} else label
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<Response>
  <Dial>
    <Conference
      statusCallback="{base_url}/api/conference/twiml/status?conf_id={quote(conf_id)}"
      statusCallbackEvent="start end join leave mute hold"
      record="record-from-start"
      participantLabel="{participant_label}"
      beep="false"
      waitUrl=""
      startConferenceOnEnter="true"
      endConferenceOnExit="false">{conference_name}</Conference>
  </Dial>
</Response>"""


async def _find_pending_transfer(session: AsyncSession, lead_phone: str) -> Optional[ConferenceSession]:
    stmt = select(ConferenceSession).where(ConferenceSession.status == "waiting_for_transfer")
    if lead_phone:
        stmt = stmt.where(or_(ConferenceSession.lead_phone == lead_phone, ConferenceSession.lead_phone == ""))
    stmt = stmt.order_by(desc(ConferenceSession.started_at)).limit(1)
    result = await session.execute(stmt)
    return result.scalar_one_or_none()


async def _get_conference(session: AsyncSession, conf_id: str) -> ConferenceSession:
    result = await session.execute(select(ConferenceSession).where(ConferenceSession.id == conf_id))
    conf = result.scalar_one_or_none()
    if not conf:
        raise ValueError(f"Conference {conf_id} not found")
    return conf


async def _get_conference_by_hint(session: AsyncSession, conf_id: str, parent_call_sid: str) -> Optional[ConferenceSession]:
    if conf_id:
        try:
            return await _get_conference(session, conf_id)
        except ValueError:
            pass
    if parent_call_sid:
        result = await session.execute(
            select(ConferenceSession).where(ConferenceSession.lead_participant_sid == parent_call_sid)
        )
        return result.scalar_one_or_none()
    return None


async def _resolve_conference_sid(conf: ConferenceSession) -> str:
    sid = conf.conference_sid or ""
    if sid.startswith("CF"):
        return sid
    try:
        conferences = await twilio_client.find_conferences_by_friendly_name(sid)
        if conferences:
            return conferences[0]["sid"]
    except Exception as exc:
        logger.warning("Could not resolve conference SID for %s: %s", sid, exc)
    return sid


def _get_participant_sid(conf: ConferenceSession, participant: str) -> Optional[str]:
    return {
        "seb": conf.seb_participant_sid,
        "lead": conf.lead_participant_sid,
        "carrier": conf.carrier_participant_sid,
    }.get(participant)


def _label_for_call_sid(conf: ConferenceSession, call_sid: str) -> str:
    if call_sid == conf.lead_participant_sid:
        return "lead"
    if call_sid == conf.seb_participant_sid:
        return "seb"
    if call_sid == conf.carrier_participant_sid:
        return "carrier"
    return ""


def _participant_state(
    conf: ConferenceSession,
    live: Dict[str, Dict[str, Any]],
    label: str,
    call_sid: Optional[str],
    phone: str,
) -> Dict[str, Any]:
    state = live.get(label, {})
    return {
        "label": label,
        "phone": phone or "",
        "call_sid": state.get("call_sid") or call_sid or "",
        "muted": state.get("muted", False),
        "hold": state.get("hold", False),
        "status": state.get("status") or ("known" if call_sid else "not_connected"),
    }


async def _mark_ended_if_no_connected_calls(session: AsyncSession, conf: ConferenceSession) -> None:
    if conf.status == "ended" or conf.status not in ACTIVE_BRIDGE_STATUSES:
        return
    call_sids = [sid for sid in (conf.lead_participant_sid, conf.seb_participant_sid, conf.carrier_participant_sid) if sid]
    if not call_sids:
        return

    active_call_statuses = {"queued", "ringing", "in-progress"}
    terminal_call_statuses = {"completed", "busy", "failed", "no-answer", "canceled"}

    if conf.conference_sid and str(conf.conference_sid).startswith("CF"):
        try:
            participants = await twilio_client.list_conference_participants(conf.conference_sid)
        except Exception as exc:
            logger.warning("Auto-end skipped; could not check conference participants for %s: %s", conf.id, exc)
            return
        if any((p.get("status") or "").lower() == "connected" for p in participants):
            return

    terminal_count = 0
    for call_sid in call_sids:
        try:
            call = await twilio_client.get_call(call_sid)
        except Exception as exc:
            logger.warning("Auto-end skipped; could not check call %s: %s", call_sid, exc)
            return
        status = (call.get("status") or "").lower()
        if status in active_call_statuses:
            return
        if status in terminal_call_statuses:
            terminal_count += 1
        else:
            logger.info("Auto-end skipped; call %s has inconclusive status %s", call_sid, status)
            return

    if terminal_count == len(call_sids):
        await _finish_session(session, conf, log_to_close=True)


async def _finish_session(session: AsyncSession, conf: ConferenceSession, *, log_to_close: bool) -> None:
    now = datetime.now(timezone.utc)
    conf.status = "ended"
    conf.ended_at = conf.ended_at or now
    if conf.started_at:
        conf.call_duration_seconds = int((conf.ended_at - conf.started_at).total_seconds())
    if log_to_close:
        logger.info(
            "Skipping Close note log for bridge %s; native Close call activities carry recordings",
            conf.id,
        )
    await session.commit()


def _seb_close_number() -> str:
    value = get_settings().twilio_seb_close_number
    if not value:
        raise ValueError("TWILIO_SEB_CLOSE_NUMBER is required for 3 Way Bridge Close callback")
    return normalize_e164(value)


def _safe_normalize(phone: str) -> str:
    try:
        return normalize_e164(phone)
    except Exception:
        return phone or ""
