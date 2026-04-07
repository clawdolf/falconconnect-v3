"""Close workflow SMS trigger — sends cadence SMS and advances stage.

Endpoint: POST /api/close/send-sms

Flow:
1. Close workflow fires webhook when cadence_stage changes to a *-done stage
2. This endpoint receives the webhook, validates CLOSE_WEBHOOK_SECRET
3. Fetches lead details from Close (contact phone, name, state)
4. Resolves outbound number via smart routing (call history → area code → state map)
5. Sends the appropriate SMS template via Close SMS API
6. Updates cadence_stage to the next value
7. Returns 200

Query params:
  template: sms1|sms2|sms3|sms4
  next_stage: the cadence_stage to set after SMS fires

Auth: Close webhook HMAC-SHA256 signature (close-sig-hash / close-sig-timestamp).
"""

import hashlib
import hmac
import json
import logging
from typing import Optional

import httpx
from fastapi import APIRouter, HTTPException, Query, Request, status
from sqlalchemy import select

from config import get_settings
from services.telegram_alerts import send_telegram_alert
from services.sms_routing import resolve_sms_from_number

logger = logging.getLogger("falconconnect.cadence_sms")

router = APIRouter()

CLOSE_API_BASE = "https://api.close.com/api/v1"

# Close custom field IDs
CF_CADENCE_STAGE = "cf_vuP2rYRL0LA3OK0nCyZm9b19ki8ddokdTAapVnJ2Elb"

# SMS templates — Variant A (Aggressive Blitz) — fallback defaults if DB empty
SMS_TEMPLATES_DEFAULT = {
    "r1_done": (
        "Hey {first_name}, tried reaching you yesterday"
        " — easier to connect by text? Just takes a couple"
        " minutes to see what coverage looks like for you."
    ),
    "r2_done": (
        "Most homeowners in {state} don't realize their mortgage"
        " has zero protection if something happens. Took 2 min"
        " to fix that for a family last week."
    ),
    "r3_done": (
        "Hey {first_name}, still happy to walk you through what"
        " mortgage protection would look like for your home."
        " Quick call, no pressure. -Seb"
    ),
    # Legacy keys kept for backward-compat with Close workflow endpoints
    "sms1": (
        "Hey {first_name}, tried reaching you yesterday"
        " — easier to connect by text? Just takes a couple"
        " minutes to see what coverage looks like for you."
    ),
    "sms2": (
        "Most homeowners in {state} don't realize their mortgage"
        " has zero protection if something happens. Took 2 min"
        " to fix that for a family last week."
    ),
    "sms3": (
        "Hey {first_name}, still happy to walk you through what"
        " mortgage protection would look like for your home."
        " Quick call, no pressure. -Seb"
    ),
    "sms4": (
        "Last one from me"
        " — if the timing's ever right, I'm here. -Seb"
    ),
}


async def _load_cadence_template(template_key: str) -> str:
    """Load a cadence SMS template from DB. Falls back to hardcoded default."""
    try:
        from db.database import _get_session_factory
        from db.models import SmsTemplate

        async with _get_session_factory()() as session:
            result = await session.execute(
                select(SmsTemplate).where(SmsTemplate.template_key == template_key)
            )
            tpl = result.scalar_one_or_none()
            if tpl:
                return tpl.body
    except Exception as exc:
        logger.warning(
            "Failed to load cadence SMS template '%s' from DB: %s", template_key, exc
        )
    return SMS_TEMPLATES_DEFAULT.get(template_key, "")


# State → timezone mapping (only licensed states)
STATE_TZ_MAP = {
    "AZ": "America/Phoenix",
    "FL": "America/New_York",
    "ID": "America/Boise",
    "KS": "America/Chicago",
    "ME": "America/New_York",
    "MT": "America/Denver",
    "NC": "America/New_York",
    "OH": "America/New_York",
    "OR": "America/Los_Angeles",
    "PA": "America/New_York",
    "TX": "America/Chicago",
}


def _resolve_cadence_tz(state: str) -> str:
    """Return tz name for state, defaulting to America/Chicago."""
    return STATE_TZ_MAP.get(state.upper().strip() if state else "", "America/Chicago")


def _close_auth() -> tuple:
    """Return (api_key, '') for httpx basic auth."""
    settings = get_settings()
    if not settings.close_api_key:
        raise RuntimeError("CLOSE_API_KEY not configured")
    return (settings.close_api_key, "")


