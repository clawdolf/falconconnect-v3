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
from datetime import datetime, timezone as dt_tz
from typing import Optional

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from config import get_settings
from db.database import get_session
from db.models import CadenceSmsDispatch
from services.telegram_alerts import send_telegram_alert
from services.sms_routing import resolve_sms_from_number

logger = logging.getLogger("falconconnect.cadence_sms")

router = APIRouter()

CLOSE_API_BASE = "https://api.close.com/api/v1"

# Close custom field IDs
CF_CADENCE_STAGE = "cf_vuP2rYRL0LA3OK0nCyZm9b19ki8ddokdTAapVnJ2Elb"
CF_LENDER = "cf_SKsIYYQS3MoBBIxkVZKlUrxpvejOCqCIbiDBOePyJxI"

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
    """Extract first_name, state, address, and ALL phone numbers across all contacts.

    Returns all_phones as a list of {contact_id, phone} dicts so cadence
    SMS fires to every number on the lead. Label quality from mailer data
    is too inconsistent to filter by type; worst case is an undeliverable.
    """
    contacts = lead.get("contacts", [])

    # Name — from first contact that has one
    first_name = "there"
    for c in contacts:
        full_name = c.get("name", "").strip()
        if full_name:
            first_name = full_name.split()[0]
            break

    # All phones across all contacts, deduped by number
    seen: set[str] = set()
    all_phones: list[dict] = []
    for c in contacts:
        contact_id = c.get("id", "")
        for p in c.get("phones", []):
            num = p.get("phone", "").strip()
            if num and num not in seen:
                seen.add(num)
                all_phones.append({"contact_id": contact_id, "phone": num})

    # State + street address from lead
    addresses = lead.get("addresses", [])
    state = addresses[0].get("state", "") if addresses else ""
    address = ""
    if addresses:
        addr = addresses[0]
        line1 = addr.get("address_line_1", "").strip()
        line2 = addr.get("address_line_2", "").strip()
        parts = [p for p in [line1, line2] if p]
        address = ", ".join(parts)

    # Lender from custom fields
    custom = lead.get("custom", {})
    lender = custom.get(CF_LENDER, "") or ""

    return {
        "first_name": first_name,
        "state": state,
        "address": address,
        "lender": lender,
        "all_phones": all_phones,
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
    """Calculate next 9:00am in lead's local timezone, return as UTC ISO string.

    9am local time per state — west coast gets 9am PT, east coast 9am ET, etc.
    Falls back to America/Chicago when state is unknown.
    If it's currently before 9:00am in lead's tz → schedule for today 9:00am.
    If it's after 9:00am → schedule for tomorrow 9:00am.
    """
    from datetime import datetime, timezone as dt_tz
    from zoneinfo import ZoneInfo

    tz_name = _resolve_cadence_tz(state)
    tz = ZoneInfo(tz_name)
    now_local = datetime.now(tz)

    target = now_local.replace(hour=9, minute=0, second=0, microsecond=0)
    if target <= now_local:
        # Past 9:00am today → use tomorrow
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

    all_phones = info["all_phones"]
    if not all_phones:
        logger.warning("No phones on lead %s — skipping SMS", lead_id)
        return {"status": "skipped", "reason": "no phone numbers", "lead_id": lead_id}

    # Load template from DB (fallback to hardcoded)
    template_body = await _load_cadence_template(template_key)
    if not template_body:
        return {"status": "error", "reason": f"unknown template: {template_key}"}

    # Render SMS text
    sms_text = template_body.format(
        first_name=info["first_name"],
        state=info["state"],
        address=info["address"],
        lender=info["lender"],
    )

    # Calculate schedule time if not provided
    if date_scheduled_utc is None:
        date_scheduled_utc = _calc_next_morning_utc(info["state"])

    # Send to every phone number on the lead — labels are unreliable from
    # mailer data, worst case is an undeliverable on a landline
    sms_ids: list[str] = []
    failed: list[str] = []
    for entry in all_phones:
        contact_id = entry["contact_id"]
        to_number = entry["phone"]

        from_number = await resolve_sms_from_number(lead_id, to_number, routing_mode="cadence")
        if not from_number:
            logger.warning("No from_number for lead=%s phone=%s — skipping", lead_id, to_number)
            failed.append(to_number)
            continue

        sms_id = await _send_close_sms(
            lead_id=lead_id,
            contact_id=contact_id,
            from_number=from_number,
            to_number=to_number,
            text=sms_text,
            date_scheduled_utc=date_scheduled_utc,
        )

        if sms_id:
            sms_ids.append(sms_id)
        else:
            failed.append(to_number)

    if not sms_ids:
        await send_telegram_alert(
            f"<b>Cadence SMS FAILED (all numbers)</b>\n"
            f"Lead: {lead_id}\n"
            f"Template: {template_key}\n"
            f"Attempted: {[e['phone'] for e in all_phones]}",
        )
        return {"status": "error", "reason": "all SMS sends failed", "lead_id": lead_id}

    # Update cadence stage only after at least one SMS succeeded
    stage_updated = False
    if next_stage:
        stage_updated = await _update_cadence_stage(lead_id, next_stage)

    return {
        "status": "ok",
        "lead_id": lead_id,
        "sms_ids": sms_ids,
        "failed_numbers": failed,
        "template": template_key,
        "sent_to": [e["phone"] for e in all_phones],
        "scheduled_utc": date_scheduled_utc,
        "next_stage": next_stage,
        "stage_updated": stage_updated,
    }


@router.post("/send-sms")
async def close_send_sms(
    request: Request,
    template: str = Query(..., description="SMS template: sms1|sms2|sms3|sms4|r1_done|r2_done|r3_done"),
    next_stage: str = Query(..., description="Cadence stage to set after SMS"),
    session: AsyncSession = Depends(get_session),
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

    # Idempotency: insert-first dedup keyed on (lead_id, template, UTC date).
    # Close webhooks deliver at-least-once; without this, retries duplicate SMS.
    today_utc = datetime.now(dt_tz.utc).date().isoformat()
    dedup_key = f"{lead_id}:{template}:{today_utc}"
    dispatch = CadenceSmsDispatch(
        dedup_key=dedup_key,
        lead_id=lead_id,
        template_key=template,
        scheduled_date=today_utc,
    )
    session.add(dispatch)
    try:
        await session.commit()
    except IntegrityError:
        await session.rollback()
        logger.info(
            "Duplicate cadence SMS suppressed: lead=%s template=%s date=%s",
            lead_id, template, today_utc,
        )
        return {
            "status": "duplicate_suppressed",
            "lead_id": lead_id,
            "template": template,
            "dedup_key": dedup_key,
        }

    # We own the lock — proceed with the actual send
    result = await send_cadence_sms(lead_id, template, next_stage)

    # Stamp the SMS IDs onto the dispatch row for audit
    sent_ids = result.get("sms_ids") or []
    if sent_ids:
        dispatch.sms_ids = ",".join(sent_ids)
        await session.commit()

    return result
