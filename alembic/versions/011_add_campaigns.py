"""Add campaigns and campaign_variants tables.

Revision ID: 011_add_campaigns
Revises: 010_fix_agent_user_id
Create Date: 2026-03-09
"""
import sqlalchemy as sa
from alembic import op

revision = "011_add_campaigns"
down_revision = "010_fix_agent_user_id"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "campaigns",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("user_id", sa.String(128), nullable=False, index=True),
        sa.Column("name", sa.String(256), nullable=False),
        sa.Column("status", sa.String(32), nullable=False, server_default="draft", index=True),
        sa.Column("strategy_json", sa.Text(), nullable=True),
        sa.Column("meta_campaign_id", sa.String(128), nullable=True),
        sa.Column("meta_ad_account_id", sa.String(128), nullable=True),
        sa.Column("budget_daily", sa.Float(), nullable=False, server_default="0"),
        sa.Column("budget_total", sa.Float(), nullable=False, server_default="0"),
        sa.Column("target_audience_json", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    op.create_table(
        "campaign_variants",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("campaign_id", sa.Integer(), sa.ForeignKey("campaigns.id"), nullable=False, index=True),
        sa.Column("variant_name", sa.String(256), nullable=False),
        sa.Column("headline", sa.String(512), nullable=False),
        sa.Column("body_copy", sa.Text(), nullable=False),
        sa.Column("cta_text", sa.String(128), nullable=False),
        sa.Column("angle", sa.String(32), nullable=False),
        sa.Column("meta_ad_id", sa.String(128), nullable=True),
        sa.Column("impressions", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("clicks", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("leads", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("booked_appointments", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("spend", sa.Float(), nullable=False, server_default="0"),
        sa.Column("cpl", sa.Float(), nullable=False, server_default="0"),
        sa.Column("status", sa.String(32), nullable=False, server_default="active"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )


def downgrade() -> None:
    op.drop_table("campaign_variants")
    op.drop_table("campaigns")
