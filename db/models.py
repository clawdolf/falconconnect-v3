"""ORM models — all tables live here."""

from datetime import datetime, date

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Date,
    Float,
    ForeignKey,
    Integer,
    JSON,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import DeclarativeBase, relationship


RegistryJSON = JSON().with_variant(JSONB, "postgresql")


class Base(DeclarativeBase):
    pass


class LeadXref(Base):
    """Maps GHL contact ID ↔ Notion page ID ↔ phone for cross-system lookups."""

    __tablename__ = "lead_xref"

    id: int = Column(Integer, primary_key=True, autoincrement=True)
    ghl_contact_id: str = Column(String(64), unique=True, nullable=False, index=True)
    close_lead_id: str = Column(String(64), nullable=True, index=True)
    notion_page_id: str = Column(String(64), unique=True, nullable=True, index=True)
    phone: str = Column(String(20), nullable=False, index=True)
    first_name: str = Column(String(128), nullable=True)
    last_name: str = Column(String(128), nullable=True)
    created_at: datetime = Column(DateTime(timezone=True), server_default=func.now())
    updated_at: datetime = Column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class SyncLog(Base):
    """Audit log for every GHL ↔ Notion sync event."""

    __tablename__ = "sync_log"

    id: int = Column(Integer, primary_key=True, autoincrement=True)
    event_type: str = Column(String(64), nullable=False, index=True)
    direction: str = Column(String(16), nullable=False)  # ghl_to_notion | notion_to_ghl
    source_id: str = Column(String(128), nullable=True)
    target_id: str = Column(String(128), nullable=True)
    payload: str = Column(Text, nullable=True)
    status: str = Column(String(16), nullable=False, default="ok")  # ok | error
    error_detail: str = Column(Text, nullable=True)
    created_at: datetime = Column(DateTime(timezone=True), server_default=func.now())


