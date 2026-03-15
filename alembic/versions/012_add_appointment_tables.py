"""Add appointment_reminders and appointment_calendar_emails tables.

Revision ID: 012_add_appointment_tables
Revises: 011_add_campaigns
Create Date: 2026-03-15
"""
import sqlalchemy as sa
from alembic import op

revision = "012_add_appointment_tables"
down_revision = "011_add_campaigns"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "appointment_reminders",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("lead_id", sa.String(128), nullable=False, index=True),
        sa.Column("contact_id", sa.String(128), nullable=False),
        sa.Column("appointment_datetime", sa.DateTime(timezone=True), nullable=False),
        sa.Column("sms_id_confirmation", sa.String(128), nullable=True),
        sa.Column("sms_id_24hr", sa.String(128), nullable=True),
        sa.Column("sms_id_1hr", sa.String(128), nullable=True),
        sa.Column("gcal_event_id", sa.String(256), nullable=True),
        sa.Column("status", sa.String(32), nullable=False, server_default="active", index=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    op.create_table(
        "appointment_calendar_emails",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("lead_id", sa.String(128), nullable=False, unique=True, index=True),
        sa.Column("contact_id", sa.String(128), nullable=False),
        sa.Column("dummy_email", sa.String(256), nullable=False, unique=True),
        sa.Column("gcal_event_id", sa.String(256), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )


def downgrade() -> None:
    op.drop_table("appointment_calendar_emails")
    op.drop_table("appointment_reminders")
