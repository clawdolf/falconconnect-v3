"""Lead capture endpoint — dual push to GHL + Notion."""

import json
import logging

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from db.database import get_session
from db.models import LeadXref, SyncLog
from models.lead import LeadCaptureResponse, LeadPayload
from services import ghl, notion
from utils.age import calculate_age, calculate_lage

logger = logging.getLogger("falconconnect.leads")

router = APIRouter()


@router.post(
    "/leads/capture",
    response_model=LeadCaptureResponse,
    status_code=status.HTTP_201_CREATED,
)
async def capture_lead(
    payload: LeadPayload,
    session: AsyncSession = Depends(get_session),
):
    """Capture a new lead and push to both GHL and Notion.

    1. Validate the payload.
    2. Calculate age from birth_year and lage_months from mail_date.
    3. Upsert contact + create opportunity in GHL.
    4. Upsert lead page in Notion.
    5. Store the cross-reference (ghl_id ↔ notion_id ↔ phone).
    6. Return IDs and calculated fields.
    """
    lead_dict = payload.model_dump()

    # Calculate derived fields
    age = calculate_age(payload.birth_year) if payload.birth_year else None
    lage_months = (
        calculate_lage(payload.mail_date.isoformat()) if payload.mail_date else None
    )

    # --- Push to GHL ---
    try:
        ghl_contact = await ghl.upsert_contact(lead_dict)
        ghl_contact_id = ghl_contact.get("id", "")
    except Exception as exc:
        logger.error("GHL upsert_contact failed: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Failed to push lead to GHL: {exc}",
        )

    # Create opportunity in GHL
    try:
        opp_name = f"{payload.first_name} {payload.last_name} — {payload.source or 'web'}"
        await ghl.create_opportunity(ghl_contact_id, stage="new", name=opp_name)
    except Exception as exc:
        logger.warning("GHL create_opportunity failed (non-fatal): %s", exc)

    # --- Push to Notion ---
    try:
        notion_page_id = await notion.upsert_lead(
            lead_dict,
            ghl_contact_id=ghl_contact_id,
            age=age,
            lage_months=lage_months,
        )
    except Exception as exc:
        logger.error("Notion upsert_lead failed: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Failed to push lead to Notion: {exc}",
        )

    # --- Store cross-reference ---
    try:
        # Check if xref already exists for this phone
        existing = await session.execute(
            select(LeadXref).where(LeadXref.phone == payload.phone)
        )
        xref = existing.scalar_one_or_none()

        if xref:
            xref.ghl_contact_id = ghl_contact_id
            xref.notion_page_id = notion_page_id
            xref.first_name = payload.first_name
            xref.last_name = payload.last_name
        else:
            xref = LeadXref(
                ghl_contact_id=ghl_contact_id,
                notion_page_id=notion_page_id,
                phone=payload.phone,
                first_name=payload.first_name,
                last_name=payload.last_name,
            )
            session.add(xref)

        # Log the sync event
        sync_log = SyncLog(
            event_type="lead.captured",
            direction="inbound",
            source_id=payload.phone,
            target_id=f"ghl:{ghl_contact_id}|notion:{notion_page_id}",
            payload=json.dumps(lead_dict, default=str),
            status="ok",
        )
        session.add(sync_log)

    except Exception as exc:
        logger.error("Failed to store xref: %s", exc)
        # Non-fatal — lead is already in GHL and Notion

    logger.info(
        "Lead captured: %s %s → GHL:%s / Notion:%s",
        payload.first_name,
        payload.last_name,
        ghl_contact_id,
        notion_page_id,
    )

    return LeadCaptureResponse(
        ghl_id=ghl_contact_id,
        notion_id=notion_page_id,
        age=age,
        lage_months=lage_months,
    )
