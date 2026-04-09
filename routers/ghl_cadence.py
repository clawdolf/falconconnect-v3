"""GHL → Close cadence webhook — receives r0-complete tag from GHL, creates/updates lead in Close.

Endpoint: POST /api/ghl/rvm-complete

Flow:
1. GHL fires webhook when contact tag changes to "r0-complete"
2. Extracts contact data (name, phone, custom fields) from GHL payload
3. Checks if lead already exists in Close by phone number
4. If new: creates lead in Close with cadence_stage=2. r1-calling + GHL contact ID
5. If existing: updates cadence_stage to 2. r1-calling
6. Logs every action to sync_log table
7. Returns 200 on success

Auth: X-GHL-Webhook-Secret header (same as existing GHL webhook pattern).
"""

import json
import logging
from typing import Optional

import httpx
from fastapi import APIRouter, Depends, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from config import get_settings
from db.database import get_session
from db.models import SyncLog, LeadXref
from services.close import normalize_phone
from services.telegram_alerts import send_telegram_alert
from utils.auth import verify_webhook_secret

logger = logging.getLogger("falconconnect.ghl_cadence")

router = APIRouter()

CLOSE_API_BASE = "https://api.close.com/api/v1"

# Close custom field IDs for cadence
CF_CADENCE_STAGE = "cf_vuP2rYRL0LA3OK0nCyZm9b19ki8ddokdTAapVnJ2Elb"
CF_GHL_ID = "cf_XWisbKrkWGeMvGYTMGMZVoWjYvFlcXmOkgILiXyDcMM"

# Default Close lead status for new cadence leads
DEFAULT_STATUS_ID = "stat_FncoFJQfuuXdXbNx0HbwsKVR7EA95OhoQmqEPNMXl7T"  # "New Lead"


def _close_auth() -> tuple:
    """Return (api_key, '') for httpx basic auth."""
    settings = get_settings()
    if not settings.close_api_key:
        raise RuntimeError("CLOSE_API_KEY not configured")
    return (settings.close_api_key, "")


async def _search_close_by_ghl_id(ghl_contact_id: str) -> Optional[dict]:
    """Search Close for an existing lead by GHL contact ID stored in custom field.

    This is the most reliable fallback when LeadXref has no row — the GHL contact ID
    is written to CF_GHL_ID custom field on every import via STEP 3b.
    """
    if not ghl_contact_id:
        return None

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.get(
                f"{CLOSE_API_BASE}/lead/",
                params={
                    "query": ghl_contact_id,
                    "_fields": "id,display_name",
                    "_limit": 1,
                },
                auth=_close_auth(),
            )
            resp.raise_for_status()
            data = resp.json().get("data", [])
            if data:
                logger.info("Close GHL-ID search hit for %s: %s", ghl_contact_id, data[0].get("id"))
                return data[0]
    except Exception as exc:
        logger.error("Close GHL-ID search failed for %s: %s", ghl_contact_id, exc)

    return None


async def _search_close_by_phone(phone: str) -> Optional[dict]:
    """Search Close for an existing lead by phone number.

    Uses Close's search API with the correct phone_number mode.
    Returns the first matching lead dict, or None.
    """
    if not phone:
        return None

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                f"{CLOSE_API_BASE}/data/search/",
                json={
                    "query": {
                        "type": "and",
                        "queries": [
                            {
                                "type": "object_type",
                                "object_type": "lead",
                            },
                            {
                                "type": "has_related",
                                "related_object_type": "contact",
                                "related_query": {
                                    "type": "and",
                                    "queries": [
                                        {
                                            "type": "field_condition",
                                            "field": {
                                                "type": "regular_field",
                                                "object_type": "contact",
                                                "field_name": "phone",
                                            },
                                            "condition": {
                                                "type": "text",
                                                "mode": "phone_number",
                                                "value": phone,
                                            },
                                        }
                                    ],
                                },
                            },
                        ],
                    },
                    "_fields": {
                        "lead": ["id", "display_name"],
                    },
                    "_limit": 1,
                },
                auth=_close_auth(),
            )
            resp.raise_for_status()
            data = resp.json().get("data", [])
            if data:
                return data[0]
    except Exception as exc:
        logger.error("Close phone search failed for %s: %s", phone, exc)

    return None


