"""Add durable Lead Hygiene report runs.

Revision ID: 023_add_lead_hygiene_report_runs
Revises: 022_add_carrier_favorites
Create Date: 2026-05-20
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "023_add_lead_hygiene_report_runs"
down_revision = "022_add_carrier_favorites"
branch_labels = None
depends_on = None


def _json_type():
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        return postgresql.JSONB(astext_type=sa.Text())
    return sa.JSON()


def upgrade() -> None:
    from sqlalchemy import inspect as sa_inspect

    bind = op.get_bind()
    existing = set(sa_inspect(bind).get_table_names())
    if "lead_hygiene_report_runs" in existing:
        return

    json_type = _json_type()
    op.create_table(
        "lead_hygiene_report_runs",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("job_id", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("phase", sa.String(length=64), nullable=True),
        sa.Column("params", json_type, nullable=True),
        sa.Column("summary", json_type, nullable=True),
        sa.Column("report_payload", json_type, nullable=True),
        sa.Column("csv_text", sa.Text(), nullable=True),
        sa.Column("sources", json_type, nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("job_id", name="uq_lead_hygiene_report_runs_job_id"),
    )
    op.create_index("ix_lead_hygiene_report_runs_job_id", "lead_hygiene_report_runs", ["job_id"])
    op.create_index("ix_lead_hygiene_report_runs_status", "lead_hygiene_report_runs", ["status"])
    op.create_index("ix_lead_hygiene_report_runs_started_at", "lead_hygiene_report_runs", ["started_at"])
    op.create_index("ix_lead_hygiene_report_runs_deleted_at", "lead_hygiene_report_runs", ["deleted_at"])


def downgrade() -> None:
    from sqlalchemy import inspect as sa_inspect

    bind = op.get_bind()
    existing = set(sa_inspect(bind).get_table_names())
    if "lead_hygiene_report_runs" not in existing:
        return
    op.drop_index("ix_lead_hygiene_report_runs_deleted_at", table_name="lead_hygiene_report_runs")
    op.drop_index("ix_lead_hygiene_report_runs_started_at", table_name="lead_hygiene_report_runs")
    op.drop_index("ix_lead_hygiene_report_runs_status", table_name="lead_hygiene_report_runs")
    op.drop_index("ix_lead_hygiene_report_runs_job_id", table_name="lead_hygiene_report_runs")
    op.drop_table("lead_hygiene_report_runs")
