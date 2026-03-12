"""License management routes — ported from FC v1 to async SQLAlchemy + Clerk auth.

Public endpoints (used by FalconVerify consumer portal):
  GET /api/licenses           — all active licenses
  GET /api/licenses/verify-info/{state_abbr} — verification system info for a state

Authenticated endpoints (Clerk):
  GET /api/licenses/me        — current user's licenses
  POST /api/licenses          — create license (auto-generates verify URL)
  PUT /api/licenses/{id}      — update license
  DELETE /api/licenses/{id}   — delete license
  GET /api/licenses/health-check — verify URL health check
"""

import asyncio
import logging
from typing import List, Optional

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from db.database import get_session
from db.models import DBAgent, DBLicense
from middleware.auth import require_auth
from models.licenses import (
    License,
    LicenseCreate,
    LicenseUpdate,
    StateVerifyInfo,
)
from constants_licenses import (
    get_verify_url as _get_verify_url,
    get_state_verify_info as _get_state_verify_info,
    needs_manual_verification as _needs_manual_verification,
    ALL_STATES,
    MANUAL_ENTRY_STATES,
)

logger = logging.getLogger("falconconnect.licenses")

router = APIRouter()

# States that require a license number for consumer manual-search verification
REQUIRE_LICENSE_NUMBER_STATES = {"TX", "PA", "ME", "CA", "NY"}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _get_agent_npn(session: AsyncSession, user_id: str) -> str:
    """Look up the agent's NPN from the agents table using their user_id."""
    result = await session.execute(
        select(DBAgent).where(DBAgent.user_id == user_id)
    )
    agent = result.scalar_one_or_none()
    return (agent.npn or "") if agent else ""


# ---------------------------------------------------------------------------
# Health check models
# ---------------------------------------------------------------------------

class HealthCheckRequest(BaseModel):
    urls: List[str]


class UrlHealth(BaseModel):
    url: str
    ok: bool


# ---------------------------------------------------------------------------
# Public endpoints (no auth required — used by FalconVerify)
# ---------------------------------------------------------------------------

@router.get("/", response_model=List[License])
async def get_public_licenses(
    user_id: Optional[str] = Query(None, description="Filter by user ID"),
    session: AsyncSession = Depends(get_session),
):
    """Public endpoint: Get all active licenses for the consumer portal.

    FalconVerify (falconfinancial.org) calls this to display agent licenses
    with verification links.
    """
    stmt = select(DBLicense).where(DBLicense.status == "active")

    if user_id:
        stmt = stmt.where(DBLicense.user_id == user_id)

    stmt = stmt.order_by(DBLicense.state)

    result = await session.execute(stmt)
    licenses = result.scalars().all()

    # Look up agent NPN once for all licenses (same user)
    npn = None
    if licenses:
        npn = await _get_agent_npn(session, licenses[0].user_id)

    return [
        License(
            id=lic.id,
            state=lic.state,
            state_abbreviation=lic.state_abbreviation,
            license_number=lic.license_number,
            verify_url=lic.verify_url,
            needs_manual_verification=lic.needs_manual_verification,
            status=lic.status,
            license_type=lic.license_type,
            npn=npn or None,  # Fallback display for SBS states with no state license number
        )
        for lic in licenses
    ]


@router.get("/verify-info/{state_abbr}", response_model=StateVerifyInfo)
async def get_verify_info(state_abbr: str):
    """Public endpoint: Get verification system info for a state.

    Returns whether the state uses NAIC SOLAR, FL DFS, Sircon, or a state portal,
    and whether manual entry is required.
    """
    state_abbr = state_abbr.upper()
    if state_abbr not in ALL_STATES:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Unknown state: {state_abbr}",
        )

    info = _get_state_verify_info(state_abbr)
    return StateVerifyInfo(**info)


# ---------------------------------------------------------------------------
# Authenticated endpoints (Clerk auth required)
# ---------------------------------------------------------------------------