class AnalyticsDaily(Base):
    """Daily production metrics — dials, contacts, appts, closes."""

    __tablename__ = "analytics_daily"

    id: int = Column(Integer, primary_key=True, autoincrement=True)
    date: date = Column(Date, nullable=False, unique=True, index=True)
    dials: int = Column(Integer, default=0)
    contacts: int = Column(Integer, default=0)
    appointments_set: int = Column(Integer, default=0)
    appointments_kept: int = Column(Integer, default=0)
    closes: int = Column(Integer, default=0)
    premium_submitted: float = Column(Float, default=0.0)
    premium_issued: float = Column(Float, default=0.0)
    notes: str = Column(Text, nullable=True)
    created_at: datetime = Column(DateTime(timezone=True), server_default=func.now())
    updated_at: datetime = Column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class DBAgent(Base):
    """Agent profiles — drives FalconVerify consumer portal dynamically."""

    __tablename__ = "agents"

    id: int = Column(Integer, primary_key=True, autoincrement=True)
    user_id: str = Column(String(128), unique=True, nullable=False, index=True)
    slug: str = Column(String(64), unique=True, nullable=False, index=True)
    name: str = Column(String(256), nullable=False)
    title: str = Column(String(256), nullable=True)
    bio: str = Column(Text, nullable=True)
    photo_url: str = Column(String(512), nullable=True)
    phone: str = Column(String(20), nullable=True)
    phone_display: str = Column(String(20), nullable=True)
    email: str = Column(String(256), nullable=True)
    calendar_url: str = Column(String(512), nullable=True)
    npn: str = Column(String(20), nullable=True)
    location: str = Column(String(256), nullable=True)
    carrier_count: int = Column(Integer, default=47)
    carriers_json: str = Column(Text, nullable=True)
    is_active: bool = Column(Boolean, default=True)
    created_at: datetime = Column(DateTime(timezone=True), server_default=func.now())
    updated_at: datetime = Column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class DBTestimonial(Base):
    """Client testimonials for agent profiles."""

    __tablename__ = "testimonials"

    id: int = Column(Integer, primary_key=True, autoincrement=True)
    agent_id: int = Column(Integer, nullable=False, index=True)
    client_name: str = Column(String(128), nullable=False)
    text: str = Column(Text, nullable=False)
    rating: int = Column(Integer, default=5)
    date: date = Column(Date, nullable=True)
    is_published: bool = Column(Boolean, default=True)
    sort_order: int = Column(Integer, default=0)
    created_at: datetime = Column(DateTime(timezone=True), server_default=func.now())
    updated_at: datetime = Column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class DBLicense(Base):
    """Agent license records — used by FalconVerify consumer portal.

    Stores state licenses with auto-generated verification URLs
    (NAIC SOLAR deep-links, FL DFS permalinks, or state portal URLs).
    """

    __tablename__ = "licenses"

    id: int = Column(Integer, primary_key=True, autoincrement=True)
    user_id: str = Column(String(128), nullable=False, index=True)  # Clerk user ID
    state: str = Column(String(64), nullable=False)
    state_abbreviation: str = Column(String(2), nullable=False, index=True)
    license_number: str = Column(String(64), nullable=True)
    verify_url: str = Column(String(512), nullable=True)
    needs_manual_verification: bool = Column(Boolean, default=False)
    status: str = Column(String(16), default="active", index=True)
    license_type: str = Column(String(64), default="insurance_producer")
    created_at: datetime = Column(DateTime(timezone=True), server_default=func.now())
    updated_at: datetime = Column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class AppointmentReminder(Base):
    """Tracks scheduled SMS reminders and GCal events for Close appointments."""

    __tablename__ = "appointment_reminders"

    id: int = Column(Integer, primary_key=True, autoincrement=True)
    lead_id: str = Column(String(128), nullable=False, index=True)
    contact_id: str = Column(String(128), nullable=False)
    activity_id: str = Column(String(128), nullable=True, unique=True, index=True)  # Close activity ID — idempotency key
    appointment_datetime: datetime = Column(DateTime(timezone=True), nullable=False)
    sms_id_confirmation: str = Column(String(128), nullable=True)
    sms_id_24hr: str = Column(String(128), nullable=True)
    sms_id_1hr: str = Column(String(128), nullable=True)
    gcal_event_id: str = Column(String(256), nullable=True)
    status: str = Column(String(32), default="active", index=True)  # active | cancelled | rebooked
    created_at: datetime = Column(DateTime(timezone=True), server_default=func.now())
    updated_at: datetime = Column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class CadenceSmsDispatch(Base):
    """Idempotency log for cadence SMS sends.

    Insert-first dedup: every webhook-triggered cadence SMS attempts to
    insert a row keyed on (lead_id + template + UTC date). The unique
    constraint on `dedup_key` makes Close webhook retries no-ops within
    the same UTC day. If a lead genuinely needs the same template again,
    it will fire on the next UTC day.
    """

    __tablename__ = "cadence_sms_dispatches"

    id: int = Column(Integer, primary_key=True, autoincrement=True)
    dedup_key: str = Column(String(256), unique=True, nullable=False, index=True)
    lead_id: str = Column(String(128), nullable=False, index=True)
    template_key: str = Column(String(64), nullable=False)
    scheduled_date: str = Column(String(32), nullable=False)
    sms_ids: str = Column(Text, nullable=True)
    created_at: datetime = Column(DateTime(timezone=True), server_default=func.now())


class AppointmentCalendarEmail(Base):
    """Maps Close leads to dummy calendar emails for GCal ↔ Close linking."""

    __tablename__ = "appointment_calendar_emails"

    id: int = Column(Integer, primary_key=True, autoincrement=True)
    lead_id: str = Column(String(128), nullable=False, unique=True, index=True)
    contact_id: str = Column(String(128), nullable=False)
    dummy_email: str = Column(String(256), nullable=False, unique=True)
    gcal_event_id: str = Column(String(256), nullable=True)
    created_at: datetime = Column(DateTime(timezone=True), server_default=func.now())


class Campaign(Base):
    """Ad campaigns — tracks Meta Ads campaigns for lead generation."""

    __tablename__ = "campaigns"

    id: int = Column(Integer, primary_key=True, autoincrement=True)
    user_id: str = Column(String(128), nullable=False, index=True)
    name: str = Column(String(256), nullable=False)
    status: str = Column(String(32), default="draft", index=True)  # draft | active | paused | completed
    strategy_json: str = Column(Text, nullable=True)  # JSON — product, target states, age range, etc.
    meta_campaign_id: str = Column(String(128), nullable=True)
    meta_ad_account_id: str = Column(String(128), nullable=True)
    budget_daily: float = Column(Float, default=0.0)
    budget_total: float = Column(Float, default=0.0)
    target_audience_json: str = Column(Text, nullable=True)  # JSON — audience targeting config
    created_at: datetime = Column(DateTime(timezone=True), server_default=func.now())
    updated_at: datetime = Column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    variants = relationship("CampaignVariant", back_populates="campaign", lazy="selectin")


