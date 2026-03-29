"""Add conference_sessions table for PSTN conference bridge.

Revision ID: 006_add_conference_sessions
Revises: 005_insert_licenses
Create Date: 2026-03-19
"""
from alembic import op
import sqlalchemy as sa

revision = "006_add_conference_sessions"
down_revision = "006_seed_seb_final"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "conference_sessions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("conference_sid", sa.String(128), nullable=True, index=True),
        sa.Column("lead_id", sa.String(128), nullable=True),
        sa.Column("lead_phone", sa.String(20), nullable=False),
        sa.Column("carrier_phone", sa.String(20), nullable=False),
        sa.Column("seb_phone", sa.String(20), nullable=False),
        sa.Column("seb_participant_sid", sa.String(128), nullable=True),
        sa.Column("lead_participant_sid", sa.String(128), nullable=True),
        sa.Column("carrier_participant_sid", sa.String(128), nullable=True),
        sa.Column("status", sa.String(32), server_default="initiating", index=True),
        sa.Column("started_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("call_duration_seconds", sa.Integer(), nullable=True),
        sa.Column("close_activity_logged", sa.Boolean(), server_default="false"),
    )


def downgrade() -> None:
    op.drop_table("conference_sessions")
