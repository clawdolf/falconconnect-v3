"""Lead capture & bulk import — Notion first (source of truth), then GHL (automations).

Business logic (locked decisions):
1. Write to Notion FIRST — if Notion fails, skip that row entirely (do NOT write to GHL).
2. Write to GHL SECOND — if GHL fails, log as warning but count lead as successfully imported.
3. NO local DB writes — lead_xref and sync_log are not used in the import flow.
"""

import asyncio
import json
import logging
from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field, field_validator

from middleware.auth import require_auth
from services import ghl, notion, quo
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


class GHLWarning(BaseModel):
    """Warning when a lead was saved to Notion but GHL failed."""

    index: int
    lead_name: str
    error: str


class BulkImportResponse(BaseModel):
    """Response from bulk lead import."""

    created: int
    updated: int = 0
    failed: int
    quo_synced: int = 0
    errors: List[BulkImportError]
    ghl_warnings: List[GHLWarning] = []


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
    """Bulk import leads — Notion first (source of truth), then GHL (automations).

    Write order:
    1. Notion FIRST — if Notion fails, skip the row entirely
    2. GHL SECOND — if GHL fails, log warning but count as success (it's in Notion)
    3. NO local DB writes — lead_xref/sync_log removed from import flow

    Processes each lead individually so partial failures don't block the batch.
    100ms delay between GHL API calls to avoid rate limiting.
    """
    created = 0
    updated = 0
    failed = 0
    quo_synced = 0
    errors: List[BulkImportError] = []
    ghl_warnings: List[GHLWarning] = []

    for idx, item in enumerate(req.leads):
        lead_name = f"{item.first_name} {item.last_name}"
        try:
            lead_dict = item.model_dump()

            # Test mode: override tier to TEST so records are easy to find + delete
            if req.test_mode:
                lead_dict["tier"] = "TEST"
                lead_dict["lead_source"] = f"[TEST] {lead_dict.get('lead_source') or 'FC v3'}"

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

            # ── STEP 1: Notion FIRST (source of truth) ──
            # If Notion fails, skip this row entirely — do NOT write to GHL
            notion_is_new = True
            try:
                notion_result = await notion.upsert_lead(
                    lead_dict,
                    ghl_contact_id="",  # Will be updated after GHL
                    age=age,
                    lage_months=lage_months,
                )
                notion_page_id = notion_result["page_id"]
                notion_is_new = notion_result["is_new"]
            except Exception as exc:
                # Notion failed → skip this row entirely
                failed += 1
                errors.append(
                    BulkImportError(
                        index=idx,
                        error=f"Notion write failed: {exc}",
                        lead_name=lead_name,
                    )
                )
                logger.warning("Bulk import — Notion failed for %s: %s", lead_name, exc)
                continue

            # ── STEP 2: GHL SECOND (automations only) ──
            # If GHL fails, log warning but count as success (lead is in Notion)
            ghl_contact_id = ""
            try:
                ghl_contact = await ghl.upsert_contact(lead_dict, test_mode=req.test_mode)
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
                except Exception as opp_exc:
                    logger.warning(
                        "GHL opp creation failed for %s (non-fatal): %s",
                        lead_name, opp_exc,
                    )

                # Update Notion with GHL contact ID → write to "GHL ID" field (bare ID, no prefix)
                if ghl_contact_id:
                    try:
                        props: dict = {
                            "GHL ID": {
                                "rich_text": [{"text": {"content": ghl_contact_id}}]
                            }
                        }
                        # Write notes to Aggregate Comments separately if present
                        if item.notes:
                            existing_comments = await notion._read_aggregate_comments(notion_page_id)
                            merged = item.notes if not existing_comments else f"{existing_comments} | {item.notes}"
                            props["Aggregate Comments"] = {
                                "rich_text": [{"text": {"content": merged}}]
                            }
                        await notion.update_page(notion_page_id, props)
                    except Exception:
                        pass  # Non-fatal

            except Exception as ghl_exc:
                # GHL failed → log warning but count as success (lead is in Notion)
                ghl_warnings.append(
                    GHLWarning(
                        index=idx,
                        lead_name=lead_name,
                        error=str(ghl_exc),
                    )
                )
                logger.warning("Bulk import — GHL failed for %s (in Notion): %s", lead_name, ghl_exc)

            # No local DB writes (lead_xref/sync_log removed)

            # ── STEP 3: Quo THIRD (dialer sync) ──
            # Non-fatal — if Quo fails, lead is still in Notion + GHL
            try:
                quo_id = await quo.sync_contact(lead_dict, test_mode=req.test_mode)
                if quo_id:
                    quo_synced += 1
            except Exception as quo_exc:
                logger.warning("Quo sync failed for %s (non-fatal): %s", lead_name, quo_exc)

            # Track created vs updated based on Notion's result
            if notion_is_new:
                created += 1
            else:
                updated += 1
            logger.info("Bulk import — %s: %s (Notion:%s, GHL:%s, Quo:%s)", "created" if notion_is_new else "updated", lead_name, notion_page_id, ghl_contact_id or "SKIPPED", "yes" if quo_synced else "no")

            # Minimal rate limiting delay between GHL calls (30ms is enough)
            if not req.dry_run and idx < len(req.leads) - 1:
                await asyncio.sleep(0.03)

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
        "Bulk import complete: %d created, %d updated, %d failed, %d GHL warnings out of %d",
        created, updated, failed, len(ghl_warnings), len(req.leads),
    )

    return BulkImportResponse(
        created=created,
        updated=updated,
        failed=failed,
        quo_synced=quo_synced,
        errors=errors,
        ghl_warnings=ghl_warnings,
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
