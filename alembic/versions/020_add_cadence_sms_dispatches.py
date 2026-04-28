"""Add cadence_sms_dispatches table for SMS send idempotency.

Stops Close webhook retries from double-sending cadence SMS. Insert-first
pattern: a row is created BEFORE the SMS is sent, keyed on
(lead_id + template + UTC date). Unique constraint catches retries.

Revision ID: 020_add_cadence_sms_dispatches
Revises: 019_add_user_id_to_conference_sessions
Create Date: 2026-04-25
"""
import sqlalchemy as sa
from alembic import op

revision = "020_add_cadence_sms_dispatches"
down_revision = "019_add_user_id_to_conference_sessions"
branch_labels = None
depends_on = None


def upgrade() -> None:
    from sqlalchemy import inspect as sa_inspect

    bind = op.get_bind()
    if "cadence_sms_dispatches" in sa_inspect(bind).get_table_names():
        return

    op.create_table(
        "cadence_sms_dispatches",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("dedup_key", sa.String(256), nullable=False),
        sa.Column("lead_id", sa.String(128), nullable=False),
        sa.Column("template_key", sa.String(64), nullable=False),
        sa.Column("scheduled_date", sa.String(32), nullable=False),
        sa.Column("sms_ids", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.UniqueConstraint("dedup_key", name="uq_cadence_sms_dispatches_dedup_key"),
    )
    op.create_index(
        "ix_cadence_sms_dispatches_dedup_key",
        "cadence_sms_dispatches",
        ["dedup_key"],
    )
    op.create_index(
        "ix_cadence_sms_dispatches_lead_id",
        "cadence_sms_dispatches",
        ["lead_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_cadence_sms_dispatches_lead_id",
        table_name="cadence_sms_dispatches",
    )
    op.drop_index(
        "ix_cadence_sms_dispatches_dedup_key",
        table_name="cadence_sms_dispatches",
    )
    op.drop_table("cadence_sms_dispatches")
