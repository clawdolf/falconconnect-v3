"""Public agents router — serves agent profile data to FalconVerify (falconfinancial.org).

Also provides admin endpoints for managing agent profiles and testimonials.
"""

import json
import logging
from typing import Dict, Any

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from db.database import get_session
from db.models import DBAgent, DBLicense, DBTestimonial
from middleware.auth import require_auth
from models.agent import (
    AgentUpdate,
    TestimonialCreate,
    TestimonialUpdate,
)

logger = logging.getLogger("falconconnect.agents")

router = APIRouter()


# ---------------------------------------------------------------------------
# Public endpoints (no auth required)
# ---------------------------------------------------------------------------


@router.get("/agents")
async def list_agents(session: AsyncSession = Depends(get_session)):
    """List all active public agents, including live license count and state abbreviations."""
    from db.models import License as DBLicense
    from sqlalchemy import func

    result = await session.execute(
        select(DBAgent).where(DBAgent.is_active == True).order_by(DBAgent.name)
    )
    agents = result.scalars().all()

    # Fetch active licenses for all agents in one query
    license_result = await session.execute(
        select(DBLicense.agent_id, DBLicense.state_abbreviation)
        .where(DBLicense.status == "active")
    )
    license_rows = license_result.all()

    # Build map: agent_id → sorted list of abbreviations
    from collections import defaultdict
    agent_licenses: dict[int, list[str]] = defaultdict(list)
    for agent_id, abbr in license_rows:
        if abbr:
            agent_licenses[agent_id].append(abbr)
    for k in agent_licenses:
        agent_licenses[k] = sorted(agent_licenses[k])

    return [
        {
            "name": a.name,
            "slug": a.slug,
            "title": a.title,
            "bio": a.bio,
            "photo_url": a.photo_url,
            "phone": a.phone,
            "phone_display": a.phone_display,
            "email": a.email,
            "npn": a.npn,
            "location": a.location,
            "carrier_count": a.carrier_count,
            "license_count": len(agent_licenses[a.id]),
            "licensed_states": agent_licenses[a.id],
        }
        for a in agents
    ]


@router.get("/agents/{slug}")
async def get_agent_profile(slug: str, session: AsyncSession = Depends(get_session)):
    """Get full agent profile including licenses and testimonials."""
    # Query agent from DB
    agent_result = await session.execute(
        select(DBAgent).where(DBAgent.slug == slug, DBAgent.is_active == True)
    )
    agent = agent_result.scalar_one_or_none()
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")

    # Fetch licenses
    license_result = await session.execute(
        select(DBLicense).where(
            DBLicense.user_id == agent.user_id,
            DBLicense.status == "active",
        ).order_by(DBLicense.state)
    )
    db_licenses = license_result.scalars().all()

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

    # Fetch published testimonials
    testimonial_result = await session.execute(
        select(DBTestimonial).where(
            DBTestimonial.agent_id == agent.id,
            DBTestimonial.is_published == True,
        ).order_by(DBTestimonial.sort_order, DBTestimonial.created_at.desc())
    )
    testimonials = testimonial_result.scalars().all()

    # Parse carriers JSON
    carriers = []
    if agent.carriers_json:
        try:
            carriers = json.loads(agent.carriers_json)
        except (json.JSONDecodeError, TypeError):
            pass

    return {
        "agent": {
            "name": agent.name,
            "slug": agent.slug,
            "title": agent.title,
            "bio": agent.bio,
            "photo_url": agent.photo_url,
            "phone": agent.phone,
            "phone_display": agent.phone_display,
            "email": agent.email,
            "calendar_url": agent.calendar_url,
            "npn": agent.npn,
            "location": agent.location,
            "carrier_count": agent.carrier_count,
            "carriers": carriers,
        },
        "licenses": licenses,
        "testimonials": [
            {
                "id": t.id,
                "client_name": t.client_name,
                "text": t.text,
                "rating": t.rating,
                "date": t.date.isoformat() if t.date else None,
            }
            for t in testimonials
        ],
    }


# ---------------------------------------------------------------------------
# Admin endpoints (auth-gated)
# ---------------------------------------------------------------------------


async def _get_agent_by_slug(
    slug: str, session: AsyncSession
) -> DBAgent:
    """Helper — resolve agent by slug or 404."""
    result = await session.execute(
        select(DBAgent).where(DBAgent.slug == slug)
    )
    agent = result.scalar_one_or_none()
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")
    return agent


