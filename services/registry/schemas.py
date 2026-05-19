from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict


class RegistryHouseholdOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    display_name: str
    status: str
    risk_level: str
    confidence: Optional[float] = None
    primary_phone: Optional[str] = None
    primary_email: Optional[str] = None
    derived_from: Optional[str] = None
    updated_at: Optional[datetime] = None


class RegistryPersonOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    household_id: int
    display_name: str
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    role: Optional[str] = None
    dnc_status: Optional[str] = None
    consent_status: Optional[str] = None


class RegistryContactMethodOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    household_id: int
    person_id: Optional[int] = None
    kind: str
    raw_value: str
    normalized_value: str
    validity_status: Optional[str] = None
    consent_status: Optional[str] = None
    is_primary: Optional[bool] = None


class RegistryExternalRecordOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    household_id: Optional[int] = None
    person_id: Optional[int] = None
    contact_method_id: Optional[int] = None
    source: str
    external_type: str
    external_id: str
    match_basis: Optional[str] = None
    match_confidence: Optional[float] = None
    match_reason: Optional[str] = None


class RegistryRecommendationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    household_id: int
    person_id: Optional[int] = None
    recommendation_type: str
    status: str
    risk_level: str
    confidence: Optional[float] = None
    evidence: Optional[dict[str, Any]] = None
    proposed_at: Optional[datetime] = None


class RegistryConsentEventOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    household_id: int
    person_id: Optional[int] = None
    contact_method_id: Optional[int] = None
    external_record_id: Optional[int] = None
    event_type: str
    source: str
    evidence: Optional[str] = None
    occurred_at: Optional[datetime] = None
    observed_at: Optional[datetime] = None


class RegistryHouseholdDetail(RegistryHouseholdOut):
    people: list[RegistryPersonOut] = []
    contact_methods: list[RegistryContactMethodOut] = []
    external_records: list[RegistryExternalRecordOut] = []
    recommendations: list[RegistryRecommendationOut] = []
    consent_events: list[RegistryConsentEventOut] = []


class RegistryPersonDetail(RegistryPersonOut):
    household: Optional[RegistryHouseholdOut] = None
    contact_methods: list[RegistryContactMethodOut] = []
    external_records: list[RegistryExternalRecordOut] = []
    recommendations: list[RegistryRecommendationOut] = []
    consent_events: list[RegistryConsentEventOut] = []


class RegistryImportSummary(BaseModel):
    job_id: str
    rows_seen: int
    households_created: int
    people_created: int
    contact_methods_created: int
    external_records_created: int
    snapshots_created: int
    recommendations_created: int
    consent_events_created: int


class RegistryLeadHygieneReportOut(BaseModel):
    job_id: str
    short_job_id: str
    label: str
    display_name: str
    status: str
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
    rows_seen: Optional[int] = None
    source_label: Optional[str] = None
    has_json_report: bool
    importable: bool


class RegistryConnectionStatus(BaseModel):
    source: str
    configured: bool
    mode: str
    secret: str = "masked"