class CampaignVariant(Base):
    """Ad copy variants within a campaign — A/B test different angles."""

    __tablename__ = "campaign_variants"

    id: int = Column(Integer, primary_key=True, autoincrement=True)
    campaign_id: int = Column(Integer, ForeignKey("campaigns.id"), nullable=False, index=True)
    variant_name: str = Column(String(256), nullable=False)
    headline: str = Column(String(512), nullable=False)
    body_copy: str = Column(Text, nullable=False)
    cta_text: str = Column(String(128), nullable=False)
    angle: str = Column(String(32), nullable=False)  # fear | math | social_proof | urgency
    meta_ad_id: str = Column(String(128), nullable=True)
    impressions: int = Column(Integer, default=0)
    clicks: int = Column(Integer, default=0)
    leads: int = Column(Integer, default=0)
    booked_appointments: int = Column(Integer, default=0)
    spend: float = Column(Float, default=0.0)
    cpl: float = Column(Float, default=0.0)
    status: str = Column(String(32), default="active")  # active | paused | killed
    created_at: datetime = Column(DateTime(timezone=True), server_default=func.now())

    campaign = relationship("Campaign", back_populates="variants")


class SmsTemplate(Base):
    """Editable SMS templates for appointment reminders."""

    __tablename__ = "sms_templates"

    id: int = Column(Integer, primary_key=True, autoincrement=True)
    template_key: str = Column(String(32), unique=True, nullable=False, index=True)
    body: str = Column(Text, nullable=False)
    created_at: datetime = Column(DateTime(timezone=True), server_default=func.now())
    updated_at: datetime = Column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class PhoneNumber(Base):
    """Outbound phone number pool for smart SMS routing."""

    __tablename__ = "phone_numbers"

    id: int = Column(Integer, primary_key=True, autoincrement=True)
    number: str = Column(String(20), unique=True, nullable=False, index=True)
    state: str = Column(String(2), nullable=False)
    area_codes_json: str = Column(Text, nullable=False)  # JSON array of ints
    is_active: bool = Column(Boolean, default=True)
    created_at: datetime = Column(DateTime(timezone=True), server_default=func.now())


class ResearchTrigger(Base):
    """Research cycle trigger queue — written by dashboard, consumed by local loop."""

    __tablename__ = "research_triggers"

    id: int = Column(Integer, primary_key=True, autoincrement=True)
    triggered_at: datetime = Column(DateTime(timezone=True), server_default=func.now())
    triggered_by: str = Column(String(128), nullable=True)  # Clerk user_id
    status: str = Column(String(16), default="pending", index=True)  # pending | consumed | cancelled
    consumed_at: datetime = Column(DateTime(timezone=True), nullable=True)
    cycle_id: str = Column(String(64), nullable=True)  # filled in by loop after run
    notes: str = Column(Text, nullable=True)


