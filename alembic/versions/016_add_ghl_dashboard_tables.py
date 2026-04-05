"""Add GHL dashboard tables for read-only intel layer.

Revision ID: 016_add_ghl_dashboard_tables
Revises: 015_add_close_lead_id_to_lead_xref
Create Date: 2026-04-01
"""
import sqlalchemy as sa
from alembic import op

revision = "016_add_ghl_dashboard_tables"
down_revision = "015_add_close_lead_id_to_lead_xref"
branch_labels = None
depends_on = None


def upgrade() -> None:
    from sqlalchemy import inspect as sa_inspect
    bind = op.get_bind()
    existing = sa_inspect(bind).get_table_names()
    if "ghl_dashboard_sync_log" in existing:
        return  # tables already exist, skip
    op.create_table(
        "ghl_dashboard_sync_log",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("sync_type", sa.String(64), nullable=False),
        sa.Column("started_at", sa.DateTime(), nullable=False),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.Column("records_processed", sa.Integer(), server_default="0", nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("error_msg", sa.Text(), nullable=True),
    )

    op.create_table(
        "ghl_dashboard_contact_cache",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("ghl_contact_id", sa.String(128), nullable=False, unique=True),
        sa.Column("name", sa.String(256), nullable=True),
        sa.Column("email", sa.String(256), nullable=True),
        sa.Column("phone", sa.String(64), nullable=True),
        sa.Column("tags", sa.Text(), nullable=True),
        sa.Column("dnd_status", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("last_activity_at", sa.DateTime(), nullable=True),
        sa.Column("cached_at", sa.DateTime(), nullable=False),
    )

    op.create_table(
        "ghl_dashboard_compliance_results",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("run_at", sa.DateTime(), nullable=False),
        sa.Column("total_contacts", sa.Integer(), nullable=False),
        sa.Column("compliant_count", sa.Integer(), nullable=False),
        sa.Column("issue_count", sa.Integer(), nullable=False),
        sa.Column("results_json", sa.Text(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("ghl_dashboard_compliance_results")
    op.drop_table("ghl_dashboard_contact_cache")
    op.drop_table("ghl_dashboard_sync_log")