async def _create_close_lead(
    name: str,
    phone: str,
    ghl_contact_id: str,
    email: Optional[str] = None,
) -> Optional[str]:
    """Create a new lead in Close with cadence_stage=2. r1-calling.

    Returns the lead ID on success, None on failure.
    """
    contacts = [{"name": name}]
    if phone:
        contacts[0]["phones"] = [{"phone": phone, "type": "mobile"}]
    if email:
        contacts[0]["emails"] = [{"email": email, "type": "office"}]

    payload = {
        "name": name,
        "status_id": DEFAULT_STATUS_ID,
        "contacts": contacts,
        f"custom.{CF_CADENCE_STAGE}": "2. r1-calling",
        f"custom.{CF_GHL_ID}": ghl_contact_id,
    }

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                f"{CLOSE_API_BASE}/lead/",
                json=payload,
                auth=_close_auth(),
            )
            resp.raise_for_status()
            lead_data = resp.json()
            lead_id = lead_data.get("id", "")
            logger.info(
                "Created Close lead %s for GHL contact %s (%s)",
                lead_id, ghl_contact_id, name,
            )
            return lead_id
    except httpx.HTTPStatusError as exc:
        logger.error(
            "Close lead creation failed: %s — %s",
            exc.response.status_code, exc.response.text[:500],
        )
    except Exception as exc:
        logger.error("Close lead creation failed: %s", exc)

    return None


async def _add_close_note(lead_id: str, note: str) -> None:
    """Add a text note to a Close lead."""
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                f"{CLOSE_API_BASE}/activity/note/",
                json={"lead_id": lead_id, "note": note},
                auth=_close_auth(),
            )
            resp.raise_for_status()
    except Exception as exc:
        logger.warning("Close note creation failed for %s: %s", lead_id, exc)


async def _update_cadence_stage(lead_id: str, stage: str) -> bool:
    """Update the cadence_stage custom field on an existing Close lead.

    Returns True on success, False on failure.
    """
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.put(
                f"{CLOSE_API_BASE}/lead/{lead_id}/",
                json={f"custom.{CF_CADENCE_STAGE}": stage},
                auth=_close_auth(),
            )
            resp.raise_for_status()
            logger.info("Updated cadence_stage=%s on lead %s", stage, lead_id)
            return True
    except Exception as exc:
        logger.error("cadence_stage update failed for lead %s: %s", lead_id, exc)
        return False


def _extract_ghl_contact_data(payload: dict) -> dict:
    """Extract contact info from a GHL webhook payload.

    GHL workflow webhooks (tag-change, automation triggers) send data like:
        {
          "type": "ContactTagUpdate",
          "customData": {"contactID": "abc123", "phone": "(480) 555-1234"},
          "workflow": {...},
          "triggerData": {}
        }

    Direct contact webhooks nest data under payload["contact"]["id"].

    Priority order for contact ID:
      1. customData.contactID  — GHL workflow/automation webhook (confirmed from logs)
      2. customData.contactId  — alternate casing
      3. payload.contactId     — direct contact webhook
      4. payload.contact_id    — snake_case variant
      5. payload.contact.id    — nested contact object
      NOTE: payload.id is the workflow EVENT id, never use it as contact id.
    """
    custom_data = payload.get("customData") or {}

    # Contact ID — priority order matters, do NOT put payload["id"] here
    contact_id = (
        custom_data.get("contactID", "")
        or custom_data.get("contactId", "")
        or payload.get("contactId", "")
        or payload.get("contact_id", "")
        or (payload.get("contact") or {}).get("id", "")
    )

    # Contact fields — check nested contact object, then top-level
    contact = payload.get("contact") or {}
    first_name = (
        contact.get("firstName", "")
        or contact.get("first_name", "")
        or payload.get("firstName", "")
        or payload.get("first_name", "")
    )
    last_name = (
        contact.get("lastName", "")
        or contact.get("last_name", "")
        or payload.get("lastName", "")
        or payload.get("last_name", "")
    )
    # GHL workflow webhooks send phone in customData, not top-level
    raw_phone = (
        custom_data.get("phone", "")
        or contact.get("phone", "")
        or payload.get("phone", "")
    )
    phone = normalize_phone(raw_phone)
    email = contact.get("email", "") or payload.get("email", "")
    full_name = f"{first_name} {last_name}".strip() or "Unknown"

    return {
        "name": full_name,
        "first_name": first_name,
        "last_name": last_name,
        "phone": phone,
        "email": email,
        "ghl_contact_id": contact_id,
    }


