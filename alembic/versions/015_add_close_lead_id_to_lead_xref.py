"""Add close_lead_id to lead_xref and make notion_page_id nullable.

Revision ID: 015_add_close_lead_id_to_lead_xref
Revises: 014_migrate_dummy_email_domain
Create Date: 2026-03-28
"""
import sqlalchemy as sa
from alembic import op

revision = "015_add_close_lead_id_to_lead_xref"
down_revision = "014_migrate_dummy_email_domain"
branch_labels = None
depends_on = None


def upgrade() -> None:
    from sqlalchemy import inspect as sa_inspect
    bind = op.get_bind()
    cols = [c["name"] for c in sa_inspect(bind).get_columns("lead_xref")]
    idxs = [i["name"] for i in sa_inspect(bind).get_indexes("lead_xref")]

    if "close_lead_id" not in cols:
        op.add_column(
            "lead_xref",
            sa.Column("close_lead_id", sa.String(64), nullable=True),
        )
    if "ix_lead_xref_close_lead_id" not in idxs:
        op.create_index("ix_lead_xref_close_lead_id", "lead_xref", ["close_lead_id"])

    with op.batch_alter_table("lead_xref") as batch_op:
        batch_op.alter_column(
            "notion_page_id",
            existing_type=sa.String(64),
            nullable=True,
        )

def downgrade() -> None:
    op.drop_index("ix_lead_xref_close_lead_id", table_name="lead_xref")
    op.drop_column("lead_xref", "close_lead_id")

    with op.batch_alter_table("lead_xref") as batch_op:
        batch_op.alter_column(
            "notion_page_id",
            existing_type=sa.String(64),
            nullable=False,
        )
