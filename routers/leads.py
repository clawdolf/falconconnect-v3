"""Lead capture & bulk import.

Bulk import writes to Close.com (primary CRM).
Single capture (capture_lead) still writes to Notion → GHL (separate migration).
"""

import asyncio
import json
import logging
from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field, field_validator

from middleware.auth import require_auth
from services import close, ghl, notion
from services.ghl import normalize_phone, split_phone_field
from utils.age import calculate_age, calculate_lage

logger = logging.getLogger("falconconnect.leads")

router = APIRouter()


# ── Bulk import models ──


class BulkLeadItem(BaseModel):
    """Single lead in a bulk import request."""

    first_name: str = Field(..., min_length=1, max_length=128)
    last_name: str = Field(..., min_length=1, max_length=128)
    phone: str = Field(..., min_length=7, max_length=40)
    email: Optional[str] = Field(None, max_length=256)
    address: Optional[str] = Field(None, max_length=512)
    city: Optional[str] = Field(None, max_length=128)
    county: Optional[str] = Field(None, max_length=128)
    state: Optional[str] = Field(None, max_length=64)  # Full names allowed — backend normalizes to 2-letter
    zip_code: Optional[str] = Field(None, max_length=10)
    # BUG 8 FIX: Dynamic max year instead of hardcoded 2026
    birth_year: Optional[int] = Field(None, ge=1900)
    mail_date: Optional[str] = None
    lead_source: Optional[str] = Field(None, max_length=64)
    lead_type: Optional[str] = Field(None, max_length=64)
    lead_age_bucket: Optional[str] = Field(None, max_length=32)
    lender: Optional[str] = Field(None, max_length=128)
    loan_amount: Optional[str] = Field(None, max_length=32)
    home_phone: Optional[str] = Field(None, max_length=40)
    mobile_phone: Optional[str] = Field(None, max_length=40)
    spouse_phone: Optional[str] = Field(None, max_length=40)
    spouse_dob: Optional[str] = None           # Spouse date of birth (ISO string)
    spouse_age: Optional[int] = Field(None, ge=0, le=120)  # Spouse age
    notes: Optional[str] = Field(None, max_length=2000)
    # Field-parity additions (match old Notion import script)
    tier: Optional[str] = Field(None, max_length=32)
    lpd: Optional[str] = None
    dob: Optional[str] = None
    best_time_to_call: Optional[str] = Field(None, max_length=256)
    gender: Optional[str] = Field(None, max_length=32)
    tobacco: Optional[bool] = None
    medical: Optional[bool] = None
    spanish: Optional[bool] = None
    lead_received: Optional[str] = None       # Date lead was received by vendor (ISO string)
    vendor_lead_id: Optional[str] = Field(None, max_length=64)  # Vendor's own lead ID

    @field_validator('birth_year')
    @classmethod
    def validate_birth_year(cls, v):
        if v is not None and v > datetime.now().year:
            raise ValueError(f'birth_year cannot be in the future (max {datetime.now().year})')
        return v


class BulkImportRequest(BaseModel):
    """Request body for POST /leads/bulk."""

    leads: List[BulkLeadItem]
    dry_run: bool = False
    test_mode: bool = False  # If True: forces tier='TEST', adds 'test-import' tag in GHL, writes normally so you can diagnose + delete


class BulkImportError(BaseModel):
    """Error detail for a single lead in bulk import."""

    index: int
    error: str
    lead_name: Optional[str] = None


class BulkImportResponse(BaseModel):
    """Response from bulk lead import."""

    created: int
    updated: int = 0
    failed: int
    errors: List[BulkImportError]


