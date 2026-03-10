"""Campaign endpoints — Meta Ads campaign management and ad copy optimization."""

import json
import logging
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Body
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from db.database import get_session
from db.models import Campaign, CampaignVariant
from middleware.auth import require_auth

logger = logging.getLogger("falconconnect.campaigns")

router = APIRouter()


# ── Hardcoded variant templates (used when Anthropic API is unavailable) ──

VARIANT_TEMPLATES = {
    "Mortgage Protection": {
        "fear": {
            "variant_name": "Fear — Family at Risk",
            "headline": "What Happens to Your Family's Home If Something Happens to You?",
            "body_copy": (
                "Your mortgage doesn't disappear when you do. Without protection, "
                "your family could lose the home you worked so hard to provide. "
                "Most families are one missed paycheck away from foreclosure after "
                "losing a breadwinner. Don't leave them with that burden."
            ),
            "cta_text": "Protect Your Family Now",
        },
        "math": {
            "variant_name": "Math — The Numbers",
            "headline": "For Less Than $1/Day, Your Mortgage Is Paid Off — No Matter What",
            "body_copy": (
                "The average mortgage protection policy costs less than your daily coffee. "
                "For as little as $28/month, your $300K mortgage is covered if you pass away, "
                "become disabled, or face a critical illness. Your family keeps the house, free and clear."
            ),
            "cta_text": "See Your Rate in 30 Seconds",
        },
        "social_proof": {
            "variant_name": "Social Proof — Real Families",
            "headline": "Join 2,400+ Arizona Homeowners Who Protected Their Families This Year",
            "body_copy": (
                "Every day, smart homeowners are locking in affordable mortgage protection "
                "while rates are still low. Your neighbors already have coverage — "
                "their families won't lose their homes no matter what happens. "
                "Don't be the one who waited too long."
            ),
            "cta_text": "Get My Free Quote",
        },
        "urgency": {
            "variant_name": "Urgency — Rates Rising",
            "headline": "Mortgage Protection Rates Are Going Up March 31st — Lock Yours In Today",
            "body_copy": (
                "Insurance carriers are raising rates across the board. "
                "The younger and healthier you are today, the less you'll pay — forever. "
                "Every day you wait costs you money. A 5-minute call could save your family's home."
            ),
            "cta_text": "Lock In My Rate Before It Goes Up",
        },
    },
    "Life Insurance": {
        "fear": {
            "variant_name": "Fear — Unprotected Family",
            "headline": "If You Died Tomorrow, Could Your Family Survive Financially?",
            "body_copy": (
                "Most families can't cover 3 months of expenses after losing a loved one. "
                "Life insurance isn't about you — it's about making sure your kids stay in their school, "
                "your spouse keeps the house, and your family doesn't have to start a GoFundMe."
            ),
            "cta_text": "Get Protected Today",
        },
        "math": {
            "variant_name": "Math — Affordable Coverage",
            "headline": "$500,000 in Coverage for Less Than Your Netflix Subscription",
            "body_copy": (
                "A healthy 35-year-old can get $500K in term life coverage for under $25/month. "
                "That's less than what you spend on streaming. Your family's financial security "
                "shouldn't cost more than entertainment."
            ),
            "cta_text": "See My Rate",
        },
        "social_proof": {
            "variant_name": "Social Proof — Smart Families",
            "headline": "Why Thousands of Young Families Are Getting Covered Right Now",
            "body_copy": (
                "Smart parents don't wait until it's too late. They're locking in coverage "
                "while they're young and healthy, paying the lowest rates possible. "
                "Join the families who already have peace of mind."
            ),
            "cta_text": "Join Them — Get a Quote",
        },
        "urgency": {
            "variant_name": "Urgency — Health Changes",
            "headline": "One Doctor Visit Could Double Your Life Insurance Rate — Apply Healthy",
            "body_copy": (
                "Your health today determines your rate forever. A new diagnosis, a prescription, "
                "even elevated cholesterol can double or triple your premiums. "
                "Lock in your rate while your health is in your favor."
            ),
            "cta_text": "Apply While You're Healthy",
        },
    },
    "Final Expense": {
        "fear": {
            "variant_name": "Fear — Burden on Family",
            "headline": "Don't Leave Your Kids with a $15,000 Funeral Bill",
            "body_copy": (
                "The average funeral costs $12,000–$15,000. Without final expense coverage, "
                "that bill falls on your children. Many families go into debt or start GoFundMes "
                "just to bury a loved one. A small policy prevents that entirely."
            ),
            "cta_text": "Protect Your Family from the Cost",
        },
        "math": {
            "variant_name": "Math — Small Cost, Big Peace",
            "headline": "Cover Your Final Expenses for Less Than $1.50/Day",
            "body_copy": (
                "For around $40/month, you can guarantee your funeral, burial, and final debts "
                "are fully covered. No medical exam required for most applicants. "
                "Your family inherits peace of mind, not bills."
            ),
            "cta_text": "Get My Rate — No Exam Needed",
        },
        "social_proof": {
            "variant_name": "Social Proof — Responsible Planning",
            "headline": "Over 10,000 Seniors Locked In Final Expense Coverage This Month",
            "body_copy": (
                "More and more seniors are taking the responsible step of covering their final expenses. "
                "They're not leaving it to chance or burdening their kids. "
                "It takes one phone call to join them."
            ),
            "cta_text": "One Call — Covered for Life",
        },
        "urgency": {
            "variant_name": "Urgency — Age Matters",
            "headline": "Every Birthday Costs You More — Lock In Your Final Expense Rate Today",
            "body_copy": (
                "Final expense rates increase with every year of age. "
                "The coverage you can get today for $40/month might cost $65/month next year. "
                "There's no better time than right now to get covered."
            ),
            "cta_text": "Lock My Rate In Today",
        },
    },
}


