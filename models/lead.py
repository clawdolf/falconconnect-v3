"""Pydantic models for lead intake."""

from datetime import date
from typing import Optional

from pydantic import BaseModel, Field


class LeadPayload(BaseModel):
    """Payload for POST /api/public/leads/capture."""

    first_name: str = Field(..., min_length=1, max_length=128)
    last_name: str = Field(..., min_length=1, max_length=128)
    phone: str = Field(..., min_length=7, max_length=40)
    email: Optional[str] = Field(None, max_length=256)
    address: Optional[str] = Field(None, max_length=512)
    city: Optional[str] = Field(None, max_length=128)
    state: Optional[str] = Field(None, max_length=2)
    zip_code: Optional[str] = Field(None, max_length=10)
    birth_year: Optional[int] = Field(None, ge=1900, le=2026)
    mail_date: Optional[date] = None
    lead_source: Optional[str] = Field(None, max_length=64)
    source: Optional[str] = Field(None, max_length=64)  # alias — deprecated, use lead_source
    segment: Optional[str] = Field("Never Worked", max_length=64)
    lender: Optional[str] = Field(None, max_length=128)
    loan_amount: Optional[str] = Field(None, max_length=32)
    home_phone: Optional[str] = Field(None, max_length=40)
    mobile_phone: Optional[str] = Field(None, max_length=40)
    spouse_phone: Optional[str] = Field(None, max_length=40)
    notes: Optional[str] = Field(None, max_length=2000)


class LeadCaptureResponse(BaseModel):
    """Response from lead capture endpoint."""

    ghl_id: str
    notion_id: str
    age: Optional[int] = None
    lage_months: Optional[int] = None
    status: str = "captured"
