"""Add licenses table for agent license verification (FalconVerify).

Revision ID: 002_licenses
Revises: 001_initial
Create Date: 2026-03-03
"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "002_licenses"
down_revision = "001_initial"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "licenses",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.String(length=128), nullable=False),
        sa.Column("state", sa.String(length=64), nullable=False),
        sa.Column("state_abbreviation", sa.String(length=2), nullable=False),
        sa.Column("license_number", sa.String(length=64), nullable=True),
        sa.Column("verify_url", sa.String(length=512), nullable=True),
        sa.Column("needs_manual_verification", sa.Boolean(), server_default="false"),
        sa.Column("status", sa.String(length=16), server_default="active"),
        sa.Column("license_type", sa.String(length=64), server_default="insurance_producer"),
        sa.Column("issue_date", sa.Date(), nullable=True),
        sa.Column("expiry_date", sa.Date(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_licenses_user_id", "licenses", ["user_id"])
    op.create_index("ix_licenses_state_abbreviation", "licenses", ["state_abbreviation"])
    op.create_index("ix_licenses_status", "licenses", ["status"])
    op.create_index("ix_licenses_expiry_date", "licenses", ["expiry_date"])


def downgrade() -> None:
    op.drop_table("licenses")
