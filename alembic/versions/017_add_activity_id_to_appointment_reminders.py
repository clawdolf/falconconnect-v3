"""Add activity_id to appointment_reminders for webhook idempotency.

Revision ID: 017_add_activity_id_to_appointment_reminders
Revises: 016_add_ghl_dashboard_tables
Create Date: 2026-04-01
"""
import sqlalchemy as sa
from alembic import op

revision = "017_add_activity_id_to_appointment_reminders"
down_revision = "016_add_ghl_dashboard_tables"
branch_labels = None
depends_on = None


def upgrade() -> None:
    from sqlalchemy import inspect as sa_inspect
    bind = op.get_bind()
    cols = [c["name"] for c in sa_inspect(bind).get_columns("appointment_reminders")]
    if "activity_id" in cols:
        return  # column already exists
    # Add activity_id column — nullable initially to avoid breaking existing rows
    op.add_column(
        "appointment_reminders",
        sa.Column("activity_id", sa.String(128), nullable=True),
    )
    # Unique index so duplicate webhook events are caught at the DB level too
    op.create_index(
        "ix_appointment_reminders_activity_id",
        "appointment_reminders",
        ["activity_id"],
        unique=True,
        postgresql_where=sa.text("activity_id IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("ix_appointment_reminders_activity_id", table_name="appointment_reminders")
    op.drop_column("appointment_reminders", "activity_id")