def _verify_close_signature(
    raw_body: bytes,
    sig_hash: Optional[str],
    sig_timestamp: Optional[str],
    signature_key: str,
) -> bool:
    """Verify Close.com webhook HMAC-SHA256 signature."""
    if not sig_hash or not sig_timestamp or not signature_key:
        return False
    try:
        data = sig_timestamp + raw_body.decode("utf-8")
        expected = hmac.new(
            bytearray.fromhex(signature_key),
            data.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
        return hmac.compare_digest(expected, sig_hash)
    except (ValueError, UnicodeDecodeError) as exc:
        logger.warning("Signature verification error: %s", exc)
        return False


async def _get_lead_details(lead_id: str) -> Optional[dict]:
    """Fetch lead with contacts and custom fields from Close."""
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.get(
                f"{CLOSE_API_BASE}/lead/{lead_id}/",
                auth=_close_auth(),
            )
            resp.raise_for_status()
            return resp.json()
    except Exception as exc:
        logger.error("Failed to fetch lead %s: %s", lead_id, exc)
        return None


def _extract_lead_info(lead: dict) -> dict:
    """Extract first_name, phone, state, contact_id from a Close lead."""
    contacts = lead.get("contacts", [])
    contact = contacts[0] if contacts else {}
    contact_id = contact.get("id", "")

    # Name
    full_name = contact.get("name", lead.get("display_name", ""))
    first_name = full_name.strip().split()[0] if full_name else "there"

    # Phone
    phones = contact.get("phones", [])
    phone = phones[0].get("phone", "") if phones else ""

    # State — from address
    addresses = lead.get("addresses", [])
    state = ""
    if addresses:
        state = addresses[0].get("state", "")

    return {
        "contact_id": contact_id,
        "first_name": first_name,
        "phone": phone,
        "state": state,
    }


async def _send_close_sms(
    lead_id: str,
    contact_id: str,
    from_number: str,
    to_number: str,
    text: str,
    date_scheduled_utc: Optional[str] = None,
) -> Optional[str]:
    """Send or schedule SMS via Close API. Returns SMS activity ID on success."""
    payload = {
        "lead_id": lead_id,
        "contact_id": contact_id,
        "local_phone": from_number,
        "remote_phone": to_number,
        "text": text,
        "direction": "outbound",
    }

    if date_scheduled_utc:
        payload["status"] = "scheduled"
        payload["date_scheduled"] = date_scheduled_utc
    else:
        payload["status"] = "outbox"

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                f"{CLOSE_API_BASE}/activity/sms/",
                json=payload,
                auth=_close_auth(),
            )
            resp.raise_for_status()
            sms_data = resp.json()
            sms_id = sms_data.get("id", "")
            logger.info(
                "Cadence SMS %s: %s → %s (template text=%s, sms_id=%s)",
                "scheduled" if date_scheduled_utc else "queued",
                from_number, to_number, text[:40], sms_id,
            )
            return sms_id
    except httpx.HTTPStatusError as exc:
        logger.error(
            "Close SMS API error %s: %s",
            exc.response.status_code, exc.response.text[:500],
        )
    except Exception as exc:
        logger.error("Close SMS send failed: %s", exc)

    return None


async def _update_cadence_stage(lead_id: str, stage: str) -> bool:
    """Update cadence_stage custom field on a Close lead."""
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.put(
                f"{CLOSE_API_BASE}/lead/{lead_id}/",
                json={f"custom.{CF_CADENCE_STAGE}": stage},
                auth=_close_auth(),
            )
            resp.raise_for_status()
            logger.info("Cadence stage updated: lead=%s stage=%s", lead_id, stage)
            return True
    except Exception as exc:
        logger.error("cadence_stage update failed for %s: %s", lead_id, exc)
        return False


def _calc_next_morning_utc(state: str) -> str:
    """Calculate next 8:30am in lead's local timezone, return as UTC ISO string.

    If it's currently before 8:30am in lead's tz → schedule for today 8:30am.
    If it's after 8:30am → schedule for tomorrow 8:30am.
    """
    from datetime import datetime, timezone as dt_tz
    from zoneinfo import ZoneInfo

    tz_name = _resolve_cadence_tz(state)
    tz = ZoneInfo(tz_name)
    now_local = datetime.now(tz)

    target = now_local.replace(hour=8, minute=30, second=0, microsecond=0)
    if target <= now_local:
        # Past 8:30am today → use tomorrow
        from datetime import timedelta
        target = target + timedelta(days=1)

    # Convert to UTC
    target_utc = target.astimezone(dt_tz.utc)
    return target_utc.isoformat()


