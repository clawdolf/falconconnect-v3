"""Drop issue_date/expiry_date from licenses, fix seed user_ids to Clerk IDs.

Bug 6: Remove expiry/issue date columns entirely — not applicable to insurance licenses.
Bug 2: Update seed user_ids from FC v3 UUID to Clerk user ID so licenses
       are visible to the JWT-authenticated user.

Revision ID: 008_drop_expiry_fix_uids
Revises: 007_add_agents_testimonials
Create Date: 2026-03-04
"""
from alembic import op
import sqlalchemy as sa

revision = "008_drop_expiry_fix_uids"
down_revision = "007_add_agents_testimonials"
branch_labels = None
depends_on = None

OLD_UID = "72dc5b7c-ba2c-4a1d-83b9-733ff600c0d5"
NEW_UID = "user_3ASrwDOrSTaDxCus6f1B5lnDsgz"


def upgrade() -> None:
    # Drop the expiry_date index first, then the columns
    op.drop_index("ix_licenses_expiry_date", table_name="licenses")
    op.drop_column("licenses", "expiry_date")
    op.drop_column("licenses", "issue_date")

    # Fix user_id mismatch: migrate old FC UUID to Clerk user ID
    # for both licenses and agents tables
    op.execute(
        f"UPDATE licenses SET user_id = '{NEW_UID}' WHERE user_id = '{OLD_UID}'"
    )
    op.execute(
        f"UPDATE agents SET user_id = '{NEW_UID}' WHERE user_id = '{OLD_UID}'"
    )


def downgrade() -> None:
    # Re-add columns
    op.add_column("licenses", sa.Column("issue_date", sa.Date(), nullable=True))
    op.add_column("licenses", sa.Column("expiry_date", sa.Date(), nullable=True))
    op.create_index("ix_licenses_expiry_date", "licenses", ["expiry_date"])

    # Revert user_id change
    op.execute(
        f"UPDATE licenses SET user_id = '{OLD_UID}' WHERE user_id = '{NEW_UID}'"
    )
    op.execute(
        f"UPDATE agents SET user_id = '{OLD_UID}' WHERE user_id = '{NEW_UID}'"
    )