class CarrierFavorite(Base):
    """Saved carrier dial contacts for the 3 Way Bridge cockpit."""

    __tablename__ = "carrier_favorites"

    id: str = Column(String(36), primary_key=True, default=lambda: str(__import__("uuid").uuid4()))
    user_id: str = Column(String(128), nullable=False, index=True)
    carrier_name: str = Column(String(256), nullable=False)
    carrier_dept: str = Column(String(256), nullable=False, default="")
    carrier_number: str = Column(String(32), nullable=False)
    dial_instructions: str = Column(Text, nullable=True)
    created_at: datetime = Column(DateTime(timezone=True), server_default=func.now())
    updated_at: datetime = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class ConferenceSession(Base):
    """PSTN conference bridge sessions — 3-way calls (Seb + Lead + Carrier)."""

    __tablename__ = "conference_sessions"

    id: str = Column(String(36), primary_key=True, default=lambda: str(__import__("uuid").uuid4()))
    user_id: str = Column(String(128), nullable=False, index=True)  # Clerk user that owns the session
    conference_sid: str = Column(String(128), nullable=True, index=True)
    lead_id: str = Column(String(128), nullable=True)
    lead_phone: str = Column(String(20), nullable=False)
    carrier_phone: str = Column(String(20), nullable=False)
    seb_phone: str = Column(String(20), nullable=False)
    seb_participant_sid: str = Column(String(128), nullable=True)
    lead_participant_sid: str = Column(String(128), nullable=True)
    carrier_participant_sid: str = Column(String(128), nullable=True)
    status: str = Column(String(32), default="initiating", index=True)
    started_at: datetime = Column(DateTime(timezone=True), server_default=func.now())
    ended_at: datetime = Column(DateTime(timezone=True), nullable=True)
    call_duration_seconds: int = Column(Integer, nullable=True)
    close_activity_logged: bool = Column(Boolean, default=False)


class ResearchCycle(Base):
    """Research cycle records — synced from Mac Mini SQLite after each cycle."""

    __tablename__ = "research_cycles"

    id: int = Column(Integer, primary_key=True, autoincrement=True)
    cycle_id: str = Column(String(64), unique=True, index=True)
    ads_generated: int = Column(Integer, default=0)
    mutations_generated: int = Column(Integer, default=0)
    hypotheses_formed: int = Column(Integer, default=0)
    analysis_summary: str = Column(Text, nullable=True)
    status: str = Column(String(32), default="complete")
    created_at: datetime = Column(DateTime(timezone=True), server_default=func.now())


class ResearchHypothesis(Base):
    """Research hypotheses — synced from Mac Mini SQLite after each cycle."""

    __tablename__ = "research_hypotheses"

    id: int = Column(Integer, primary_key=True, autoincrement=True)
    cycle_id: str = Column(String(64), index=True)
    hypothesis_text: str = Column(Text)
    account_type: str = Column(String(16))  # SAC | NONSAC | both
    status: str = Column(String(32), default="proposed")  # proposed | testing | winner | loser
    confidence: float = Column(Float, default=0.5)
    created_at: datetime = Column(DateTime(timezone=True), server_default=func.now())
    updated_at: datetime = Column(DateTime(timezone=True), onupdate=func.now())


class ResearchAd(Base):
    """Research ad variants — synced from Mac Mini SQLite after each cycle."""

    __tablename__ = "research_ads"

    id: int = Column(Integer, primary_key=True, autoincrement=True)
    cycle_id: str = Column(String(64), index=True)
    hypothesis_id: int = Column(Integer, nullable=True)
    name: str = Column(String(256))
    ad_copy: str = Column(Text)
    headline: str = Column(String(256), nullable=True)
    description: str = Column(Text, nullable=True)
    cta: str = Column(String(64), nullable=True)
    account_type: str = Column(String(16))  # SAC | NONSAC
    status: str = Column(String(32), default="pending_approval")  # pending_approval | approved | rejected | live | paused
    approved_at: datetime = Column(DateTime(timezone=True), nullable=True)
    rejected_at: datetime = Column(DateTime(timezone=True), nullable=True)
    created_at: datetime = Column(DateTime(timezone=True), server_default=func.now())
    updated_at: datetime = Column(DateTime(timezone=True), onupdate=func.now())


# ══════════════════════════════════════════════════════════════════════════════
#  GHL Dashboard tables — read-only lead intelligence cache
# ══════════════════════════════════════════════════════════════════════════════


class GHLSyncStatus(Base):
    """Tracks sync metadata for each GHL data type."""

    __tablename__ = "ghl_sync_status"

    id: int = Column(Integer, primary_key=True, autoincrement=True)
    sync_type: str = Column(String(50), nullable=False)
    last_sync_at = Column(DateTime(timezone=True), nullable=True)
    records_synced: int = Column(Integer, default=0)
    status: str = Column(String(20), default="pending")
    error_message: str = Column(Text, nullable=True)
    created_at: datetime = Column(DateTime(timezone=True), server_default=func.now())


