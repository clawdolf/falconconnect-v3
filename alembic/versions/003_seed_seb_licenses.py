"""Seed Seb's 8 active insurance licenses — v2 prod DB migration.

NPN: 21408357  |  User ID: 72dc5b7c-ba2c-4a1d-83b9-733ff600c0d5

Revision ID: 003_seed_seb_licenses
Revises: 002_licenses
Create Date: 2026-03-04
"""
from alembic import op

revision = "003_seed_seb_licenses"
down_revision = "002_licenses"
branch_labels = None
depends_on = None

SEB_UID = "user_3ASrwDOrSTaDxCus6f1B5lnDsgz"


def upgrade() -> None:
    # All values are hardcoded constants — safe to interpolate directly.
    # Using op.execute(str) is the correct modern pattern (no get_bind, no bindparams).
    rows = [
        ("Arizona",        "AZ", "NULL",      "https://sbs.naic.org/solar-external-lookup/lookup/licensee/summary/21408357?jurisdiction=AZ&entityType=IND&licenseType=PRO", "false"),
        ("Florida",        "FL", "'G258860'", "https://licenseesearch.fldfs.com/Licensee/2700806", "false"),
        ("Kansas",         "KS", "NULL",      "https://sbs.naic.org/solar-external-lookup/lookup/licensee/summary/21408357?jurisdiction=KS&entityType=IND&licenseType=PRO", "false"),
        ("Maine",          "ME", "NULL",      "https://www.pfr.maine.gov/ALMSOnline/ALMSQuery/ShowDetail.aspx?DetailToken=704F3C701A9F11E086BB0F98AA047C448C67C5003D086308CD98C8424EC1769E", "false"),
        ("North Carolina", "NC", "NULL",      "https://sbs.naic.org/solar-external-lookup/lookup/licensee/summary/21408357?jurisdiction=NC&entityType=IND&licenseType=PRO", "false"),
        ("Oregon",         "OR", "NULL",      "https://sbs.naic.org/solar-external-lookup/lookup/licensee/summary/21408357?jurisdiction=OR&entityType=IND&licenseType=PRO", "false"),
        ("Pennsylvania",   "PA", "'1152553'", "https://www.sircon.com/ComplianceExpress/Inquiry/consumerInquiry.do?nonSscrb=Y", "true"),
        ("Texas",          "TX", "'3317972'", "https://www.sircon.com/ComplianceExpress/Inquiry/consumerInquiry.do?nonSscrb=Y", "true"),
    ]
    for state, abbr, lic_num, verify_url, manual in rows:
        op.execute(
            f"INSERT INTO licenses "
            f"(user_id, state, state_abbreviation, license_number, verify_url, "
            f"needs_manual_verification, status, license_type, created_at, updated_at) "
            f"SELECT '{SEB_UID}', '{state}', '{abbr}', {lic_num}, '{verify_url}', "
            f"{manual}, 'active', 'insurance_producer', NOW(), NOW() "
            f"WHERE NOT EXISTS ("
            f"  SELECT 1 FROM licenses WHERE user_id='{SEB_UID}' AND state_abbreviation='{abbr}'"
            f")"
        )


def downgrade() -> None:
    op.execute(f"DELETE FROM licenses WHERE user_id='{SEB_UID}'")
