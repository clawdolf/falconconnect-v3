"""Public ad lead capture — receives form submissions from Meta / Google / TikTok
ad landing pages and writes them into Close.com with full attribution and a
TCPA-compliant consent audit trail.

Public endpoint — no Clerk auth. Bot protection: Cloudflare Turnstile +
hidden honeypot + slowapi rate limit.
"""

import logging
from typing import Optional

from fastapi import APIRouter, HTTPException, Request, status
from pydantic import BaseModel, Field

from services import close_client
from utils.rate_limit import limiter
from utils.turnstile import verify_turnstile

logger = logging.getLogger("falconconnect.ad_leads")

router = APIRouter()


# ── Request / Response Models ──


class AdLeadPayload(BaseModel):
    """Payload for POST /api/public/leads/capture/ad."""

    first_name: str = Field(..., min_length=1, max_length=128)
    last_name: str = Field(..., min_length=1, max_length=128)
    email: Optional[str] = Field(None, max_length=256)
    phone: str = Field(..., min_length=7, max_length=40)
    state: Optional[str] = Field(None, max_length=64)
    age: Optional[int] = Field(None, ge=18, le=120)
    coverage_interest: Optional[str] = Field(None, max_length=64)

    # TCPA / A2P SMS consent — single combined opt-in. Must be true to submit.
    sms_consent: bool = False

    # UTM attribution (all optional — form may not capture all)
    utm_source: Optional[str] = Field(None, max_length=128)
    utm_medium: Optional[str] = Field(None, max_length=128)
    utm_campaign: Optional[str] = Field(None, max_length=256)
    utm_content: Optional[str] = Field(None, max_length=256)
    ad_platform: Optional[str] = Field(None, max_length=64)
    lead_form_variant: Optional[str] = Field(None, max_length=128)

    # Per-click attribution IDs — from the ad networks
    fbclid: Optional[str] = Field(None, max_length=512)
    gclid: Optional[str] = Field(None, max_length=512)
    ttclid: Optional[str] = Field(None, max_length=512)

    # Full landing page URL at the moment of submission
    landing_page_url: Optional[str] = Field(None, max_length=2048)

    # Bot protection
    turnstile_token: Optional[str] = Field(None, max_length=4096)
    # Honeypot — real users leave this empty. Bots filling "all fields" trip 422.
    website: Optional[str] = Field(None, max_length=0)


class AdLeadResponse(BaseModel):
    """Response from ad lead capture endpoint."""

    success: bool
    lead_id: str
    duplicate: bool = False


# ── Endpoint ──


@router.post(
    "/leads/capture/ad",
    response_model=AdLeadResponse,
    status_code=status.HTTP_201_CREATED,
)
@limiter.limit("5/minute;30/hour")
async def capture_ad_lead(request: Request, payload: AdLeadPayload):
    """Capture a lead from an ad landing page — writes to Close.com.

    Public endpoint (no auth). Called by falconfinancial.org landing page forms.
    """
    client_ip = request.headers.get("CF-Connecting-IP") or (
        request.headers.get("X-Forwarded-For", "").split(",")[0].strip() or None
    )

    if not await verify_turnstile(payload.turnstile_token, client_ip):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Bot verification failed.",
        )

    # Enforce TCPA opt-in at the API edge too, not just in the UI.
    if not payload.sms_consent:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Consent is required to submit this form.",
        )

    try:
        result = await close_client.create_lead(
            first_name=payload.first_name,
            last_name=payload.last_name,
            email=payload.email,
            phone=payload.phone,
            state=payload.state,
            age=payload.age,
            coverage_interest=payload.coverage_interest,
            utm_source=payload.utm_source,
            utm_medium=payload.utm_medium,
            utm_campaign=payload.utm_campaign,
            utm_content=payload.utm_content,
            ad_platform=payload.ad_platform,
            lead_form_variant=payload.lead_form_variant,
            sms_consent=payload.sms_consent,
            consent_ip=client_ip,
            fbclid=payload.fbclid,
            gclid=payload.gclid,
            ttclid=payload.ttclid,
            landing_page_url=payload.landing_page_url,
        )

        logger.info(
            "Ad lead %s: %s %s → Close:%s (source=%s, campaign=%s, variant=%s)",
            "deduped" if result.get("duplicate") else "captured",
            payload.first_name,
            payload.last_name,
            result["lead_id"],
            payload.utm_source or "unknown",
            payload.utm_campaign or "unknown",
            payload.lead_form_variant or "unknown",
        )

        return AdLeadResponse(
            success=True,
            lead_id=result["lead_id"],
            duplicate=bool(result.get("duplicate")),
        )

    except Exception as exc:
        logger.error(
            "Failed to capture ad lead %s %s: %s",
            payload.first_name,
            payload.last_name,
            exc,
        )
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Failed to create lead in CRM: {exc}",
        )