async def _log_sync(
    session: AsyncSession,
    event_type: str,
    source_id: str = "",
    target_id: str = "",
    status: str = "ok",
    error_detail: str = None,
    payload: dict = None,
):
    """Write a sync_log entry (reuses existing FC pattern)."""
    log = SyncLog(
        event_type=event_type,
        direction="ghl_to_close",
        source_id=source_id,
        target_id=target_id,
        payload=json.dumps(payload, default=str) if payload else None,
        status=status,
        error_detail=error_detail,
    )
    session.add(log)


@router.post("/rvm-complete")
async def ghl_rvm_complete(
    request: Request,
    _secret: str = Depends(verify_webhook_secret),
    session: AsyncSession = Depends(get_session),
):
    """Receive GHL webhook when contact tag changes to r0-complete.

    Creates or updates the lead in Close with cadence_stage=2. r1-calling.

    Webhook URL: https://falconnect.org/api/ghl/rvm-complete
    Auth: X-GHL-Webhook-Secret header
    """
    raw_body = await request.json()

    # Extract contact data from GHL payload
    contact_data = _extract_ghl_contact_data(raw_body)
    ghl_contact_id = contact_data["ghl_contact_id"]
    phone = contact_data["phone"]
    name = contact_data["name"]

    logger.info(
        "GHL r0-complete webhook: contact=%s name=%s phone=%s",
        ghl_contact_id, name, phone,
    )

    if not ghl_contact_id:
        logger.warning("No GHL contact ID in webhook payload — skipping")
        await _log_sync(
            session,
            event_type="ghl.rvm_complete",
            status="skipped",
            error_detail="no GHL contact ID in payload",
            payload=raw_body,
        )
        return {"status": "skipped", "reason": "no contact ID"}

    # Look up Close lead via LeadXref (GHL contact ID → Close lead ID)
    # Phone is only required for the fallback phone search, not for xref lookup.
    existing_lead = None
    if ghl_contact_id:
        try:
            xref_result = await session.execute(
                select(LeadXref).where(LeadXref.ghl_contact_id == ghl_contact_id)
            )
            xref = xref_result.scalar_one_or_none()
            if xref and xref.close_lead_id:
                existing_lead = {"id": xref.close_lead_id}
                logger.info("LeadXref hit: GHL %s → Close %s", ghl_contact_id, xref.close_lead_id)
        except Exception as xref_exc:
            logger.warning("LeadXref lookup failed for %s: %s", ghl_contact_id, xref_exc)

    if not existing_lead:
        logger.info("LeadXref miss for GHL %s — searching Close by GHL contact ID", ghl_contact_id)
        existing_lead = await _search_close_by_ghl_id(ghl_contact_id)

    if not existing_lead and phone:
        logger.info("GHL-ID search miss for %s — falling back to phone search", ghl_contact_id)
        existing_lead = await _search_close_by_phone(phone)

    if existing_lead:
        lead_id = existing_lead.get("id", "")
        logger.info(
            "Lead already exists in Close: %s — updating cadence_stage to 2. r1-calling",
            lead_id,
        )
        updated = await _update_cadence_stage(lead_id, "2. r1-calling")
        await _add_close_note(lead_id, "RVM + SMS Drop Completed")
        await _log_sync(
            session,
            event_type="ghl.rvm_complete",
            source_id=ghl_contact_id,
            target_id=lead_id,
            status="ok" if updated else "error",
            error_detail=None if updated else "cadence_stage update failed",
            payload=raw_body,
        )
        return {
            "status": "ok",
            "action": "updated",
            "lead_id": lead_id,
            "cadence_stage": "2. r1-calling",
        }

    # Create new lead in Close
    lead_id = await _create_close_lead(
        name=name,
        phone=phone,
        ghl_contact_id=ghl_contact_id,
        email=contact_data.get("email"),
    )

    if lead_id:
        await _log_sync(
            session,
            event_type="ghl.rvm_complete",
            source_id=ghl_contact_id,
            target_id=lead_id,
            status="ok",
            payload=raw_body,
        )

        # Telegram notification for new cadence lead
        await send_telegram_alert(
            f"<b>New Cadence Lead</b>\n"
            f"Name: {name}\n"
            f"Phone: {phone}\n"
            f"GHL ID: {ghl_contact_id}\n"
            f"Close Lead: {lead_id}\n"
            f"Stage: 2. r1-calling",
        )

        return {
            "status": "ok",
            "action": "created",
            "lead_id": lead_id,
            "cadence_stage": "2. r1-calling",
        }

    # Creation failed
    await _log_sync(
        session,
        event_type="ghl.rvm_complete",
        source_id=ghl_contact_id,
        status="error",
        error_detail="Close lead creation failed",
        payload=raw_body,
    )

    await send_telegram_alert(
        f"<b>Cadence Lead Creation FAILED</b>\n"
        f"Name: {name}\n"
        f"Phone: {phone}\n"
        f"GHL ID: {ghl_contact_id}\n\n"
        f"Check Close API key and field configuration.",
    )

    return {"status": "error", "reason": "lead creation failed"}