@router.get("/meta/status")
async def meta_status(user=Depends(require_auth)):
    """Check if Meta Ads credentials are configured.

    Returns {"connected": false} until Meta credentials are set up.
    """
    return {"connected": False, "message": "Meta Ads integration not configured yet."}


@router.get("")
async def list_campaigns(
    session: AsyncSession = Depends(get_session),
    user=Depends(require_auth),
):
    """List all campaigns for the authenticated user."""
    result = await session.execute(
        select(Campaign)
        .where(Campaign.user_id == user["user_id"])
        .order_by(Campaign.created_at.desc())
    )
    campaigns = result.scalars().all()

    return {
        "count": len(campaigns),
        "campaigns": [
            {
                "id": c.id,
                "name": c.name,
                "status": c.status,
                "budget_daily": c.budget_daily,
                "budget_total": c.budget_total,
                "meta_campaign_id": c.meta_campaign_id,
                "strategy_json": json.loads(c.strategy_json) if c.strategy_json else None,
                "variant_count": len(c.variants) if c.variants else 0,
                "total_spend": sum(v.spend for v in c.variants) if c.variants else 0,
                "total_leads": sum(v.leads for v in c.variants) if c.variants else 0,
                "total_booked": sum(v.booked_appointments for v in c.variants) if c.variants else 0,
                "avg_cpl": (
                    round(sum(v.spend for v in c.variants) / max(sum(v.leads for v in c.variants), 1), 2)
                    if c.variants else 0
                ),
                "created_at": c.created_at.isoformat() if c.created_at else None,
                "updated_at": c.updated_at.isoformat() if c.updated_at else None,
            }
            for c in campaigns
        ],
    }


