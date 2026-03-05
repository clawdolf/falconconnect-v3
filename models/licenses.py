"""Pydantic models for license endpoints."""

from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class LicenseStatus(str, Enum):
    ACTIVE = "active"
    EXPIRED = "expired"
    PENDING = "pending"
    SUSPENDED = "suspended"


class License(BaseModel):
    """Public license model for consumer portal (FalconVerify)."""

    id: int
    state: str
    state_abbreviation: str
    license_number: Optional[str] = None
    verify_url: Optional[str] = None
    needs_manual_verification: bool = False
    status: str = "active"
    license_type: str = "insurance_producer"


class LicenseCreate(BaseModel):
    """License creation model for agent portal.

    verify_url is optional — if not provided, it will be auto-generated
    based on the state (NAIC SOLAR for most states, state portal for others).
    """

    state: str = Field(..., min_length=2, max_length=64)
    state_abbreviation: str = Field(..., min_length=2, max_length=2)
    license_number: Optional[str] = Field(None, max_length=64)
    verify_url: Optional[str] = None
    needs_manual_verification: bool = False
    status: str = "active"
    license_type: str = "insurance_producer"


class LicenseUpdate(BaseModel):
    """License update model for agent portal."""

    state: Optional[str] = None
    state_abbreviation: Optional[str] = None
    license_number: Optional[str] = None
    verify_url: Optional[str] = None
    needs_manual_verification: Optional[bool] = None
    status: Optional[str] = None
    license_type: Optional[str] = None


class StateVerifyInfo(BaseModel):
    """Verification system info for a state."""

    state: str
    state_name: str
    uses_solar: bool
    is_fl_dfs: bool
    portal_url: Optional[str] = None
    needs_manual: bool
    needs_lookup: bool
    system: str