# --- GHL Contact Declined Handler ---

# Keywords that indicate a contact is declining further outreach
DECLINE_KEYWORDS = [
    "not interested",
    "stop",
    "don't want",
    "do not want",
    "no thanks",
    "no thank you",
    "unsubscribe",
    "remove me",
    "take me off",
    "wrong number",
    "leave me alone",
]


def _is_decline_response(message: str) -> bool:
    """Check if an inbound SMS message is a decline/opt-out response.

    Matches on common decline phrases. Case-insensitive.
    Short messages (< 50 chars) are more likely to be direct responses.
    """
    if not message:
        return False
    msg_lower = message.lower().strip()
    return any(kw in msg_lower for kw in DECLINE_KEYWORDS)


async def _remove_contact_from_ghl_sequences(ghl_contact_id: str) -> bool:
    """Remove a GHL contact from all active workflows/sequences.

    Uses the GHL API to remove the contact from workflows,
    which effectively stops any pending RVM, SMS, or call actions.
    """
    settings = get_settings()
    if not settings.ghl_api_key or not ghl_contact_id:
        return False

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            # Remove contact from all workflows
            resp = await client.delete(
                f"https://services.leadconnectorhq.com/contacts/{ghl_contact_id}/workflow/",
                headers={
                    "Authorization": f"Bearer {settings.ghl_api_key}",
                    "Version": "2021-07-28",
                },
            )
            if resp.status_code in (200, 204):
                logger.info("Removed GHL contact %s from all workflows", ghl_contact_id)
                return True
            else:
                logger.warning(
                    "GHL workflow removal returned %s for contact %s: %s",
                    resp.status_code, ghl_contact_id, resp.text[:300],
                )
    except Exception as exc:
        logger.error("Failed to remove GHL contact %s from workflows: %s", ghl_contact_id, exc)

    return False


async def _tag_ghl_contact(ghl_contact_id: str, tag: str) -> bool:
    """Add a tag to a GHL contact (e.g. 'Declined - Post RVM')."""
    settings = get_settings()
    if not settings.ghl_api_key or not ghl_contact_id:
        return False

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                f"https://services.leadconnectorhq.com/contacts/{ghl_contact_id}/tags",
                headers={
                    "Authorization": f"Bearer {settings.ghl_api_key}",
                    "Version": "2021-07-28",
                    "Content-Type": "application/json",
                },
                json={"tags": [tag]},
            )
            if resp.status_code in (200, 201, 204):
                logger.info("Tagged GHL contact %s with '%s'", ghl_contact_id, tag)
                return True
            else:
                logger.warning(
                    "GHL tag add returned %s for contact %s: %s",
                    resp.status_code, ghl_contact_id, resp.text[:300],
                )
    except Exception as exc:
        logger.error("Failed to tag GHL contact %s: %s", ghl_contact_id, exc)

    return False


