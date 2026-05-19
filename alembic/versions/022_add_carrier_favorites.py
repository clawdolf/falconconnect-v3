"""Add 3 Way Bridge carrier favorites.

Revision ID: 022_add_carrier_favorites
Revises: 021_add_registry_tables
Create Date: 2026-05-19
"""
import sqlalchemy as sa
from alembic import op

revision = "022_add_carrier_favorites"
down_revision = "021_add_registry_tables"
branch_labels = None
depends_on = None


def upgrade() -> None:
    from sqlalchemy import inspect as sa_inspect

    bind = op.get_bind()
    existing = set(sa_inspect(bind).get_table_names())
    if "carrier_favorites" in existing:
        return

    op.create_table(
        "carrier_favorites",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.String(length=128), nullable=False),
        sa.Column("carrier_name", sa.String(length=256), nullable=False),
        sa.Column("carrier_dept", sa.String(length=256), nullable=False, server_default=""),
        sa.Column("carrier_number", sa.String(length=32), nullable=False),
        sa.Column("dial_instructions", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_carrier_favorites_user_id", "carrier_favorites", ["user_id"])
    op.create_index("ix_carrier_favorites_user_name_dept", "carrier_favorites", ["user_id", "carrier_name", "carrier_dept"])


def downgrade() -> None:
    from sqlalchemy import inspect as sa_inspect

    bind = op.get_bind()
    existing = set(sa_inspect(bind).get_table_names())
    if "carrier_favorites" not in existing:
        return
    op.drop_index("ix_carrier_favorites_user_name_dept", table_name="carrier_favorites")
    op.drop_index("ix_carrier_favorites_user_id", table_name="carrier_favorites")
    op.drop_table("carrier_favorites")