class GHLContact(Base):
    """Cached GHL contacts."""

    __tablename__ = "ghl_contacts"

    id: str = Column(String(100), primary_key=True)
    first_name: str = Column(String(255), nullable=True)
    last_name: str = Column(String(255), nullable=True)
    email: str = Column(String(255), nullable=True)
    phone: str = Column(String(50), nullable=True)
    tags = Column(ARRAY(Text), nullable=True)
    dnd: bool = Column(Boolean, default=False)
    dnd_sms: bool = Column(Boolean, default=False)
    dnd_email: bool = Column(Boolean, default=False)
    dnd_calls: bool = Column(Boolean, default=False)
    source: str = Column(String(255), nullable=True)
    assigned_to: str = Column(String(100), nullable=True)
    date_added = Column(DateTime(timezone=True), nullable=True)
    date_updated = Column(DateTime(timezone=True), nullable=True)
    custom_fields = Column(JSONB, default={})
    raw_data = Column(JSONB, nullable=True)
    synced_at = Column(DateTime(timezone=True), server_default=func.now())


class GHLPipeline(Base):
    """Cached GHL pipeline structure."""

    __tablename__ = "ghl_pipelines"

    id: str = Column(String(100), primary_key=True)
    name: str = Column(String(255), nullable=True)
    stages = Column(JSONB, nullable=True)
    synced_at = Column(DateTime(timezone=True), server_default=func.now())


class GHLOpportunity(Base):
    """Cached GHL opportunities."""

    __tablename__ = "ghl_opportunities"

    id: str = Column(String(100), primary_key=True)
    name: str = Column(String(255), nullable=True)
    status: str = Column(String(50), nullable=True)
    pipeline_id: str = Column(String(100), nullable=True)
    stage_id: str = Column(String(100), nullable=True)
    stage_name: str = Column(String(255), nullable=True)
    monetary_value = Column(Numeric(12, 2), nullable=True)
    contact_id: str = Column(String(100), nullable=True)
    contact_name: str = Column(String(255), nullable=True)
    contact_email: str = Column(String(255), nullable=True)
    contact_phone: str = Column(String(50), nullable=True)
    date_added = Column(DateTime(timezone=True), nullable=True)
    last_status_change = Column(DateTime(timezone=True), nullable=True)
    raw_data = Column(JSONB, nullable=True)
    synced_at = Column(DateTime(timezone=True), server_default=func.now())


class GHLWorkflow(Base):
    """Cached GHL workflows."""

    __tablename__ = "ghl_workflows"

    id: str = Column(String(100), primary_key=True)
    name: str = Column(String(255), nullable=True)
    status: str = Column(String(50), nullable=True)
    synced_at = Column(DateTime(timezone=True), server_default=func.now())


class GHLComplianceFlag(Base):
    """Computed compliance flags from GHL data."""

    __tablename__ = "ghl_compliance_flags"

    id: int = Column(Integer, primary_key=True, autoincrement=True)
    contact_id: str = Column(String(100), nullable=False)
    contact_name: str = Column(String(255), nullable=True)
    contact_phone: str = Column(String(50), nullable=True)
    contact_email: str = Column(String(255), nullable=True)
    flag_type: str = Column(String(50), nullable=False)
    flag_detail: str = Column(Text, nullable=True)
    severity: str = Column(String(20), default="warning")
    pipeline_name: str = Column(String(255), nullable=True)
    stage_name: str = Column(String(255), nullable=True)
    tags = Column(ARRAY(Text), nullable=True)
    created_at: datetime = Column(DateTime(timezone=True), server_default=func.now())
    resolved: bool = Column(Boolean, default=False)


class LeadHygieneReportRun(Base):
    """Durable Lead Hygiene report history and payload storage."""

    __tablename__ = "lead_hygiene_report_runs"

    id: int = Column(Integer, primary_key=True, autoincrement=True)
    job_id: str = Column(String(32), unique=True, nullable=False, index=True)
    status: str = Column(String(32), nullable=False, index=True)
    phase: str = Column(String(64), nullable=True)
    params = Column(RegistryJSON, nullable=True)
    summary = Column(RegistryJSON, nullable=True)
    report_payload = Column(RegistryJSON, nullable=True)
    csv_text: str = Column(Text, nullable=True)
    sources = Column(RegistryJSON, nullable=True)
    started_at: datetime = Column(DateTime(timezone=True), nullable=True, index=True)
    finished_at: datetime = Column(DateTime(timezone=True), nullable=True)
    error: str = Column(Text, nullable=True)
    deleted_at: datetime = Column(DateTime(timezone=True), nullable=True, index=True)
    created_at: datetime = Column(DateTime(timezone=True), server_default=func.now())
    updated_at: datetime = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