@router.get("/me", response_model=List[License])
async def get_my_licenses(
    user=Depends(require_auth),
    session: AsyncSession = Depends(get_session),
):
    """Authenticated: Get licenses for the current logged-in agent."""
    user_id = user.get("user_id") or user.get("sub") or "dev-mode"

    result = await session.execute(
        select(DBLicense)
        .where(DBLicense.user_id == user_id)
        .order_by(DBLicense.state)
    )
    licenses = result.scalars().all()

    return [
        License(
            id=lic.id,
            state=lic.state,
            state_abbreviation=lic.state_abbreviation,
            license_number=lic.license_number,
            verify_url=lic.verify_url,
            needs_manual_verification=lic.needs_manual_verification,
            status=lic.status,
            license_type=lic.license_type,
        )
        for lic in licenses
    ]


@router.post("", response_model=License, status_code=status.HTTP_201_CREATED)
@router.post("/", response_model=License, status_code=status.HTTP_201_CREATED, include_in_schema=False)
async def create_license(
    license_data: LicenseCreate,
    user=Depends(require_auth),
    session: AsyncSession = Depends(get_session),
):
    """Authenticated: Add a new license for the current agent.

    If verify_url is not provided, it is auto-generated based on the state:
    - NAIC SOLAR states: deep-link via NPN
    - FL: one-time automated lookup via fl_license_lookup
    - Other states: state portal URL
    """
    user_id = user.get("user_id") or user.get("sub") or "dev-mode"
    state = license_data.state_abbreviation.upper()

    # --- Bug 4 fix: prevent duplicate state for same user ---
    existing = await session.execute(
        select(DBLicense).where(
            DBLicense.user_id == user_id,
            DBLicense.state_abbreviation == state,
        )
    )
    if existing.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"You already have a license for {state}. Edit the existing one instead.",
        )

    # --- Feature 2: require license number for manual-verification states ---
    if state in REQUIRE_LICENSE_NUMBER_STATES and not license_data.license_number:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"License number is required for {state}. Consumers need it to verify your license.",
        )

    verify_url = license_data.verify_url
    manual = license_data.needs_manual_verification

    # Auto-generate verify URL if not provided
    if not verify_url:
        # --- Bug 1 fix: look up NPN from agents table, not JWT ---
        npn = await _get_agent_npn(session, user_id)

        if state == "FL":
            # FL requires a one-time web lookup to resolve the direct permalink
            try:
                from fl_license_lookup import lookup_fl_direct_url_safe

                fl_url = await asyncio.to_thread(
                    lookup_fl_direct_url_safe,
                    fl_license_number=license_data.license_number,
                )
                from constants_licenses import FL_DFS_SEARCH_URL

                verify_url = fl_url or FL_DFS_SEARCH_URL
                manual = not bool(fl_url)
            except Exception as e:
                logger.warning("FL license lookup failed: %s", e)
                from constants_licenses import FL_DFS_SEARCH_URL

                verify_url = FL_DFS_SEARCH_URL
                manual = True
        else:
            verify_url = (
                _get_verify_url(
                    state,
                    npn=npn,
                    license_number=license_data.license_number,
                )
                or ""
            )
            manual = _needs_manual_verification(state)

    new_license = DBLicense(
        user_id=user_id,
        state=license_data.state,
        state_abbreviation=state,
        license_number=license_data.license_number,
        verify_url=verify_url,
        needs_manual_verification=manual,
        status=license_data.status,
        license_type=license_data.license_type,
    )
    session.add(new_license)
    # Flush to get the auto-generated ID before returning
    await session.flush()

    logger.info(
        "License created: user=%s state=%s id=%d",
        user_id,
        state,
        new_license.id,
    )

    return License(
        id=new_license.id,
        state=new_license.state,
        state_abbreviation=new_license.state_abbreviation,
        license_number=new_license.license_number,
        verify_url=new_license.verify_url,
        needs_manual_verification=new_license.needs_manual_verification,
        status=new_license.status,
        license_type=new_license.license_type,
    )


