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
    String,
    Text,
    func,
)
from sqlalchemy.orm import DeclarativeBase, relationship


class Base(DeclarativeBase):
    pass


class LeadXref(Base):
    """Maps GHL contact ID ↔ Notion page ID ↔ phone for cross-system lookups."""

    __tablename__ = "lead_xref"

    id: int = Column(Integer, primary_key=True, autoincrement=True)
    ghl_contact_id: str = Column(String(64), unique=True, nullable=False, index=True)
    notion_page_id: str = Column(String(64), unique=True, nullable=False, index=True)
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


class IssuedPaid(Base):
    """Carrier commission deposits from Plaid (Phase 2)."""

    __tablename__ = "issued_paid"

    id: int = Column(Integer, primary_key=True, autoincrement=True)
    carrier: str = Column(String(128), nullable=False)
    amount: float = Column(Float, nullable=False)
    transaction_date: date = Column(Date, nullable=False)
    plaid_transaction_id: str = Column(String(128), unique=True, nullable=True)
    description: str = Column(Text, nullable=True)
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
