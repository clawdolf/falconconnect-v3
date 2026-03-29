"""Close.com → FC kill-switch webhook — stops GHL RVM sequences on lead status changes.

Endpoint: POST /api/close/lead-status

When a Close lead moves to a terminal status (Closed Won/Lost, Dead, DNC, etc.),
this webhook:
1. Looks up the GHL contact ID via lead_xref (by phone)
2. Adds an "rvm-stop" tag to the GHL contact
3. Removes the contact from the RVM workflow (if workflow ID is configured)
4. Logs the event to sync_log

Auth: Close HMAC-SHA256 signature (close-sig-hash / close-sig-timestamp).
Always returns 200 — Close retries on non-200.
"""

import hashlib
import hmac
import json
import logging
from typing import Optional

import httpx
from fastapi import APIRouter, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from fastapi import Depends

from config import get_settings
from db.database import get_session
from db.models import LeadXref, SyncLog
from services.close import normalize_phone

logger = logging.getLogger("falconconnect.close_lead_status")

router = APIRouter()

GHL_BASE = "https://services.leadconnectorhq.com"
GHL_API_VERSION = "2021-07-28"

# Lead statuses that trigger the kill switch — stop all GHL cadence activity
STOP_STATUSES = {
    "Closed Won",
    "Closed Lost",
    "Dead",
    "DNC",
    "Bad Number",
    "Opted Out",
    "Appointment Set",
    "Appointment Held",
    "Not Interested",
}


def _verify_close_signature(
    raw_body: bytes,
    sig_hash: Optional[str],
    sig_timestamp: Optional[str],
    signature_key: str,
) -> bool:
    """Verify Close.com webhook HMAC-SHA256 signature.

    Close sends:
      - close-sig-hash: hex HMAC-SHA256 digest
      - close-sig-timestamp: unix timestamp string

    The signed data is: timestamp + payload (concatenated as strings).
    The key is the subscription's signature_key (hex-encoded).
    """
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


def _ghl_headers() -> dict:
    """Standard GHL API headers."""
    settings = get_settings()
    return {
        "Authorization": f"Bearer {settings.ghl_api_key}",
        "Version": GHL_API_VERSION,
        "Content-Type": "application/json",
    }


async def _add_ghl_tag(contact_id: str, tag: str) -> bool:
    """Add a tag to a GHL contact. Returns True on success."""
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                f"{GHL_BASE}/contacts/{contact_id}/tags",
                json={"tags": [tag]},
                headers=_ghl_headers(),
            )
            resp.raise_for_status()
            logger.info("Added tag '%s' to GHL contact %s", tag, contact_id)
            return True
    except Exception as exc:
        logger.error("Failed to add tag '%s' to GHL contact %s: %s", tag, contact_id, exc)
        return False


async def _remove_from_workflow(contact_id: str, workflow_id: str) -> bool:
    """Remove a GHL contact from a workflow. Returns True on success."""
    if not workflow_id:
        return False
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.delete(
                f"{GHL_BASE}/contacts/{contact_id}/workflow/{workflow_id}",
                headers=_ghl_headers(),
            )
            resp.raise_for_status()
            logger.info(
                "Removed GHL contact %s from workflow %s", contact_id, workflow_id
            )
            return True
    except Exception as exc:
        logger.error(
            "Failed to remove GHL contact %s from workflow %s: %s",
            contact_id, workflow_id, exc,
        )
        return False


def _extract_phone_from_event(event_data: dict) -> str:
    """Extract and normalize the first phone from a Close lead webhook event.

    Close webhook lead payloads nest contacts under data or data.lead.
    """
    # Try data.contacts[0].phones[0].phone
    contacts = event_data.get("contacts", [])
    if not contacts:
        # Try nested under "lead"
        lead = event_data.get("lead", {})
        contacts = lead.get("contacts", [])

    if contacts:
        phones = contacts[0].get("phones", [])
        if phones:
            return normalize_phone(phones[0].get("phone", ""))

    return ""


def _extract_status_label(payload: dict) -> str:
    """Extract the lead status label from a Close webhook payload.

    Close lead.updated events include the full lead object in event.data.
    The status label can appear at:
      - event.data.status_label
      - event.data.lead.status_label
    """
    event = payload.get("event", {})
    data = event.get("data", {})

    status_label = data.get("status_label", "")
    if not status_label:
        status_label = data.get("lead", {}).get("status_label", "")

    return status_label


async def _log_sync(
    session: AsyncSession,
    event_type: str,
    source_id: str = "",
    target_id: str = "",
    sync_status: str = "ok",
    error_detail: str = None,
    payload: dict = None,
):
    """Write a sync_log entry."""
    log = SyncLog(
        event_type=event_type,
        direction="close_to_ghl",
        source_id=source_id,
        target_id=target_id,
        payload=json.dumps(payload, default=str) if payload else None,
        status=sync_status,
        error_detail=error_detail,
    )
    session.add(log)


