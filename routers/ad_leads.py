"""Public ad lead capture — receives form submissions from Meta/Google ad landing pages.

Creates leads directly in Close.com with full UTM attribution.
No auth required — this endpoint is hit by public landing page forms.
"""

import logging
from typing import Optional

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field

from services import close_client

logger = logging.getLogger("falconconnect.ad_leads")

router = APIRouter()


# ── Request / Response Models ──


class AdLeadPayload(BaseModel):
    """Payload for POST /api/public/leads/capture/ad — ad landing page form submission."""

    first_name: str = Field(..., min_length=1, max_length=128)
    last_name: str = Field(..., min_length=1, max_length=128)
    email: Optional[str] = Field(None, max_length=256)
    phone: str = Field(..., min_length=7, max_length=40)
    state: Optional[str] = Field(None, max_length=64)
    age: Optional[int] = Field(None, ge=18, le=120)
    is_homeowner: Optional[bool] = None
    coverage_interest: Optional[str] = Field(None, max_length=64)

    # UTM attribution (all optional — form may not capture all)
    utm_source: Optional[str] = Field(None, max_length=128)
    utm_medium: Optional[str] = Field(None, max_length=128)
    utm_campaign: Optional[str] = Field(None, max_length=256)
    utm_content: Optional[str] = Field(None, max_length=256)
    ad_platform: Optional[str] = Field(None, max_length=64)
    lead_form_variant: Optional[str] = Field(None, max_length=128)


class AdLeadResponse(BaseModel):
    """Response from ad lead capture endpoint."""

    success: bool
    lead_id: str


# ── Endpoint ──


@router.post(
    "/leads/capture/ad",
    response_model=AdLeadResponse,
    status_code=status.HTTP_201_CREATED,
)
async def capture_ad_lead(payload: AdLeadPayload):
    """Capture a lead from an ad landing page — writes to Close.com.

    Public endpoint (no auth). Called by falconfinancial.org landing page forms.
    """
    try:
        result = await close_client.create_lead(
            first_name=payload.first_name,
            last_name=payload.last_name,
            email=payload.email,
            phone=payload.phone,
            state=payload.state,
            age=payload.age,
            is_homeowner=payload.is_homeowner,
            coverage_interest=payload.coverage_interest,
            utm_source=payload.utm_source,
            utm_medium=payload.utm_medium,
            utm_campaign=payload.utm_campaign,
            utm_content=payload.utm_content,
            ad_platform=payload.ad_platform,
            lead_form_variant=payload.lead_form_variant,
        )

        logger.info(
            "Ad lead captured: %s %s → Close:%s (source=%s, campaign=%s)",
            payload.first_name,
            payload.last_name,
            result["lead_id"],
            payload.utm_source or "unknown",
            payload.utm_campaign or "unknown",
        )

        return AdLeadResponse(
            success=True,
            lead_id=result["lead_id"],
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
