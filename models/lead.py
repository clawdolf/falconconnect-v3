"""Pydantic models for lead intake."""

from datetime import date
from typing import Optional

from pydantic import BaseModel, Field


class LeadPayload(BaseModel):
    """Payload for POST /api/public/leads/capture."""

    first_name: str = Field(..., min_length=1, max_length=128)
    last_name: str = Field(..., min_length=1, max_length=128)
    phone: str = Field(..., min_length=7, max_length=20)
    email: Optional[str] = Field(None, max_length=256)
    address: Optional[str] = Field(None, max_length=512)
    city: Optional[str] = Field(None, max_length=128)
    state: Optional[str] = Field(None, max_length=2)
    zip_code: Optional[str] = Field(None, max_length=10)
    birth_year: Optional[int] = Field(None, ge=1900, le=2026)
    mail_date: Optional[date] = None
    source: Optional[str] = Field("website", max_length=64)
    notes: Optional[str] = Field(None, max_length=2000)


class LeadCaptureResponse(BaseModel):
    """Response from lead capture endpoint."""

    ghl_id: str
    notion_id: str
    age: Optional[int] = None
    lage_months: Optional[int] = None
    status: str = "captured"