@router.post("")
async def create_campaign(
    body: dict = Body(...),
    session: AsyncSession = Depends(get_session),
    user=Depends(require_auth),
):
    """Create a new campaign (draft by default)."""
    name = body.get("name")
    if not name:
        raise HTTPException(status_code=400, detail="Campaign name is required.")

    strategy = body.get("strategy", {})
    target_audience = body.get("target_audience", {})
    status = body.get("status", "draft")

    campaign = Campaign(
        user_id=user["user_id"],
        name=name,
        status=status,
        strategy_json=json.dumps(strategy) if strategy else None,
        budget_daily=body.get("budget_daily", 0),
        budget_total=body.get("budget_total", 0),
        target_audience_json=json.dumps(target_audience) if target_audience else None,
    )
    session.add(campaign)
    await session.flush()

    # If variants were provided (from generate-variants), create them
    variants_data = body.get("variants", [])
    for v in variants_data:
        variant = CampaignVariant(
            campaign_id=campaign.id,
            variant_name=v.get("variant_name", "Untitled"),
            headline=v.get("headline", ""),
            body_copy=v.get("body_copy", ""),
            cta_text=v.get("cta_text", "Learn More"),
            angle=v.get("angle", "fear"),
        )
        session.add(variant)

    await session.flush()

    return {
        "id": campaign.id,
        "name": campaign.name,
        "status": campaign.status,
        "variant_count": len(variants_data),
        "created_at": campaign.created_at.isoformat() if campaign.created_at else None,
    }


@router.get("/{campaign_id}")
async def get_campaign(
    campaign_id: int,
    session: AsyncSession = Depends(get_session),
    user=Depends(require_auth),
):
    """Get campaign detail including all variants."""
    result = await session.execute(
        select(Campaign)
        .where(Campaign.id == campaign_id)
        .where(Campaign.user_id == user["user_id"])
    )
    campaign = result.scalar_one_or_none()
    if not campaign:
        raise HTTPException(status_code=404, detail="Campaign not found.")

    return {
        "id": campaign.id,
        "name": campaign.name,
        "status": campaign.status,
        "budget_daily": campaign.budget_daily,
        "budget_total": campaign.budget_total,
        "meta_campaign_id": campaign.meta_campaign_id,
        "meta_ad_account_id": campaign.meta_ad_account_id,
        "strategy_json": json.loads(campaign.strategy_json) if campaign.strategy_json else None,
        "target_audience_json": json.loads(campaign.target_audience_json) if campaign.target_audience_json else None,
        "created_at": campaign.created_at.isoformat() if campaign.created_at else None,
        "updated_at": campaign.updated_at.isoformat() if campaign.updated_at else None,
        "variants": [
            {
                "id": v.id,
                "variant_name": v.variant_name,
                "headline": v.headline,
                "body_copy": v.body_copy,
                "cta_text": v.cta_text,
                "angle": v.angle,
                "meta_ad_id": v.meta_ad_id,
                "impressions": v.impressions,
                "clicks": v.clicks,
                "leads": v.leads,
                "booked_appointments": v.booked_appointments,
                "spend": v.spend,
                "cpl": v.cpl,
                "status": v.status,
                "created_at": v.created_at.isoformat() if v.created_at else None,
            }
            for v in (campaign.variants or [])
        ],
    }


@router.put("/{campaign_id}/pause")
async def pause_campaign(
    campaign_id: int,
    session: AsyncSession = Depends(get_session),
    user=Depends(require_auth),
):
    """Pause an active campaign."""
    result = await session.execute(
        select(Campaign)
        .where(Campaign.id == campaign_id)
        .where(Campaign.user_id == user["user_id"])
    )
    campaign = result.scalar_one_or_none()
    if not campaign:
        raise HTTPException(status_code=404, detail="Campaign not found.")

    if campaign.status not in ("active", "draft"):
        raise HTTPException(status_code=400, detail=f"Cannot pause a {campaign.status} campaign.")

    campaign.status = "paused"
    return {"id": campaign.id, "status": "paused"}


