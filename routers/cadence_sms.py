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

from config import get_settings
from services.telegram_alerts import send_telegram_alert
from services.sms_routing import resolve_sms_from_number

logger = logging.getLogger("falconconnect.cadence_sms")

router = APIRouter()

CLOSE_API_BASE = "https://api.close.com/api/v1"

# Close custom field IDs
CF_CADENCE_STAGE = "cf_vuP2rYRL0LA3OK0nCyZm9b19ki8ddokdTAapVnJ2Elb"

# SMS templates — Variant A (Aggressive Blitz)
SMS_TEMPLATES = {
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

# State → phone number mapping (Seb's ported numbers in Close)
# Built from Close phone_number API — 19 numbers across 9 states
STATE_PHONE_MAP = {
    "AZ": "+14809999040",
    "MT": "+14066463344",
    "NC": "+19808909888",   # NC 1 (primary)
    "ME": "+12078881046",   # ME 2 (primary)
    "KS": "+19133793347",
    "OR": "+19719993141",   # OR 1 (primary)
    "TX": "+18322429026",   # TX 1 (primary)
    "PA": "+12156077444",
    "FL": "+17862548006",   # FL 1 (primary)
    "CA": "+13502473286",   # California 1
}

# Toll-free fallback
TOLL_FREE = "+18446813690"


def _resolve_from_number(state: str) -> str:
    """Pick the outbound number for SMS based on lead's state.

    Falls back to toll-free if state not in map.
    """
    if not state:
        return TOLL_FREE
    return STATE_PHONE_MAP.get(state.upper().strip(), TOLL_FREE)


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


def _render_sms(template_key: str, first_name: str, state: str) -> Optional[str]:
    """Render an SMS template with lead data."""
    template = SMS_TEMPLATES.get(template_key)
    if not template:
        return None
    return template.format(first_name=first_name, state=state)


async def _send_close_sms(
    lead_id: str,
    contact_id: str,
    from_number: str,
    to_number: str,
    text: str,
) -> Optional[str]:
    """Send SMS via Close API. Returns SMS activity ID on success."""
    payload = {
        "lead_id": lead_id,
        "contact_id": contact_id,
        "local_phone": from_number,
        "remote_phone": to_number,
        "text": text,
        "status": "outbox",
        "direction": "outbound",
    }

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
                "Cadence SMS sent: %s → %s (template=%s, sms_id=%s)",
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


async def send_cadence_sms(
    lead_id: str,
    template_key: str,
    next_stage: str,
) -> dict:
    """Core SMS sending logic — shared by endpoint and standalone script.

    1. Fetch lead details from Close
    2. Resolve outbound number
    3. Render + send SMS
    4. Update cadence_stage

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

    # Render SMS text
    sms_text = _render_sms(template_key, info["first_name"], info["state"])
    if not sms_text:
        return {"status": "error", "reason": f"unknown template: {template_key}"}

    # Resolve outbound number via smart routing (history → area code → state fallback)
    from_number = await resolve_sms_from_number(lead_id, info["phone"])
    if not from_number:
        from_number = _resolve_from_number(info["state"])

    # Send SMS
    sms_id = await _send_close_sms(
        lead_id=lead_id,
        contact_id=info["contact_id"],
        from_number=from_number,
        to_number=info["phone"],
        text=sms_text,
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

    # Update cadence stage
    stage_updated = await _update_cadence_stage(lead_id, next_stage)

    return {
        "status": "ok",
        "lead_id": lead_id,
        "sms_id": sms_id,
        "template": template_key,
        "from_number": from_number,
        "to_number": info["phone"],
        "next_stage": next_stage,
        "stage_updated": stage_updated,
    }


@router.post("/send-sms")
async def close_send_sms(
    request: Request,
    template: str = Query(..., description="SMS template: sms1|sms2|sms3|sms4"),
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
    # Close webhooks nest data in event.data or at top level
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
    if template not in SMS_TEMPLATES:
        return {"status": "error", "reason": f"unknown template: {template}"}

    logger.info(
        "Cadence SMS webhook: lead=%s template=%s next_stage=%s",
        lead_id, template, next_stage,
    )

    # Send SMS and update stage
    result = await send_cadence_sms(lead_id, template, next_stage)
    return result
