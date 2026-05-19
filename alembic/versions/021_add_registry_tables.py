"""Add Registry v1 local identity review tables.

Revision ID: 021_add_registry_tables
Revises: 020_add_cadence_sms_dispatches
Create Date: 2026-05-18
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "021_add_registry_tables"
down_revision = "020_add_cadence_sms_dispatches"
branch_labels = None
depends_on = None


def _json_type():
    return postgresql.JSONB(astext_type=sa.Text()).with_variant(sa.JSON(), "sqlite")


def upgrade() -> None:
    from sqlalchemy import inspect as sa_inspect

    bind = op.get_bind()
    existing = set(sa_inspect(bind).get_table_names())
    if "registry_households" in existing:
        return

    op.create_table(
        "registry_households",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("display_name", sa.String(256), nullable=False),
        sa.Column("status", sa.String(32), nullable=False, server_default="active"),
        sa.Column("risk_level", sa.String(32), nullable=False, server_default="unknown"),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("primary_phone", sa.String(32), nullable=True),
        sa.Column("primary_email", sa.String(256), nullable=True),
        sa.Column("derived_from", sa.String(64), nullable=True),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_registry_households_display_name", "registry_households", ["display_name"])
    op.create_index("ix_registry_households_status", "registry_households", ["status"])
    op.create_index("ix_registry_households_risk_level", "registry_households", ["risk_level"])
    op.create_index("ix_registry_households_primary_phone", "registry_households", ["primary_phone"])
    op.create_index("ix_registry_households_primary_email", "registry_households", ["primary_email"])

    op.create_table(
        "registry_people",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("household_id", sa.Integer(), sa.ForeignKey("registry_households.id"), nullable=False),
        sa.Column("display_name", sa.String(256), nullable=False),
        sa.Column("first_name", sa.String(128), nullable=True),
        sa.Column("last_name", sa.String(128), nullable=True),
        sa.Column("role", sa.String(64), nullable=True),
        sa.Column("dnc_status", sa.String(64), nullable=True),
        sa.Column("consent_status", sa.String(64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_registry_people_household_id", "registry_people", ["household_id"])
    op.create_index("ix_registry_people_display_name", "registry_people", ["display_name"])

    op.create_table(
        "registry_contact_methods",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("household_id", sa.Integer(), sa.ForeignKey("registry_households.id"), nullable=False),
        sa.Column("person_id", sa.Integer(), sa.ForeignKey("registry_people.id"), nullable=True),
        sa.Column("kind", sa.String(32), nullable=False),
        sa.Column("raw_value", sa.String(512), nullable=False),
        sa.Column("normalized_value", sa.String(512), nullable=False),
        sa.Column("validity_status", sa.String(64), nullable=True),
        sa.Column("consent_status", sa.String(64), nullable=True),
        sa.Column("is_primary", sa.Boolean(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("household_id", "kind", "normalized_value", name="uq_registry_contact_method_identity"),
    )
    op.create_index("ix_registry_contact_methods_household_id", "registry_contact_methods", ["household_id"])
    op.create_index("ix_registry_contact_methods_person_id", "registry_contact_methods", ["person_id"])
    op.create_index("ix_registry_contact_methods_kind", "registry_contact_methods", ["kind"])
    op.create_index("ix_registry_contact_methods_normalized_value", "registry_contact_methods", ["normalized_value"])

    op.create_table(
        "registry_source_snapshots",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("source", sa.String(32), nullable=False),
        sa.Column("source_type", sa.String(64), nullable=True),
        sa.Column("source_ref", sa.String(256), nullable=True),
        sa.Column("payload_hash", sa.String(128), nullable=False, unique=True),
        sa.Column("payload", _json_type(), nullable=False),
        sa.Column("pulled_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("record_count", sa.Integer(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
    )
    op.create_index("ix_registry_source_snapshots_source", "registry_source_snapshots", ["source"])
    op.create_index("ix_registry_source_snapshots_source_ref", "registry_source_snapshots", ["source_ref"])
    op.create_index("ix_registry_source_snapshots_payload_hash", "registry_source_snapshots", ["payload_hash"])

    op.create_table(
        "registry_external_records",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("household_id", sa.Integer(), sa.ForeignKey("registry_households.id"), nullable=True),
        sa.Column("person_id", sa.Integer(), sa.ForeignKey("registry_people.id"), nullable=True),
        sa.Column("contact_method_id", sa.Integer(), sa.ForeignKey("registry_contact_methods.id"), nullable=True),
        sa.Column("source", sa.String(32), nullable=False),
        sa.Column("external_type", sa.String(64), nullable=False),
        sa.Column("external_id", sa.String(256), nullable=False),
        sa.Column("match_basis", sa.String(64), nullable=True),
        sa.Column("match_confidence", sa.Float(), nullable=True),
        sa.Column("match_reason", sa.Text(), nullable=True),
        sa.Column("payload_hash", sa.String(128), nullable=True),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("source", "external_type", "external_id", name="uq_registry_external_record_source_id"),
    )
    op.create_index("ix_registry_external_records_household_id", "registry_external_records", ["household_id"])
    op.create_index("ix_registry_external_records_person_id", "registry_external_records", ["person_id"])
    op.create_index("ix_registry_external_records_contact_method_id", "registry_external_records", ["contact_method_id"])
    op.create_index("ix_registry_external_records_source", "registry_external_records", ["source"])
    op.create_index("ix_registry_external_records_external_id", "registry_external_records", ["external_id"])

    op.create_table(
        "registry_recommendations",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("household_id", sa.Integer(), sa.ForeignKey("registry_households.id"), nullable=False),
        sa.Column("person_id", sa.Integer(), sa.ForeignKey("registry_people.id"), nullable=True),
        sa.Column("external_record_id", sa.Integer(), sa.ForeignKey("registry_external_records.id"), nullable=True),
        sa.Column("source_snapshot_id", sa.Integer(), sa.ForeignKey("registry_source_snapshots.id"), nullable=True),
        sa.Column("recommendation_type", sa.String(128), nullable=False),
        sa.Column("status", sa.String(64), nullable=False, server_default="proposed"),
        sa.Column("risk_level", sa.String(32), nullable=False, server_default="unknown"),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("evidence", _json_type(), nullable=True),
        sa.Column("proposed_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("household_id", "source_snapshot_id", "recommendation_type", name="uq_registry_recommendation_snapshot"),
    )
    op.create_index("ix_registry_recommendations_household_id", "registry_recommendations", ["household_id"])
    op.create_index("ix_registry_recommendations_person_id", "registry_recommendations", ["person_id"])
    op.create_index("ix_registry_recommendations_source_snapshot_id", "registry_recommendations", ["source_snapshot_id"])
    op.create_index("ix_registry_recommendations_recommendation_type", "registry_recommendations", ["recommendation_type"])
    op.create_index("ix_registry_recommendations_status", "registry_recommendations", ["status"])
    op.create_index("ix_registry_recommendations_risk_level", "registry_recommendations", ["risk_level"])

    op.create_table(
        "registry_consent_events",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("household_id", sa.Integer(), sa.ForeignKey("registry_households.id"), nullable=False),
        sa.Column("person_id", sa.Integer(), sa.ForeignKey("registry_people.id"), nullable=True),
        sa.Column("contact_method_id", sa.Integer(), sa.ForeignKey("registry_contact_methods.id"), nullable=True),
        sa.Column("external_record_id", sa.Integer(), sa.ForeignKey("registry_external_records.id"), nullable=True),
        sa.Column("event_type", sa.String(128), nullable=False),
        sa.Column("source", sa.String(32), nullable=False),
        sa.Column("evidence", sa.Text(), nullable=True),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("observed_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_registry_consent_events_household_id", "registry_consent_events", ["household_id"])
    op.create_index("ix_registry_consent_events_person_id", "registry_consent_events", ["person_id"])
    op.create_index("ix_registry_consent_events_event_type", "registry_consent_events", ["event_type"])
    op.create_index("ix_registry_consent_events_source", "registry_consent_events", ["source"])


def downgrade() -> None:
    for table, indexes in (
        ("registry_consent_events", ["ix_registry_consent_events_source", "ix_registry_consent_events_event_type", "ix_registry_consent_events_person_id", "ix_registry_consent_events_household_id"]),
        ("registry_recommendations", ["ix_registry_recommendations_risk_level", "ix_registry_recommendations_status", "ix_registry_recommendations_recommendation_type", "ix_registry_recommendations_source_snapshot_id", "ix_registry_recommendations_person_id", "ix_registry_recommendations_household_id"]),
        ("registry_external_records", ["ix_registry_external_records_external_id", "ix_registry_external_records_source", "ix_registry_external_records_contact_method_id", "ix_registry_external_records_person_id", "ix_registry_external_records_household_id"]),
        ("registry_source_snapshots", ["ix_registry_source_snapshots_payload_hash", "ix_registry_source_snapshots_source_ref", "ix_registry_source_snapshots_source"]),
        ("registry_contact_methods", ["ix_registry_contact_methods_normalized_value", "ix_registry_contact_methods_kind", "ix_registry_contact_methods_person_id", "ix_registry_contact_methods_household_id"]),
        ("registry_people", ["ix_registry_people_display_name", "ix_registry_people_household_id"]),
        ("registry_households", ["ix_registry_households_primary_email", "ix_registry_households_primary_phone", "ix_registry_households_risk_level", "ix_registry_households_status", "ix_registry_households_display_name"]),
    ):
        for index in indexes:
            op.drop_index(index, table_name=table)
        op.drop_table(table)
