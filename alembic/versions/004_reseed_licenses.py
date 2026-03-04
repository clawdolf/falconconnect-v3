"""No-op migration — placeholder to preserve alembic version chain.

004 was previously written then removed from disk while already applied to DB.
This stub restores the chain: 003 -> 004 -> (future).

Revision ID: 004_reseed_licenses
Revises: 003_seed_seb_licenses
Create Date: 2026-03-04
"""
from alembic import op

revision = "004_reseed_licenses"
down_revision = "003_seed_seb_licenses"
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass  # No-op — data already seeded via app startup _seed_licenses_if_empty()


def downgrade() -> None:
    pass  # No-op
