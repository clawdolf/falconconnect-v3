"""GHL → Close cadence webhook — receives r0-complete tag from GHL, creates/updates lead in Close.

Endpoint: POST /api/ghl/rvm-complete

Flow:
1. GHL fires webhook when contact tag changes to "r0-complete"
2. Extracts contact data (name, phone, custom fields) from GHL payload
3. Checks if lead already exists in Close by phone number
4. If new: creates lead in Close with cadence_stage=r1-to-call + GHL contact ID
5. If existing: updates cadence_stage to r1-to-call
6. Logs every action to sync_log table
7. Returns 200 on success

Auth: X-GHL-Webhook-Secret header (same as existing GHL webhook pattern).
"""

import json
import logging
from typing import Optional

import httpx
from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from config import get_settings
from db.database import get_session
from db.models import SyncLog
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


async def _search_close_by_phone(phone: str) -> Optional[dict]:
    """Search Close for an existing lead by phone number.

    Uses Close's lead search endpoint with phone query.
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
                                                "field_name": "phones.phone",
                                            },
                                            "condition": {
                                                "type": "text",
                                                "mode": "full_words",
                                                "value": phone,
                                            },
                                        }
                                    ],
                                },
                            },
                        ],
                    },
                    "_fields": {
                        "lead": ["id", "display_name", "contacts"],
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
    """Create a new lead in Close with cadence_stage=r1-to-call.

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
        f"custom.{CF_CADENCE_STAGE}": "r1-to-call",
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

    GHL tag-change webhooks send the full contact object.
    Handles variations in payload structure.
    """
    # GHL can nest contact data at top level or under "contact"
    contact = payload.get("contact", payload)

    first_name = (
        contact.get("firstName", "")
        or contact.get("first_name", "")
        or contact.get("name", "").split()[0] if contact.get("name") else ""
    )
    last_name = (
        contact.get("lastName", "")
        or contact.get("last_name", "")
        or (" ".join(contact.get("name", "").split()[1:]) if contact.get("name") else "")
    )
    phone = normalize_phone(contact.get("phone", ""))
    email = contact.get("email", "")
    contact_id = (
        contact.get("id", "")
        or contact.get("contactId", "")
        or payload.get("contactId", "")
        or payload.get("contact_id", "")
    )
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

    Creates or updates the lead in Close with cadence_stage=r1-to-call.

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

    if not phone:
        logger.warning(
            "No phone number for GHL contact %s — skipping Close sync",
            ghl_contact_id,
        )
        await _log_sync(
            session,
            event_type="ghl.rvm_complete",
            source_id=ghl_contact_id,
            status="skipped",
            error_detail="no phone number",
            payload=raw_body,
        )
        return {"status": "skipped", "reason": "no phone number"}

    # Check if lead already exists in Close by phone
    existing_lead = await _search_close_by_phone(phone)

    if existing_lead:
        lead_id = existing_lead.get("id", "")
        logger.info(
            "Lead already exists in Close: %s — updating cadence_stage to r1-to-call",
            lead_id,
        )
        updated = await _update_cadence_stage(lead_id, "r1-to-call")
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
            "cadence_stage": "r1-to-call",
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
            f"Stage: r1-to-call",
        )

        return {
            "status": "ok",
            "action": "created",
            "lead_id": lead_id,
            "cadence_stage": "r1-to-call",
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
