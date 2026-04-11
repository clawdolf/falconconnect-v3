"""Lead capture & bulk import.

Bulk import writes to Close.com (primary CRM).
Single capture (capture_lead) still writes to Notion → GHL (separate migration).
"""

import asyncio
import logging
from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, status
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from db.database import get_session
from db.models import LeadXref
from middleware.auth import require_auth
from services import close, ghl
from services.ghl import normalize_phone

logger = logging.getLogger("falconconnect.leads")

router = APIRouter()


# -- Lead field normalization --

def _title(val):
    if not val:
        return val
    skip_upper = {"llc", "inc", "na", "n/a", "usa", "fha", "va", "usda", "arm"}
    words = val.strip().split()
    out = []
    for w in words:
        if w.lower() in skip_upper:
            out.append(w.upper())
        elif "'" in w:
            out.append("'".join(p.capitalize() for p in w.split("'")))
        else:
            out.append(w.capitalize())
    return " ".join(out)


def _normalize_lead(d: dict) -> dict:
    title_fields = [
        "first_name", "last_name", "city", "county", "lender",
        "address", "best_time_to_call",
    ]
    for f in title_fields:
        if d.get(f):
            d[f] = _title(d[f])
    if d.get("email"):
        d["email"] = d["email"].strip().lower()
    if d.get("state") and len(d["state"].strip()) == 2:
        d["state"] = d["state"].strip().upper()
    if d.get("notes"):
        d["notes"] = d["notes"].strip()
    return d


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
    home_value: Optional[str] = Field(None, max_length=64)
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
    tobacco: Optional[str] = Field(None, max_length=32)    # "Yes"/"No" from frontend
    medical: Optional[str] = Field(None, max_length=256)   # Free text or "Yes"/"No" from frontend
    spanish: Optional[str] = Field(None, max_length=32)    # "Yes"/"No" from frontend
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
    enable_rvm: bool = True  # If True: GHL tag=rvm-staging, Close cadence=1. r0-pending; If False: GHL tag=rvm-skipped, Close cadence=2. r1-calling


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
    session: AsyncSession = Depends(get_session),
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
            _normalize_lead(lead_dict)

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
                close_result = await close.create_lead(lead_dict, enable_rvm=req.enable_rvm)
                close_lead_id = close_result["id"]
            except Exception as exc:
                failed += 1
                # Extract response body from httpx errors for diagnosability
                error_detail = str(exc)
                if hasattr(exc, 'response') and exc.response is not None:
                    try:
                        error_detail = f"{exc} | Response: {exc.response.text[:500]}"
                    except Exception:
                        pass
                errors.append(
                    BulkImportError(
                        index=idx,
                        error=f"Close.com write failed: {error_detail}",
                        lead_name=lead_name,
                    )
                )
                logger.warning("Bulk import — Close failed for %s: %s", lead_name, error_detail)
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

            # ── STEP 3: GHL upsert — non-fatal, surfaces in error summary ──
            ghl_contact_id = ""
            try:
                ghl_lead = item.model_dump()
                ghl_lead["tags"] = ["rvm-staging"] if req.enable_rvm else ["rvm-skipped"]
                ghl_contact = await ghl.upsert_contact(ghl_lead)
                ghl_contact_id = ghl_contact.get("id", "")
                logger.info("Bulk import — GHL upsert OK: %s (GHL:%s)", lead_name, ghl_contact_id)
            except Exception as ghl_exc:
                ghl_detail = str(ghl_exc)
                errors.append(
                    BulkImportError(
                        index=idx,
                        error=f"GHL upsert failed (lead created in Close): {ghl_detail}",
                        lead_name=lead_name,
                    )
                )
                logger.warning("Bulk import — GHL upsert failed for %s (non-fatal): %s", lead_name, ghl_exc)

            # ── STEP 3b: Write GHL contact ID back to Close lead custom field ──
            if ghl_contact_id and close_lead_id:
                try:
                    import httpx as _httpx
                    _auth = close._auth()
                    async with _httpx.AsyncClient(timeout=15.0) as _c:
                        await _c.put(
                            f"https://api.close.com/api/v1/lead/{close_lead_id}/",
                            json={"custom.cf_XWisbKrkWGeMvGYTMGMZVoWjYvFlcXmOkgILiXyDcMM": ghl_contact_id},
                            auth=_auth,
                        )
                except Exception as ghl_field_exc:
                    logger.warning(
                        "Bulk import — GHL ID field update failed for %s (non-fatal): %s",
                        lead_name, ghl_field_exc,
                    )

            # ── STEP 4: Persist GHL↔Close cross-reference ──
            if ghl_contact_id:
                try:
                    result = await session.execute(
                        select(LeadXref).where(LeadXref.ghl_contact_id == ghl_contact_id)
                    )
                    xref = result.scalar_one_or_none()
                    if xref:
                        xref.close_lead_id = close_lead_id
                        xref.phone = normalize_phone(item.phone)
                    else:
                        session.add(LeadXref(
                            ghl_contact_id=ghl_contact_id,
                            close_lead_id=close_lead_id,
                            phone=normalize_phone(item.phone),
                            first_name=item.first_name,
                            last_name=item.last_name,
                            notion_page_id=None,
                        ))
                    await session.flush()
                except Exception as xref_exc:
                    logger.warning(
                        "LeadXref upsert failed for %s (non-fatal): %s",
                        lead_name, xref_exc,
                    )

            created += 1
            logger.info(
                "Bulk import — created: %s (Close:%s, GHL:%s)",
                lead_name, close_lead_id, ghl_contact_id or "FAILED",
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


