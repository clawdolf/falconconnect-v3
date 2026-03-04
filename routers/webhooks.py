"""GHL → Notion webhook bridge — routes GHL events to Notion updates."""

import json
import logging

from fastapi import APIRouter, Depends, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from db.database import get_session
from db.models import LeadXref, SyncLog
from models.webhook import GHLWebhookPayload
from services import notion
from utils.auth import verify_webhook_secret

logger = logging.getLogger("falconconnect.webhooks")

router = APIRouter()

# Mapping of GHL event types to handler functions
EVENT_HANDLERS = {
    "appointment.booked": "_handle_appointment_booked",
    "appointment.cancelled": "_handle_appointment_cancelled",
    "appointment.no_show": "_handle_appointment_no_show",
    "opportunity.stage_changed": "_handle_opportunity_stage_changed",
    "contact.opted_out": "_handle_contact_opted_out",
}


@router.post("/ghl")
async def ghl_webhook(
    request: Request,
    _secret: str = Depends(verify_webhook_secret),
    session: AsyncSession = Depends(get_session),
):
    """Receive GHL webhook events and mirror changes to Notion.

    Verifies the shared secret header before processing.
    Routes events by type to the appropriate handler.
    Logs every sync event to the sync_log table.
    """
    raw_body = await request.json()
    payload = GHLWebhookPayload(**raw_body)

    logger.info("GHL webhook received: type=%s contactId=%s", payload.type, payload.contactId)

    handler_name = EVENT_HANDLERS.get(payload.type)
    if not handler_name:
        logger.info("Unhandled GHL event type: %s — logging and skipping", payload.type)
        await _log_sync(
            session,
            event_type=payload.type,
            source_id=payload.contactId,
            status="skipped",
            payload=raw_body,
        )
        return {"status": "skipped", "reason": f"unhandled event type: {payload.type}"}

    # Look up the Notion page ID from our xref table
    notion_page_id = None
    if payload.contactId:
        result = await session.execute(
            select(LeadXref).where(LeadXref.ghl_contact_id == payload.contactId)
        )
        xref = result.scalar_one_or_none()
        if xref:
            notion_page_id = xref.notion_page_id

    if not notion_page_id:
        logger.warning(
            "No Notion page found for GHL contact %s — logging event without sync",
            payload.contactId,
        )
        await _log_sync(
            session,
            event_type=payload.type,
            source_id=payload.contactId,
            status="no_xref",
            payload=raw_body,
        )
        return {"status": "no_xref", "contactId": payload.contactId}

    # Dispatch to handler
    try:
        handler = globals()[handler_name]
        await handler(payload, notion_page_id)
        await _log_sync(
            session,
            event_type=payload.type,
            source_id=payload.contactId,
            target_id=notion_page_id,
            status="ok",
            payload=raw_body,
        )
        return {"status": "ok", "event": payload.type, "notion_page_id": notion_page_id}

    except Exception as exc:
        logger.error("Webhook handler failed: %s — %s", payload.type, exc)
        await _log_sync(
            session,
            event_type=payload.type,
            source_id=payload.contactId,
            target_id=notion_page_id,
            status="error",
            error_detail=str(exc),
            payload=raw_body,
        )
        return {"status": "error", "detail": str(exc)}


# --- Event handlers ---


async def _handle_appointment_booked(payload: GHLWebhookPayload, notion_page_id: str):
    """Update Notion with appointment date and set status to Scheduled."""
    properties = {
        "Status": {"select": {"name": "Scheduled"}},
    }
    if payload.startTime:
        properties["Appointment Date"] = {
            "date": {"start": payload.startTime}
        }
    await notion.update_page(notion_page_id, properties)
    logger.info("Appointment booked → Notion %s updated", notion_page_id)


async def _handle_appointment_cancelled(payload: GHLWebhookPayload, notion_page_id: str):
    """Set Notion appointment status to Cancelled."""
    await notion.update_page(
        notion_page_id,
        {"Status": {"select": {"name": "Cancelled"}}},
    )
    logger.info("Appointment cancelled → Notion %s updated", notion_page_id)


async def _handle_appointment_no_show(payload: GHLWebhookPayload, notion_page_id: str):
    """Set Notion appointment status to No Show."""
    await notion.update_page(
        notion_page_id,
        {"Status": {"select": {"name": "No Show"}}},
    )
    logger.info("Appointment no-show → Notion %s updated", notion_page_id)


async def _handle_opportunity_stage_changed(payload: GHLWebhookPayload, notion_page_id: str):
    """Mirror the GHL pipeline stage to Notion Status."""
    stage = payload.stage or "Unknown"
    await notion.update_page(
        notion_page_id,
        {"Status": {"select": {"name": stage}}},
    )
    logger.info("Opportunity stage → %s → Notion %s", stage, notion_page_id)


async def _handle_contact_opted_out(payload: GHLWebhookPayload, notion_page_id: str):
    """Mark the lead as DNC in Notion."""
    await notion.update_page(
        notion_page_id,
        {"Status": {"select": {"name": "DNC"}}},
    )
    logger.info("Contact opted out → DNC → Notion %s", notion_page_id)


# --- Helpers ---


async def _log_sync(
    session: AsyncSession,
    event_type: str,
    source_id: str = None,
    target_id: str = None,
    status: str = "ok",
    error_detail: str = None,
    payload: dict = None,
):
    """Write a sync_log entry."""
    log = SyncLog(
        event_type=event_type,
        direction="ghl_to_notion",
        source_id=source_id or "",
        target_id=target_id or "",
        payload=json.dumps(payload, default=str) if payload else None,
        status=status,
        error_detail=error_detail,
    )
    session.add(log)
