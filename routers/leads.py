"""Lead capture endpoint — dual push to GHL + Notion."""

import json
import logging
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from db.database import get_session
from db.models import LeadXref, SyncLog
from models.lead import LeadCaptureResponse, LeadPayload
from services import ghl, notion
from utils.age import calculate_age, calculate_lage

logger = logging.getLogger("falconconnect.leads")

router = APIRouter()


# ── Bulk import models ──


class BulkLeadItem(BaseModel):
    """Single lead in a bulk import request."""

    first_name: str = Field(..., min_length=1, max_length=128)
    last_name: str = Field(..., min_length=1, max_length=128)
    phone: str = Field(..., min_length=7, max_length=20)
    email: Optional[str] = Field(None, max_length=256)
    address: Optional[str] = Field(None, max_length=512)
    city: Optional[str] = Field(None, max_length=128)
    state: Optional[str] = Field(None, max_length=2)
    zip_code: Optional[str] = Field(None, max_length=10)
    birth_year: Optional[int] = Field(None, ge=1900, le=2026)
    mail_date: Optional[str] = None
    lead_source: Optional[str] = Field(None, max_length=64)
    lead_type: Optional[str] = Field(None, max_length=64)
    lead_age_bucket: Optional[str] = Field(None, max_length=32)
    lender: Optional[str] = Field(None, max_length=128)
    notes: Optional[str] = Field(None, max_length=2000)


class BulkImportRequest(BaseModel):
    """Request body for POST /leads/bulk."""

    leads: List[BulkLeadItem]
    dry_run: bool = False


class BulkImportError(BaseModel):
    """Error detail for a single lead in bulk import."""

    index: int
    error: str
    lead_name: Optional[str] = None


class BulkImportResponse(BaseModel):
    """Response from bulk lead import."""

    created: int
    failed: int
    errors: List[BulkImportError]


@router.post(
    "/leads/bulk",
    response_model=BulkImportResponse,
    status_code=status.HTTP_201_CREATED,
)
async def bulk_import_leads(
    req: BulkImportRequest,
    session: AsyncSession = Depends(get_session),
) -> BulkImportResponse:
    """Bulk import leads — push each to GHL + Notion.

    Accepts an array of lead objects. Processes each individually so
    partial failures don't block the entire batch.
    """
    created = 0
    failed = 0
    errors: List[BulkImportError] = []

    for idx, item in enumerate(req.leads):
        lead_name = f"{item.first_name} {item.last_name}"
        try:
            lead_dict = item.model_dump()

            # Calculate derived fields
            age = calculate_age(item.birth_year) if item.birth_year else None
            lage_months = None
            if item.mail_date:
                try:
                    lage_months = calculate_lage(item.mail_date)
                except Exception:
                    pass

            # Dry run — validate only, skip all external writes
            if req.dry_run:
                created += 1
                continue

            # Push to GHL
            ghl_contact = await ghl.upsert_contact(lead_dict)
            ghl_contact_id = ghl_contact.get("id", "")

            # Create GHL opportunity
            try:
                opp_name = (
                    f"{item.first_name} {item.last_name} — "
                    f"{item.lead_source or 'bulk-import'}"
                )
                await ghl.create_opportunity(
                    ghl_contact_id,
                    stage_name="New Lead",
                    name=opp_name,
                )
            except Exception as exc:
                logger.warning(
                    "GHL opp creation failed for %s (non-fatal): %s",
                    lead_name,
                    exc,
                )

            # Push to Notion
            notion_page_id = await notion.upsert_lead(
                lead_dict,
                ghl_contact_id=ghl_contact_id,
                age=age,
                lage_months=lage_months,
            )

            # Store cross-reference
            try:
                existing = await session.execute(
                    select(LeadXref).where(LeadXref.phone == item.phone)
                )
                xref = existing.scalar_one_or_none()

                if xref:
                    xref.ghl_contact_id = ghl_contact_id
                    xref.notion_page_id = notion_page_id
                    xref.first_name = item.first_name
                    xref.last_name = item.last_name
                else:
                    xref = LeadXref(
                        ghl_contact_id=ghl_contact_id,
                        notion_page_id=notion_page_id,
                        phone=item.phone,
                        first_name=item.first_name,
                        last_name=item.last_name,
                    )
                    session.add(xref)

                sync_log = SyncLog(
                    event_type="lead.bulk_import",
                    direction="inbound",
                    source_id=item.phone,
                    target_id=f"ghl:{ghl_contact_id}|notion:{notion_page_id}",
                    payload=json.dumps(lead_dict, default=str),
                    status="ok",
                )
                session.add(sync_log)
            except Exception as exc:
                logger.error("Xref storage failed for %s: %s", lead_name, exc)

            created += 1
            logger.info("Bulk import — created: %s", lead_name)

        except Exception as exc:
            failed += 1
            errors.append(
                BulkImportError(
                    index=idx,
                    error=str(exc),
                    lead_name=lead_name,
                )
            )
            logger.warning("Bulk import — failed %s: %s", lead_name, exc)

    logger.info(
        "Bulk import complete: %d created, %d failed out of %d",
        created,
        failed,
        len(req.leads),
    )

    return BulkImportResponse(created=created, failed=failed, errors=errors)


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
    4. Upsert lead page in Notion (with GHL contact ID for xref).
    5. Store the cross-reference (ghl_id ↔ notion_id ↔ phone).
    6. Return IDs and calculated fields.
    """
    lead_dict = payload.model_dump()

    # Normalize source — prefer lead_source over source
    if payload.lead_source and not payload.source:
        lead_dict["source"] = payload.lead_source

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
        opp_name = f"{payload.first_name} {payload.last_name} — {payload.lead_source or payload.source or 'web'}"
        await ghl.create_opportunity(
            ghl_contact_id,
            stage_name="New Lead",
            name=opp_name,
        )
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