@router.put("/{license_id}", response_model=License)
async def update_license(
    license_id: int,
    license_data: LicenseUpdate,
    user=Depends(require_auth),
    session: AsyncSession = Depends(get_session),
):
    """Authenticated: Update an existing license.

    Only the license owner can update their own licenses.
    If state changes, verify_url and needs_manual_verification are regenerated.
    """
    user_id = user.get("user_id") or user.get("sub") or "dev-mode"

    result = await session.execute(
        select(DBLicense).where(
            DBLicense.id == license_id,
            DBLicense.user_id == user_id,
        )
    )
    license_obj = result.scalar_one_or_none()

    if not license_obj:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="License not found",
        )

    old_state = license_obj.state_abbreviation

    update_data = license_data.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(license_obj, key, value)

    # --- Bug 3 fix: regenerate verify_url if state changed ---
    new_state = license_obj.state_abbreviation
    if new_state and new_state != old_state:
        npn = await _get_agent_npn(session, user_id)
        new_state_upper = new_state.upper()

        if new_state_upper == "FL":
            try:
                from fl_license_lookup import lookup_fl_direct_url_safe
                fl_url = await asyncio.to_thread(
                    lookup_fl_direct_url_safe,
                    fl_license_number=license_obj.license_number,
                )
                from constants_licenses import FL_DFS_SEARCH_URL
                license_obj.verify_url = fl_url or FL_DFS_SEARCH_URL
                license_obj.needs_manual_verification = not bool(fl_url)
            except Exception as e:
                logger.warning("FL license lookup failed on edit: %s", e)
                from constants_licenses import FL_DFS_SEARCH_URL
                license_obj.verify_url = FL_DFS_SEARCH_URL
                license_obj.needs_manual_verification = True
        else:
            license_obj.verify_url = (
                _get_verify_url(
                    new_state_upper,
                    npn=npn,
                    license_number=license_obj.license_number,
                )
                or ""
            )
            license_obj.needs_manual_verification = _needs_manual_verification(new_state_upper)

    logger.info("License updated: id=%d user=%s", license_id, user_id)

    return License(
        id=license_obj.id,
        state=license_obj.state,
        state_abbreviation=license_obj.state_abbreviation,
        license_number=license_obj.license_number,
        verify_url=license_obj.verify_url,
        needs_manual_verification=license_obj.needs_manual_verification,
        status=license_obj.status,
        license_type=license_obj.license_type,
    )


@router.delete("/{license_id}")
async def delete_license(
    license_id: int,
    user=Depends(require_auth),
    session: AsyncSession = Depends(get_session),
):
    """Authenticated: Delete a license.

    Only the license owner can delete their own licenses.
    """
    user_id = user.get("user_id") or user.get("sub") or "dev-mode"

    result = await session.execute(
        select(DBLicense).where(
            DBLicense.id == license_id,
            DBLicense.user_id == user_id,
        )
    )
    license_obj = result.scalar_one_or_none()

    if not license_obj:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="License not found",
        )

    await session.delete(license_obj)
    logger.info("License deleted: id=%d user=%s", license_id, user_id)

    return {"message": "License deleted successfully"}


# ---------------------------------------------------------------------------
# Health check endpoint (Feature 1)
# ---------------------------------------------------------------------------

@router.post("/health-check", response_model=List[UrlHealth])
async def health_check_verify_urls(
    payload: HealthCheckRequest,
    user=Depends(require_auth),
):
    """Authenticated: Check if verify URLs are reachable.

    Does HEAD requests to each URL and returns ok/not-ok status.
    Used by the frontend to show green/red dots next to Verify links.
    """
    async def check_url(url: str) -> UrlHealth:
        headers = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/120.0 Safari/537.36"}
        try:
            async with httpx.AsyncClient(timeout=10, follow_redirects=True, verify=False, headers=headers) as client:
                resp = await client.head(url)
                # 403/405 = site is up but blocks server-side requests (NAIC SOLAR, state DOI)
                # Only mark red on 5xx (broken server) — 4xx means the server responded fine
                if resp.status_code < 500:
                    return UrlHealth(url=url, ok=True)
                # Try GET as fallback for HEAD-blocking servers
                resp2 = await client.get(url)
                return UrlHealth(url=url, ok=resp2.status_code < 500)
        except Exception:
            return UrlHealth(url=url, ok=False)

    results = await asyncio.gather(*[check_url(u) for u in payload.urls])
    return list(results)