# ══════════════════════════════════════════════════════════════════════════════
#  Registry v1 — local-only identity review cache
# ══════════════════════════════════════════════════════════════════════════════


class RegistryHousehold(Base):
    """Parent identity group for people, contacts, and source records."""

    __tablename__ = "registry_households"

    id: int = Column(Integer, primary_key=True, autoincrement=True)
    display_name: str = Column(String(256), nullable=False, index=True)
    status: str = Column(String(32), default="active", nullable=False, index=True)
    risk_level: str = Column(String(32), default="unknown", nullable=False, index=True)
    confidence: float = Column(Float, default=0.0)
    primary_phone: str = Column(String(32), nullable=True, index=True)
    primary_email: str = Column(String(256), nullable=True, index=True)
    derived_from: str = Column(String(64), nullable=True)
    first_seen_at: datetime = Column(DateTime(timezone=True), server_default=func.now())
    last_seen_at: datetime = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    created_at: datetime = Column(DateTime(timezone=True), server_default=func.now())
    updated_at: datetime = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    people = relationship("RegistryPerson", back_populates="household", lazy="selectin")
    contact_methods = relationship("RegistryContactMethod", back_populates="household", lazy="selectin")
    external_records = relationship("RegistryExternalRecord", back_populates="household", lazy="selectin")
    recommendations = relationship("RegistryRecommendation", back_populates="household", lazy="selectin")
    consent_events = relationship("RegistryConsentEvent", back_populates="household", lazy="selectin")


class RegistryPerson(Base):
    """Person record inside a registry household."""

    __tablename__ = "registry_people"

    id: int = Column(Integer, primary_key=True, autoincrement=True)
    household_id: int = Column(Integer, ForeignKey("registry_households.id"), nullable=False, index=True)
    display_name: str = Column(String(256), nullable=False, index=True)
    first_name: str = Column(String(128), nullable=True)
    last_name: str = Column(String(128), nullable=True)
    role: str = Column(String(64), default="primary")
    dnc_status: str = Column(String(64), default="unknown")
    consent_status: str = Column(String(64), default="unknown")
    created_at: datetime = Column(DateTime(timezone=True), server_default=func.now())
    updated_at: datetime = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    household = relationship("RegistryHousehold", back_populates="people")
    contact_methods = relationship("RegistryContactMethod", back_populates="person", lazy="selectin")


class RegistryContactMethod(Base):
    """Normalized local phone, email, or address attached to a household/person."""

    __tablename__ = "registry_contact_methods"

    id: int = Column(Integer, primary_key=True, autoincrement=True)
    household_id: int = Column(Integer, ForeignKey("registry_households.id"), nullable=False, index=True)
    person_id: int = Column(Integer, ForeignKey("registry_people.id"), nullable=True, index=True)
    kind: str = Column(String(32), nullable=False, index=True)
    raw_value: str = Column(String(512), nullable=False)
    normalized_value: str = Column(String(512), nullable=False, index=True)
    validity_status: str = Column(String(64), default="unknown")
    consent_status: str = Column(String(64), default="unknown")
    is_primary: bool = Column(Boolean, default=False)
    created_at: datetime = Column(DateTime(timezone=True), server_default=func.now())
    updated_at: datetime = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        UniqueConstraint("household_id", "kind", "normalized_value", name="uq_registry_contact_method_identity"),
    )

    household = relationship("RegistryHousehold", back_populates="contact_methods")
    person = relationship("RegistryPerson", back_populates="contact_methods")


