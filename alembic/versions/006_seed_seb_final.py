"""Final attempt: seed Seb's licenses using simple individual INSERT statements.

Revision ID: 006_seed_seb_final
Revises: 005_insert_licenses
Create Date: 2026-03-04
"""
from alembic import op

revision = "006_seed_seb_final"
down_revision = "005_insert_licenses"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Use absolute simplest approach: individual row INSERTs
    inserts = [
        "INSERT INTO licenses (user_id, state, state_abbreviation, license_number, verify_url, needs_manual_verification, status, license_type, created_at, updated_at) VALUES ('72dc5b7c-ba2c-4a1d-83b9-733ff600c0d5', 'Arizona', 'AZ', NULL, 'https://sbs.naic.org/solar-external-lookup/lookup/licensee/summary/21408357?jurisdiction=AZ&entityType=IND&licenseType=PRO', false, 'active', 'insurance_producer', NOW(), NOW()) ON CONFLICT DO NOTHING;",
        "INSERT INTO licenses (user_id, state, state_abbreviation, license_number, verify_url, needs_manual_verification, status, license_type, created_at, updated_at) VALUES ('72dc5b7c-ba2c-4a1d-83b9-733ff600c0d5', 'Florida', 'FL', 'G258860', 'https://licenseesearch.fldfs.com/Licensee/2700806', false, 'active', 'insurance_producer', NOW(), NOW()) ON CONFLICT DO NOTHING;",
        "INSERT INTO licenses (user_id, state, state_abbreviation, license_number, verify_url, needs_manual_verification, status, license_type, created_at, updated_at) VALUES ('72dc5b7c-ba2c-4a1d-83b9-733ff600c0d5', 'Kansas', 'KS', NULL, 'https://sbs.naic.org/solar-external-lookup/lookup/licensee/summary/21408357?jurisdiction=KS&entityType=IND&licenseType=PRO', false, 'active', 'insurance_producer', NOW(), NOW()) ON CONFLICT DO NOTHING;",
        "INSERT INTO licenses (user_id, state, state_abbreviation, license_number, verify_url, needs_manual_verification, status, license_type, created_at, updated_at) VALUES ('72dc5b7c-ba2c-4a1d-83b9-733ff600c0d5', 'Maine', 'ME', NULL, 'https://www.pfr.maine.gov/ALMSOnline/ALMSQuery/ShowDetail.aspx?DetailToken=704F3C701A9F11E086BB0F98AA047C448C67C5003D086308CD98C8424EC1769E', false, 'active', 'insurance_producer', NOW(), NOW()) ON CONFLICT DO NOTHING;",
        "INSERT INTO licenses (user_id, state, state_abbreviation, license_number, verify_url, needs_manual_verification, status, license_type, created_at, updated_at) VALUES ('72dc5b7c-ba2c-4a1d-83b9-733ff600c0d5', 'North Carolina', 'NC', NULL, 'https://sbs.naic.org/solar-external-lookup/lookup/licensee/summary/21408357?jurisdiction=NC&entityType=IND&licenseType=PRO', false, 'active', 'insurance_producer', NOW(), NOW()) ON CONFLICT DO NOTHING;",
        "INSERT INTO licenses (user_id, state, state_abbreviation, license_number, verify_url, needs_manual_verification, status, license_type, created_at, updated_at) VALUES ('72dc5b7c-ba2c-4a1d-83b9-733ff600c0d5', 'Oregon', 'OR', NULL, 'https://sbs.naic.org/solar-external-lookup/lookup/licensee/summary/21408357?jurisdiction=OR&entityType=IND&licenseType=PRO', false, 'active', 'insurance_producer', NOW(), NOW()) ON CONFLICT DO NOTHING;",
        "INSERT INTO licenses (user_id, state, state_abbreviation, license_number, verify_url, needs_manual_verification, status, license_type, created_at, updated_at) VALUES ('72dc5b7c-ba2c-4a1d-83b9-733ff600c0d5', 'Pennsylvania', 'PA', '1152553', 'https://www.sircon.com/ComplianceExpress/Inquiry/consumerInquiry.do?nonSscrb=Y', true, 'active', 'insurance_producer', NOW(), NOW()) ON CONFLICT DO NOTHING;",
        "INSERT INTO licenses (user_id, state, state_abbreviation, license_number, verify_url, needs_manual_verification, status, license_type, created_at, updated_at) VALUES ('72dc5b7c-ba2c-4a1d-83b9-733ff600c0d5', 'Texas', 'TX', '3317972', 'https://www.sircon.com/ComplianceExpress/Inquiry/consumerInquiry.do?nonSscrb=Y', true, 'active', 'insurance_producer', NOW(), NOW()) ON CONFLICT DO NOTHING;",
    ]
    for sql in inserts:
        op.execute(sql)


def downgrade() -> None:
    op.execute("DELETE FROM licenses WHERE user_id = '72dc5b7c-ba2c-4a1d-83b9-733ff600c0d5';")