@router.put("/{campaign_id}/resume")
async def resume_campaign(
    campaign_id: int,
    session: AsyncSession = Depends(get_session),
    user=Depends(require_auth),
):
    """Resume a paused campaign."""
    result = await session.execute(
        select(Campaign)
        .where(Campaign.id == campaign_id)
        .where(Campaign.user_id == user["user_id"])
    )
    campaign = result.scalar_one_or_none()
    if not campaign:
        raise HTTPException(status_code=404, detail="Campaign not found.")

    if campaign.status != "paused":
        raise HTTPException(status_code=400, detail=f"Cannot resume a {campaign.status} campaign.")

    campaign.status = "active"
    return {"id": campaign.id, "status": "active"}


@router.post("/generate-variants")
async def generate_variants(
    body: dict = Body(...),
    user=Depends(require_auth),
):
    """Generate ad copy variants for a campaign.

    Uses hardcoded templates by product type. Each product gets 4 variants
    covering angles: fear, math, social_proof, urgency.
    """
    product = body.get("product", "Mortgage Protection")
    target_states = body.get("target_states", "Arizona")

    templates = VARIANT_TEMPLATES.get(product, VARIANT_TEMPLATES["Mortgage Protection"])

    variants = []
    for angle, tmpl in templates.items():
        variants.append({
            "variant_name": tmpl["variant_name"],
            "headline": tmpl["headline"],
            "body_copy": tmpl["body_copy"],
            "cta_text": tmpl["cta_text"],
            "angle": angle,
        })

    return {
        "product": product,
        "target_states": target_states,
        "variant_count": len(variants),
        "variants": variants,
    }


@router.post("/optimize")
async def optimize_campaign(
    body: dict = Body(...),
    session: AsyncSession = Depends(get_session),
    user=Depends(require_auth),
):
    """Score campaign variants and flag losers (CPL > threshold).

    Returns optimization recommendations with replacement copy suggestions.
    """
    campaign_id = body.get("campaign_id")
    cpl_threshold = body.get("cpl_threshold", 80.0)

    if not campaign_id:
        raise HTTPException(status_code=400, detail="campaign_id is required.")

    result = await session.execute(
        select(Campaign)
        .where(Campaign.id == campaign_id)
        .where(Campaign.user_id == user["user_id"])
    )
    campaign = result.scalar_one_or_none()
    if not campaign:
        raise HTTPException(status_code=404, detail="Campaign not found.")

    winners = []
    losers = []
    needs_data = []

    for v in (campaign.variants or []):
        if v.status in ("killed", "paused"):
            continue

        if v.leads == 0 and v.spend < 50:
            needs_data.append({
                "id": v.id,
                "variant_name": v.variant_name,
                "angle": v.angle,
                "reason": "Not enough data yet — less than $50 spent and 0 leads.",
            })
            continue

        effective_cpl = v.spend / max(v.leads, 1)

        if effective_cpl > cpl_threshold:
            losers.append({
                "id": v.id,
                "variant_name": v.variant_name,
                "angle": v.angle,
                "cpl": round(effective_cpl, 2),
                "spend": v.spend,
                "leads": v.leads,
                "recommendation": "Kill or pause — CPL exceeds threshold.",
                "replacement_suggestion": f"Rewrite {v.angle} angle with stronger hook. Test new headline.",
            })
        elif effective_cpl <= 40:
            winners.append({
                "id": v.id,
                "variant_name": v.variant_name,
                "angle": v.angle,
                "cpl": round(effective_cpl, 2),
                "spend": v.spend,
                "leads": v.leads,
                "recommendation": "Scale — CPL under $40. Increase budget on this variant.",
            })
        else:
            winners.append({
                "id": v.id,
                "variant_name": v.variant_name,
                "angle": v.angle,
                "cpl": round(effective_cpl, 2),
                "spend": v.spend,
                "leads": v.leads,
                "recommendation": "Monitor — CPL acceptable but not elite.",
            })

    return {
        "campaign_id": campaign.id,
        "campaign_name": campaign.name,
        "cpl_threshold": cpl_threshold,
        "winners": winners,
        "losers": losers,
        "needs_data": needs_data,
        "summary": (
            f"{len(winners)} performing, {len(losers)} flagged for kill, "
            f"{len(needs_data)} need more data."
        ),
    }