class RegistryExternalRecord(Base):
    """External source pointer. It stores identifiers only, never upstream writes."""

    __tablename__ = "registry_external_records"

    id: int = Column(Integer, primary_key=True, autoincrement=True)
    household_id: int = Column(Integer, ForeignKey("registry_households.id"), nullable=True, index=True)
    person_id: int = Column(Integer, ForeignKey("registry_people.id"), nullable=True, index=True)
    contact_method_id: int = Column(Integer, ForeignKey("registry_contact_methods.id"), nullable=True, index=True)
    source: str = Column(String(32), nullable=False, index=True)
    external_type: str = Column(String(64), nullable=False)
    external_id: str = Column(String(256), nullable=False, index=True)
    match_basis: str = Column(String(64), nullable=True)
    match_confidence: float = Column(Float, nullable=True)
    match_reason: str = Column(Text, nullable=True)
    payload_hash: str = Column(String(128), nullable=True)
    first_seen_at: datetime = Column(DateTime(timezone=True), server_default=func.now())
    last_seen_at: datetime = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    created_at: datetime = Column(DateTime(timezone=True), server_default=func.now())
    updated_at: datetime = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        UniqueConstraint("source", "external_type", "external_id", name="uq_registry_external_record_source_id"),
    )

    household = relationship("RegistryHousehold", back_populates="external_records")


class RegistrySourceSnapshot(Base):
    """Immutable local payload snapshot for an import/report row."""

    __tablename__ = "registry_source_snapshots"

    id: int = Column(Integer, primary_key=True, autoincrement=True)
    source: str = Column(String(32), nullable=False, index=True)
    source_type: str = Column(String(64), nullable=True)
    source_ref: str = Column(String(256), nullable=True, index=True)
    payload_hash: str = Column(String(128), unique=True, nullable=False, index=True)
    payload = Column(RegistryJSON, nullable=False)
    pulled_at: datetime = Column(DateTime(timezone=True), server_default=func.now())
    created_at: datetime = Column(DateTime(timezone=True), server_default=func.now())
    record_count: int = Column(Integer, nullable=True)
    notes: str = Column(Text, nullable=True)


class RegistryRecommendation(Base):
    """Read-only proposed action generated from local evidence."""

    __tablename__ = "registry_recommendations"

    id: int = Column(Integer, primary_key=True, autoincrement=True)
    household_id: int = Column(Integer, ForeignKey("registry_households.id"), nullable=False, index=True)
    person_id: int = Column(Integer, ForeignKey("registry_people.id"), nullable=True, index=True)
    external_record_id: int = Column(Integer, ForeignKey("registry_external_records.id"), nullable=True)
    source_snapshot_id: int = Column(Integer, ForeignKey("registry_source_snapshots.id"), nullable=True, index=True)
    recommendation_type: str = Column(String(128), nullable=False, index=True)
    status: str = Column(String(64), default="proposed", nullable=False, index=True)
    risk_level: str = Column(String(32), default="unknown", nullable=False, index=True)
    confidence: float = Column(Float, nullable=True)
    evidence = Column(RegistryJSON, nullable=True)
    proposed_at: datetime = Column(DateTime(timezone=True), server_default=func.now())
    created_at: datetime = Column(DateTime(timezone=True), server_default=func.now())
    updated_at: datetime = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        UniqueConstraint("household_id", "source_snapshot_id", "recommendation_type", name="uq_registry_recommendation_snapshot"),
    )

    household = relationship("RegistryHousehold", back_populates="recommendations")


class RegistryConsentEvent(Base):
    """Audit event for consent/DNC evidence observed in source data."""

    __tablename__ = "registry_consent_events"

    id: int = Column(Integer, primary_key=True, autoincrement=True)
    household_id: int = Column(Integer, ForeignKey("registry_households.id"), nullable=False, index=True)
    person_id: int = Column(Integer, ForeignKey("registry_people.id"), nullable=True, index=True)
    contact_method_id: int = Column(Integer, ForeignKey("registry_contact_methods.id"), nullable=True)
    external_record_id: int = Column(Integer, ForeignKey("registry_external_records.id"), nullable=True)
    event_type: str = Column(String(128), nullable=False, index=True)
    source: str = Column(String(32), nullable=False, index=True)
    evidence: str = Column(Text, nullable=True)
    occurred_at: datetime = Column(DateTime(timezone=True), nullable=True)
    observed_at: datetime = Column(DateTime(timezone=True), server_default=func.now())
    created_at: datetime = Column(DateTime(timezone=True), server_default=func.now())

    household = relationship("RegistryHousehold", back_populates="consent_events")
