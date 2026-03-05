"""De-duplicate license rows caused by user_id mismatch (Bug 2 cleanup).

The old FC v3 UUID rows were updated to Clerk ID by migration 008,
but startup seed may have already inserted Clerk ID rows — creating duplicates.
This migration keeps the newest row per (user_id, state_abbreviation) and deletes the rest.

Revision ID: 009_dedup_licenses
Revises: 008_drop_expiry_fix_uids
Create Date: 2026-03-05
"""
from alembic import op

revision = "009_dedup_licenses"
down_revision = "008_drop_expiry_fix_uids"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Delete duplicate license rows, keeping the one with the highest ID (most recent)
    op.execute(
        """DELETE FROM licenses
           WHERE id NOT IN (
               SELECT MAX(id)
               FROM licenses
               GROUP BY user_id, state_abbreviation
           )"""
    )


def downgrade() -> None:
    pass  # Can't un-delete rows
