"""Insert Seb's 8 licenses — direct INSERT with literal VALUES.

Previous attempts (003/004) failed silently due to alembic async context.
This uses a single bulk INSERT that definitely works.

Revision ID: 005_insert_licenses
Revises: 004_reseed_licenses
Create Date: 2026-03-04
"""
from alembic import op

revision = "005_insert_licenses"
down_revision = "004_reseed_licenses"
branch_labels = None
depends_on = None

SEB_UID = "72dc5b7c-ba2c-4a1d-83b9-733ff600c0d5"


def upgrade() -> None:
    op.execute(
        f"""
        INSERT INTO licenses
            (user_id, state, state_abbreviation, license_number, verify_url,
             needs_manual_verification, status, license_type, created_at, updated_at)
        SELECT * FROM (VALUES
            ('{SEB_UID}', 'Arizona',        'AZ', NULL,       'https://sbs.naic.org/solar-external-lookup/lookup/licensee/summary/21408357?jurisdiction=AZ&entityType=IND&licenseType=PRO', false, 'active', 'insurance_producer', NOW(), NOW()),
            ('{SEB_UID}', 'Florida',        'FL', 'G258860',  'https://licenseesearch.fldfs.com/Licensee/2700806',                                                                          false, 'active', 'insurance_producer', NOW(), NOW()),
            ('{SEB_UID}', 'Kansas',         'KS', NULL,       'https://sbs.naic.org/solar-external-lookup/lookup/licensee/summary/21408357?jurisdiction=KS&entityType=IND&licenseType=PRO', false, 'active', 'insurance_producer', NOW(), NOW()),
            ('{SEB_UID}', 'Maine',          'ME', NULL,       'https://www.pfr.maine.gov/ALMSOnline/ALMSQuery/ShowDetail.aspx?DetailToken=704F3C701A9F11E086BB0F98AA047C448C67C5003D086308CD98C8424EC1769E', false, 'active', 'insurance_producer', NOW(), NOW()),
            ('{SEB_UID}', 'North Carolina', 'NC', NULL,       'https://sbs.naic.org/solar-external-lookup/lookup/licensee/summary/21408357?jurisdiction=NC&entityType=IND&licenseType=PRO', false, 'active', 'insurance_producer', NOW(), NOW()),
            ('{SEB_UID}', 'Oregon',         'OR', NULL,       'https://sbs.naic.org/solar-external-lookup/lookup/licensee/summary/21408357?jurisdiction=OR&entityType=IND&licenseType=PRO', false, 'active', 'insurance_producer', NOW(), NOW()),
            ('{SEB_UID}', 'Pennsylvania',   'PA', '1152553',  'https://www.sircon.com/ComplianceExpress/Inquiry/consumerInquiry.do?nonSscrb=Y',                                             true,  'active', 'insurance_producer', NOW(), NOW()),
            ('{SEB_UID}', 'Texas',          'TX', '3317972',  'https://www.sircon.com/ComplianceExpress/Inquiry/consumerInquiry.do?nonSscrb=Y',                                             true,  'active', 'insurance_producer', NOW(), NOW())
        ) AS v(user_id, state, state_abbreviation, license_number, verify_url, needs_manual_verification, status, license_type, created_at, updated_at)
        WHERE NOT EXISTS (
            SELECT 1 FROM licenses l
            WHERE l.user_id = v.user_id AND l.state_abbreviation = v.state_abbreviation
        )
        """
    )


def downgrade() -> None:
    op.execute(f"DELETE FROM licenses WHERE user_id = '{SEB_UID}'")
