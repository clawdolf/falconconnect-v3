"""Add sms_templates and phone_numbers tables.

Revision ID: 013
Revises: 012_add_appointment_tables
"""

from alembic import op
import sqlalchemy as sa

revision = "013"
down_revision = "012_add_appointment_tables"
branch_labels = None
depends_on = None


def upgrade() -> None:
    from sqlalchemy import inspect as sa_inspect
    bind = op.get_bind()
    existing = sa_inspect(bind).get_table_names()

    if "sms_templates" not in existing:
        op.create_table(
            "sms_templates",
            sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
            sa.Column("template_key", sa.String(32), unique=True, nullable=False, index=True),
            sa.Column("body", sa.Text, nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), onupdate=sa.func.now()),
        )

    if "phone_numbers" not in existing:
        op.create_table(
            "phone_numbers",
            sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
            sa.Column("number", sa.String(20), unique=True, nullable=False, index=True),
            sa.Column("state", sa.String(2), nullable=False),
            sa.Column("area_codes_json", sa.Text, nullable=False),
            sa.Column("is_active", sa.Boolean, default=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        )

def downgrade() -> None:
    op.drop_table("phone_numbers")
    op.drop_table("sms_templates")
