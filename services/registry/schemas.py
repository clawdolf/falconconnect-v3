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
    people_count: int = 0
    contact_method_count: int = 0
    phone_count: int = 0
    email_count: int = 0
    address_count: int = 0
    sources: list[str] = []
    source_count: int = 0
    recommendation_count: int = 0
    high_risk_recommendation_count: int = 0
    dnc_event_count: int = 0
    hard_stop_count: int = 0
    bucket_counts: dict[str, int] = {}
    latest_seen_at: Optional[datetime] = None
    latest_source_label: Optional[str] = None


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


class RegistrySankeyNode(BaseModel):
    id: str
    label: str
    column: str
    count: int


class RegistrySankeyLink(BaseModel):
    source: str
    target: str
    value: int


class RegistrySankeyTotals(BaseModel):
    households: int
    people: int
    contact_methods: int
    recommendations: int
    links: int


class RegistrySourceCoverage(BaseModel):
    source: str
    label: str
    total: int
    matched: int
    missing: int
    match_pct: float


class RegistrySankeyOut(BaseModel):
    generated_at: datetime
    level: str
    filters: dict[str, Any]
    nodes: list[RegistrySankeyNode]
    links: list[RegistrySankeyLink]
    totals: RegistrySankeyTotals
    source_coverage: list[RegistrySourceCoverage] = []
    coverage_universe: int = 0
    truncated: bool = False