@router.post("/lead-status")
async def close_lead_status_webhook(
    request: Request,
    session: AsyncSession = Depends(get_session),
):
    """Receive Close.com lead status change webhook — kill-switch for GHL sequences.

    Verifies HMAC-SHA256 signature, checks if the new status is terminal,
    looks up the GHL contact via lead_xref, and stops the RVM workflow.

    Always returns 200 — Close retries on non-200.

    Webhook URL: https://falconconnect.org/api/close/lead-status
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
                "Close lead-status webhook signature verification FAILED — "
                "sig_hash=%s sig_timestamp=%s",
                sig_hash[:10] if sig_hash else "MISSING",
                sig_timestamp or "MISSING",
            )
            await _log_sync(
                session,
                event_type="close.lead_status_stop",
                sync_status="error",
                error_detail="signature verification failed",
            )
            # Return 200 anyway — don't trigger Close retries for auth issues
            return {"status": "error", "reason": "signature_verification_failed"}
    else:
        logger.warning(
            "CLOSE_WEBHOOK_SECRET not set — skipping signature verification"
        )

    # Parse payload
    try:
        payload = json.loads(raw_body)
    except json.JSONDecodeError:
        logger.error("Invalid JSON in Close lead-status webhook")
        return {"status": "error", "reason": "invalid_json"}

    # Check event type — only handle lead.updated and lead.status_changed
    event = payload.get("event", {})
    object_type = event.get("object_type", "")
    action = event.get("action", "")

    if object_type != "lead" or action != "updated":
        logger.debug(
            "Ignoring Close lead-status event: object_type=%s action=%s",
            object_type, action,
        )
        return {"status": "skipped", "reason": f"not a lead update: {object_type}.{action}"}

    # Check if status_label changed to a stop status
    status_label = _extract_status_label(payload)
    if not status_label:
        logger.debug("No status_label in Close lead-status event — skipping")
        return {"status": "skipped", "reason": "no status_label"}

    if status_label not in STOP_STATUSES:
        logger.debug(
            "Lead status '%s' is not a stop status — skipping", status_label
        )
        return {"status": "skipped", "reason": f"status '{status_label}' not in stop list"}

    # Extract lead ID and phone
    event_data = event.get("data", {})
    lead_id = event.get("lead_id", "") or event_data.get("id", "")
    phone = _extract_phone_from_event(event_data)

    logger.info(
        "Close lead-status kill-switch: lead=%s status='%s' phone=%s",
        lead_id, status_label, phone,
    )

    if not phone:
        logger.warning(
            "No phone in Close lead-status event for lead %s — cannot look up GHL contact",
            lead_id,
        )
        await _log_sync(
            session,
            event_type="close.lead_status_stop",
            source_id=lead_id,
            sync_status="skipped",
            error_detail="no phone number in event",
            payload=payload,
        )
        return {"status": "skipped", "reason": "no phone number"}

    # Look up GHL contact via lead_xref
    result = await session.execute(
        select(LeadXref).where(LeadXref.phone == phone)
    )
    xref = result.scalar_one_or_none()

    if not xref or not xref.ghl_contact_id:
        logger.warning(
            "No LeadXref found for phone %s (lead %s) — cannot stop GHL sequence",
            phone, lead_id,
        )
        await _log_sync(
            session,
            event_type="close.lead_status_stop",
            source_id=lead_id,
            sync_status="skipped",
            error_detail=f"no lead_xref for phone {phone}",
            payload=payload,
        )
        return {"status": "skipped", "reason": "no GHL contact found"}

    ghl_contact_id = xref.ghl_contact_id

    # Add rvm-stop tag to GHL contact
    tag_added = await _add_ghl_tag(ghl_contact_id, "rvm-stop")

    # Remove from RVM workflow if configured
    workflow_removed = False
    if settings.ghl_rvm_workflow_id:
        workflow_removed = await _remove_from_workflow(
            ghl_contact_id, settings.ghl_rvm_workflow_id
        )

    # Log to sync_log
    await _log_sync(
        session,
        event_type="close.lead_status_stop",
        source_id=lead_id,
        target_id=ghl_contact_id,
        sync_status="ok" if tag_added else "error",
        error_detail=None if tag_added else "failed to add rvm-stop tag",
        payload=payload,
    )

    logger.info(
        "Kill-switch executed: lead=%s ghl=%s status='%s' tag_added=%s workflow_removed=%s",
        lead_id, ghl_contact_id, status_label, tag_added, workflow_removed,
    )

    return {
        "status": "ok",
        "lead_id": lead_id,
        "ghl_contact_id": ghl_contact_id,
        "status_label": status_label,
        "tag_added": tag_added,
        "workflow_removed": workflow_removed,
    }
