"""Add agents and testimonials tables, seed Seb's agent record.

Revision ID: 007_add_agents_testimonials
Revises: 006_seed_seb_final
Create Date: 2026-03-04
"""
import json
from alembic import op
import sqlalchemy as sa

revision = "007_add_agents_testimonials"
down_revision = "006_seed_seb_final"
branch_labels = None
depends_on = None

# Seb's carrier list from FalconVerify Carriers.tsx
CARRIERS = json.dumps([
    "Transamerica", "Mutual of Omaha", "AIG", "Americo",
    "Foresters Financial", "Protective Life", "Prudential",
    "Lincoln Financial", "Pacific Life", "Penn Mutual",
    "Nationwide", "Securian Financial",
])

SEB_BIO = (
    "Independent life insurance broker with access to 47+ A-rated carriers. "
    "Specializing in mortgage protection, term life, IUL, and final expense coverage."
)


def upgrade() -> None:
    # Create agents table
    op.create_table(
        "agents",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("user_id", sa.String(128), unique=True, nullable=False, index=True),
        sa.Column("slug", sa.String(64), unique=True, nullable=False, index=True),
        sa.Column("name", sa.String(256), nullable=False),
        sa.Column("title", sa.String(256), nullable=True),
        sa.Column("bio", sa.Text, nullable=True),
        sa.Column("photo_url", sa.String(512), nullable=True),
        sa.Column("phone", sa.String(20), nullable=True),
        sa.Column("phone_display", sa.String(20), nullable=True),
        sa.Column("email", sa.String(256), nullable=True),
        sa.Column("calendar_url", sa.String(512), nullable=True),
        sa.Column("npn", sa.String(20), nullable=True),
        sa.Column("location", sa.String(256), nullable=True),
        sa.Column("carrier_count", sa.Integer, server_default="47"),
        sa.Column("carriers_json", sa.Text, nullable=True),
        sa.Column("is_active", sa.Boolean, server_default="true"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    # Create testimonials table
    op.create_table(
        "testimonials",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("agent_id", sa.Integer, nullable=False, index=True),
        sa.Column("client_name", sa.String(128), nullable=False),
        sa.Column("text", sa.Text, nullable=False),
        sa.Column("rating", sa.Integer, server_default="5"),
        sa.Column("date", sa.Date, nullable=True),
        sa.Column("is_published", sa.Boolean, server_default="true"),
        sa.Column("sort_order", sa.Integer, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    # Seed Seb's agent record
    op.execute(
        f"""INSERT INTO agents (user_id, slug, name, title, bio, phone, phone_display, email, npn, location, carrier_count, carriers_json, is_active, created_at, updated_at)
        VALUES (
            '72dc5b7c-ba2c-4a1d-83b9-733ff600c0d5',
            'seb',
            'Sébastien Taillieu',
            'Founder & Principal Advisor',
            '{SEB_BIO}',
            '+14809999040',
            '(480) 999-9040',
            'seb@falconfinancial.org',
            '21408357',
            'Scottsdale Airpark, Arizona',
            47,
            '{CARRIERS.replace(chr(39), chr(39)*2)}',
            true,
            NOW(),
            NOW()
        ) ON CONFLICT DO NOTHING;"""
    )


def downgrade() -> None:
    op.drop_table("testimonials")
    op.drop_table("agents")