@router.post("/contact-declined")
async def ghl_contact_declined(
    request: Request,
    _secret: str = Depends(verify_webhook_secret),
    session: AsyncSession = Depends(get_session),
):
    """Receive GHL webhook when a contact replies with a decline message.

    Triggered by GHL workflow: Inbound SMS → keyword match → webhook.
    Webhook URL: https://falconnect.org/api/ghl/contact-declined
    Auth: X-GHL-Webhook-Secret header

    Flow:
    1. Extract contact ID and message from GHL payload
    2. Verify the message is a decline (double-check keywords)
    3. Look up Close lead via LeadXref → GHL ID → phone fallback
    4. Update cadence_stage to "0. declined" in Close
    5. Add a note to the Close lead with the decline message
    6. Tag contact in GHL as "Declined - Post RVM"
    7. Remove contact from all GHL workflows/sequences
    8. Log to sync_log
    """
    raw_body = await request.json()

    # Extract contact data
    contact_data = _extract_ghl_contact_data(raw_body)
    ghl_contact_id = contact_data["ghl_contact_id"]
    phone = contact_data["phone"]
    name = contact_data["name"]

    # Extract the inbound message text from various payload shapes
    message = (
        raw_body.get("message", "")
        or raw_body.get("text", "")
        or raw_body.get("body", "")
        or (raw_body.get("customData") or {}).get("message", "")
        or (raw_body.get("customData") or {}).get("text", "")
    )

    logger.info(
        "GHL contact-declined webhook: contact=%s name=%s phone=%s message=%r",
        ghl_contact_id, name, phone, message,
    )

    if not ghl_contact_id:
        logger.warning("No GHL contact ID in webhook payload — skipping")
        await _log_sync(
            session,
            event_type="ghl.contact_declined",
            status="skipped",
            error_detail="no GHL contact ID in payload",
            payload=raw_body,
        )
        return {"status": "skipped", "reason": "no contact ID"}

    # Double-check the message is actually a decline
    if message and not _is_decline_response(message):
        logger.info(
            "Message %r does not match decline keywords — skipping", message[:100]
        )
        await _log_sync(
            session,
            event_type="ghl.contact_declined",
            source_id=ghl_contact_id,
            status="skipped",
            error_detail=f"message did not match decline keywords: {message[:200]}",
            payload=raw_body,
        )
        return {"status": "skipped", "reason": "not a decline message"}

    # Look up Close lead
    existing_lead = None
    if ghl_contact_id:
        try:
            xref_result = await session.execute(
                select(LeadXref).where(LeadXref.ghl_contact_id == ghl_contact_id)
            )
            xref = xref_result.scalar_one_or_none()
            if xref and xref.close_lead_id:
                existing_lead = {"id": xref.close_lead_id}
                logger.info(
                    "LeadXref hit: GHL %s → Close %s", ghl_contact_id, xref.close_lead_id
                )
        except Exception as xref_exc:
            logger.warning("LeadXref lookup failed for %s: %s", ghl_contact_id, xref_exc)

    if not existing_lead:
        existing_lead = await _search_close_by_ghl_id(ghl_contact_id)

    if not existing_lead and phone:
        existing_lead = await _search_close_by_phone(phone)

    lead_id = existing_lead.get("id", "") if existing_lead else ""

    # Update Close lead if found
    if lead_id:
        # Set cadence_stage to "0. declined"
        stage_updated = await _update_cadence_stage(lead_id, "0. declined")

        # Add decline note with the message text
        note_text = f"Contact declined (SMS reply)"
        if message:
            note_text += f': "{message}"'
        await _add_close_note(lead_id, note_text)

        logger.info(
            "Close lead %s marked as declined (stage=%s, note added)",
            lead_id, "0. declined" if stage_updated else "update failed",
        )
    else:
        logger.warning(
            "No Close lead found for GHL contact %s — skipping Close update", ghl_contact_id
        )

    # Tag and remove from GHL sequences (do this even if Close update fails)
    ghl_tagged = await _tag_ghl_contact(ghl_contact_id, "Declined - Post RVM")
    ghl_removed = await _remove_contact_from_ghl_sequences(ghl_contact_id)

    # Log the sync
    await _log_sync(
        session,
        event_type="ghl.contact_declined",
        source_id=ghl_contact_id,
        target_id=lead_id,
        status="ok" if (lead_id or ghl_tagged) else "partial",
        error_detail=None if lead_id else "Close lead not found, GHL updated only",
        payload=raw_body,
    )

    # Telegram alert for visibility
    await send_telegram_alert(
        f"<b>Contact Declined</b>\n"
        f"Name: {name}\n"
        f"Phone: {phone}\n"
        f"Message: {message[:100] if message else '(not captured)'}\n"
        f"Close Lead: {lead_id or 'not found'}\n"
        f"GHL Tagged: {ghl_tagged}\n"
        f"GHL Removed: {ghl_removed}",
    )

    return {
        "status": "ok",
        "lead_id": lead_id or None,
        "close_updated": bool(lead_id),
        "ghl_tagged": ghl_tagged,
        "ghl_removed_from_sequences": ghl_removed,
    }