async def send_cadence_sms(
    lead_id: str,
    template_key: str,
    next_stage: str,
    date_scheduled_utc: Optional[str] = None,
) -> dict:
    """Core SMS sending logic — shared by endpoint and webhook handler.

    1. Fetch lead details from Close
    2. Load template from DB (fallback to hardcoded)
    3. Resolve outbound number
    4. Render + send/schedule SMS
    5. Update cadence_stage (only if next_stage is provided and non-empty)

    Returns result dict with status and details.
    """
    # Fetch lead
    lead = await _get_lead_details(lead_id)
    if not lead:
        return {"status": "error", "reason": f"lead {lead_id} not found"}

    info = _extract_lead_info(lead)

    if not info["phone"]:
        logger.warning("No phone on lead %s — skipping SMS", lead_id)
        return {"status": "skipped", "reason": "no phone number", "lead_id": lead_id}

    if not info["contact_id"]:
        logger.warning("No contact on lead %s — skipping SMS", lead_id)
        return {"status": "skipped", "reason": "no contact", "lead_id": lead_id}

    # Load template from DB (fallback to hardcoded)
    template_body = await _load_cadence_template(template_key)
    if not template_body:
        return {"status": "error", "reason": f"unknown template: {template_key}"}

    # Render SMS text
    sms_text = template_body.format(
        first_name=info["first_name"],
        state=info["state"],
    )

    # Resolve outbound number via smart routing (history → area code → state fallback)
    from_number = await resolve_sms_from_number(lead_id, info["phone"], routing_mode="cadence")
    if not from_number:
        logger.warning("No from_number resolved for cadence SMS lead=%s", lead_id)
        return {"status": "error", "reason": "no from_number resolved", "lead_id": lead_id}

    # Calculate schedule time if not provided
    if date_scheduled_utc is None:
        date_scheduled_utc = _calc_next_morning_utc(info["state"])

    # Send/schedule SMS
    sms_id = await _send_close_sms(
        lead_id=lead_id,
        contact_id=info["contact_id"],
        from_number=from_number,
        to_number=info["phone"],
        text=sms_text,
        date_scheduled_utc=date_scheduled_utc,
    )

    if not sms_id:
        await send_telegram_alert(
            f"<b>Cadence SMS FAILED</b>\n"
            f"Lead: {lead_id}\n"
            f"Template: {template_key}\n"
            f"Phone: {info['phone']}\n"
            f"From: {from_number}",
        )
        return {"status": "error", "reason": "SMS send failed", "lead_id": lead_id}

    # Update cadence stage (only if next_stage provided)
    stage_updated = False
    if next_stage:
        stage_updated = await _update_cadence_stage(lead_id, next_stage)

    return {
        "status": "ok",
        "lead_id": lead_id,
        "sms_id": sms_id,
        "template": template_key,
        "from_number": from_number,
        "to_number": info["phone"],
        "scheduled_utc": date_scheduled_utc,
        "next_stage": next_stage,
        "stage_updated": stage_updated,
    }


@router.post("/send-sms")
async def close_send_sms(
    request: Request,
    template: str = Query(..., description="SMS template: sms1|sms2|sms3|sms4|r1_done|r2_done|r3_done"),
    next_stage: str = Query(..., description="Cadence stage to set after SMS"),
):
    """Receive webhook from Close workflow and send cadence SMS.

    Webhook URL: https://falconnect.org/api/close/send-sms?template=sms1&next_stage=r2-to-call

    Validates Close webhook signature, extracts lead_id from payload,
    sends the specified SMS template, and updates cadence_stage.
    """
    settings = get_settings()

    # Read raw body for signature verification
    raw_body = await request.body()

    # Verify Close webhook signature
    sig_hash = request.headers.get("close-sig-hash")
    sig_timestamp = request.headers.get("close-sig-timestamp")

    if settings.close_webhook_secret:
        if not _verify_close_signature(
            raw_body, sig_hash, sig_timestamp, settings.close_webhook_secret,
        ):
            logger.error(
                "Cadence SMS webhook signature verification FAILED"
            )
            return {"status": "error", "reason": "signature_verification_failed"}
    else:
        logger.warning(
            "CLOSE_WEBHOOK_SECRET not set — skipping signature verification"
        )

    # Parse payload
    try:
        payload = json.loads(raw_body)
    except json.JSONDecodeError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid JSON body",
        )

    # Extract lead_id from Close webhook payload
    event = payload.get("event", payload)
    event_data = event.get("data", event)
    lead_id = (
        event.get("lead_id", "")
        or event_data.get("lead_id", "")
        or payload.get("lead_id", "")
    )

    if not lead_id:
        logger.error("No lead_id in cadence SMS webhook payload")
        return {"status": "error", "reason": "no lead_id"}

    # Validate template
    all_valid_keys = set(SMS_TEMPLATES_DEFAULT.keys())
    if template not in all_valid_keys:
        return {"status": "error", "reason": f"unknown template: {template}"}

    logger.info(
        "Cadence SMS webhook: lead=%s template=%s next_stage=%s",
        lead_id, template, next_stage,
    )

    # Send SMS and update stage
    result = await send_cadence_sms(lead_id, template, next_stage)
    return result