# BUG 11 FIX: Moved from /api/public/leads/bulk to /api/leads/bulk (requires auth)
@router.post(
    "/leads/bulk",
    response_model=BulkImportResponse,
    status_code=status.HTTP_201_CREATED,
)
async def bulk_import_leads(
    req: BulkImportRequest,
    user=Depends(require_auth),
) -> BulkImportResponse:
    """Bulk import leads — writes directly to Close.com (primary CRM).

    Write order per lead:
    1. Close.com create_lead — if fails, count as failed + skip
    2. If notes present, add_note — non-fatal
    3. Track created count

    Processes each lead individually so partial failures don't block the batch.
    300ms delay between Close API calls to respect rate limits.
    """
    created = 0
    failed = 0
    errors: List[BulkImportError] = []

    for idx, item in enumerate(req.leads):
        lead_name = f"{item.first_name} {item.last_name}"
        try:
            lead_dict = item.model_dump()

            # Test mode: override tier to TEST so records are easy to find + delete
            if req.test_mode:
                lead_dict["tier"] = "TEST"
                lead_dict["lead_source"] = f"[TEST] {lead_dict.get('lead_source') or 'FC v3'}"

            # Dry run — validate only, skip all external writes
            if req.dry_run:
                created += 1
                continue

            # ── STEP 1: Close.com (primary CRM) ──
            # If Close fails, count as failed and skip
            try:
                close_result = await close.create_lead(lead_dict)
                close_lead_id = close_result["id"]
            except Exception as exc:
                failed += 1
                errors.append(
                    BulkImportError(
                        index=idx,
                        error=f"Close.com write failed: {exc}",
                        lead_name=lead_name,
                    )
                )
                logger.warning("Bulk import — Close failed for %s: %s", lead_name, exc)
                continue

            # ── STEP 2: Add note if present (non-fatal) ──
            if item.notes:
                try:
                    await close.add_note(close_lead_id, item.notes)
                except Exception as note_exc:
                    logger.warning(
                        "Close note failed for %s (non-fatal): %s",
                        lead_name, note_exc,
                    )

            created += 1
            logger.info(
                "Bulk import — created: %s (Close:%s)",
                lead_name, close_lead_id,
            )

            # Rate limiting delay between Close API calls (300ms)
            if not req.dry_run and idx < len(req.leads) - 1:
                await asyncio.sleep(0.3)

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
        created, failed, len(req.leads),
    )

    return BulkImportResponse(
        created=created,
        failed=failed,
        errors=errors,
    )


# ── Single lead capture (kept for backwards compatibility) ──

from models.lead import LeadCaptureResponse, LeadPayload


@router.post(
    "/leads/capture",
    response_model=LeadCaptureResponse,
    status_code=status.HTTP_201_CREATED,
)
async def capture_lead(
    payload: LeadPayload,
    user=Depends(require_auth),
):
    """Capture a new lead — Notion first, then GHL.

    1. Calculate age from birth_year and lage_months from mail_date.
    2. Upsert lead page in Notion (source of truth).
    3. Upsert contact + create opportunity in GHL (automations).
    4. Update Notion with GHL contact ID cross-reference.
    5. Return IDs and calculated fields.
    """
    lead_dict = payload.model_dump()

    # Normalize source
    if payload.lead_source and not payload.source:
        lead_dict["source"] = payload.lead_source

    # Calculate derived fields
    age = calculate_age(payload.birth_year) if payload.birth_year else None
    lage_months = (
        calculate_lage(payload.mail_date.isoformat()) if payload.mail_date else None
    )

    # --- STEP 1: Notion FIRST ---
    try:
        notion_result = await notion.upsert_lead(
            lead_dict,
            ghl_contact_id="",
            age=age,
            lage_months=lage_months,
        )
        notion_page_id = notion_result["page_id"]
    except Exception as exc:
        logger.error("Notion upsert_lead failed: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Failed to push lead to Notion: {exc}",
        )

    # --- STEP 2: GHL SECOND ---
    ghl_contact_id = ""
    try:
        ghl_contact = await ghl.upsert_contact(lead_dict)
        ghl_contact_id = ghl_contact.get("id", "")

        # Create opportunity
        try:
            opp_name = f"{payload.first_name} {payload.last_name} — {payload.lead_source or payload.source or 'web'}"
            await ghl.create_opportunity(
                ghl_contact_id,
                stage_name="New Lead",
                name=opp_name,
            )
        except Exception as exc:
            logger.warning("GHL create_opportunity failed (non-fatal): %s", exc)

        # Update Notion with GHL ID → write to "GHL ID" field (bare ID, no prefix)
        if ghl_contact_id:
            try:
                notes = lead_dict.get("notes", "")
                props: dict = {
                    "GHL ID": {
                        "rich_text": [{"text": {"content": ghl_contact_id}}]
                    }
                }
                if notes:
                    existing_comments = await notion._read_aggregate_comments(notion_page_id)
                    merged = notes if not existing_comments else f"{existing_comments} | {notes}"
                    props["Aggregate Comments"] = {
                        "rich_text": [{"text": {"content": merged}}]
                    }
                await notion.update_page(notion_page_id, props)
            except Exception:
                pass

    except Exception as exc:
        # GHL failed but lead is in Notion — log warning, don't fail
        logger.warning("GHL upsert_contact failed (lead in Notion): %s", exc)

    logger.info(
        "Lead captured: %s %s → Notion:%s / GHL:%s",
        payload.first_name, payload.last_name,
        notion_page_id, ghl_contact_id or "FAILED",
    )

    return LeadCaptureResponse(
        ghl_id=ghl_contact_id,
        notion_id=notion_page_id,
        age=age,
        lage_months=lage_months,
    )
