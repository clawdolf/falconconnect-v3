"""Public agents router — serves agent profile data to FalconVerify (falconfinancial.org)."""

from fastapi import APIRouter, HTTPException
from sqlalchemy import select
from db.database import get_session
from db.models import DBLicense
from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

router = APIRouter()

# Seb's static profile — single agent for now
SEB_PROFILE = {
    "name": "Sébastien Taillieu",
    "slug": "seb",
    "bio": "Independent life insurance broker with access to 47+ A-rated carriers. Specializing in mortgage protection, term life, IUL, and final expense coverage.",
    "photo_url": None,
    "phone": None,
    "email": None,
    "calendar_url": None,
    "npn": "21408357",
}

SEB_USER_ID = "72dc5b7c-ba2c-4a1d-83b9-733ff600c0d5"


@router.get("/agents")
async def list_agents():
    """List all public agents."""
    return [SEB_PROFILE]


@router.get("/agents/{slug}")
async def get_agent_profile(slug: str, session: AsyncSession = Depends(get_session)):
    """Get full agent profile including licenses and testimonials."""
    if slug != "seb":
        raise HTTPException(status_code=404, detail="Agent not found")

    # Fetch licenses from DB
    result = await session.execute(
        select(DBLicense).where(
            DBLicense.user_id == SEB_USER_ID,
            DBLicense.status == "active",
        ).order_by(DBLicense.state)
    )
    db_licenses = result.scalars().all()

    licenses = [
        {
            "id": lic.id,
            "state": lic.state,
            "abbreviation": lic.state_abbreviation,
            "license_number": lic.license_number,
            "licenseNumber": lic.license_number,
            "verify_url": lic.verify_url,
            "verifyUrl": lic.verify_url,
            "needs_manual_verification": lic.needs_manual_verification,
            "needsManualVerification": lic.needs_manual_verification,
            "status": lic.status,
        }
        for lic in db_licenses
    ]

    return {
        "agent": SEB_PROFILE,
        "licenses": licenses,
        "testimonials": [],
    }