@router.put("/agents/{slug}/profile")
async def update_agent_profile(
    slug: str,
    body: AgentUpdate,
    session: AsyncSession = Depends(get_session),
    user: Dict[str, Any] = Depends(require_auth),
):
    """Update agent profile fields (admin only)."""
    agent = await _get_agent_by_slug(slug, session)

    update_data = body.model_dump(exclude_unset=True)
    if not update_data:
        return {"ok": True, "message": "No changes"}

    await session.execute(
        update(DBAgent).where(DBAgent.id == agent.id).values(**update_data)
    )
    logger.info("Agent %s profile updated by user %s: %s", slug, user.get("user_id"), list(update_data.keys()))
    return {"ok": True, "updated": list(update_data.keys())}


@router.get("/agents/{slug}/testimonials")
async def list_testimonials(
    slug: str,
    session: AsyncSession = Depends(get_session),
    user: Dict[str, Any] = Depends(require_auth),
):
    """List ALL testimonials for an agent (including unpublished) — admin only."""
    agent = await _get_agent_by_slug(slug, session)

    result = await session.execute(
        select(DBTestimonial)
        .where(DBTestimonial.agent_id == agent.id)
        .order_by(DBTestimonial.sort_order, DBTestimonial.created_at.desc())
    )
    testimonials = result.scalars().all()
    return [
        {
            "id": t.id,
            "client_name": t.client_name,
            "text": t.text,
            "rating": t.rating,
            "date": t.date.isoformat() if t.date else None,
            "is_published": t.is_published,
            "sort_order": t.sort_order,
        }
        for t in testimonials
    ]


@router.post("/agents/{slug}/testimonials", status_code=201)
async def create_testimonial(
    slug: str,
    body: TestimonialCreate,
    session: AsyncSession = Depends(get_session),
    user: Dict[str, Any] = Depends(require_auth),
):
    """Add a new testimonial for an agent (admin only)."""
    agent = await _get_agent_by_slug(slug, session)

    testimonial = DBTestimonial(
        agent_id=agent.id,
        client_name=body.client_name,
        text=body.text,
        rating=body.rating,
        date=body.date,
    )
    session.add(testimonial)
    await session.flush()
    logger.info("Testimonial %d created for agent %s by user %s", testimonial.id, slug, user.get("user_id"))
    return {"ok": True, "id": testimonial.id}


@router.put("/agents/{slug}/testimonials/{testimonial_id}")
async def update_testimonial(
    slug: str,
    testimonial_id: int,
    body: TestimonialUpdate,
    session: AsyncSession = Depends(get_session),
    user: Dict[str, Any] = Depends(require_auth),
):
    """Update an existing testimonial (admin only)."""
    agent = await _get_agent_by_slug(slug, session)

    result = await session.execute(
        select(DBTestimonial).where(
            DBTestimonial.id == testimonial_id,
            DBTestimonial.agent_id == agent.id,
        )
    )
    testimonial = result.scalar_one_or_none()
    if not testimonial:
        raise HTTPException(status_code=404, detail="Testimonial not found")

    update_data = body.model_dump(exclude_unset=True)
    if not update_data:
        return {"ok": True, "message": "No changes"}

    await session.execute(
        update(DBTestimonial)
        .where(DBTestimonial.id == testimonial_id)
        .values(**update_data)
    )
    logger.info("Testimonial %d updated by user %s", testimonial_id, user.get("user_id"))
    return {"ok": True, "updated": list(update_data.keys())}


@router.delete("/agents/{slug}/testimonials/{testimonial_id}")
async def delete_testimonial(
    slug: str,
    testimonial_id: int,
    session: AsyncSession = Depends(get_session),
    user: Dict[str, Any] = Depends(require_auth),
):
    """Soft-delete a testimonial (set is_published=false) — admin only."""
    agent = await _get_agent_by_slug(slug, session)

    result = await session.execute(
        select(DBTestimonial).where(
            DBTestimonial.id == testimonial_id,
            DBTestimonial.agent_id == agent.id,
        )
    )
    testimonial = result.scalar_one_or_none()
    if not testimonial:
        raise HTTPException(status_code=404, detail="Testimonial not found")

    await session.execute(
        update(DBTestimonial)
        .where(DBTestimonial.id == testimonial_id)
        .values(is_published=False)
    )
    logger.info("Testimonial %d soft-deleted by user %s", testimonial_id, user.get("user_id"))
    return {"ok": True, "message": "Testimonial unpublished"}
