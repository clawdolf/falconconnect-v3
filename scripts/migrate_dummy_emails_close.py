#!/usr/bin/env python3
"""Migrate dummy calendar emails on Close contacts from old to new domain.

For each row in appointment_calendar_emails with the old domain:
1. Find the Close contact
2. Remove old dummy email, add new dummy email
3. Update the DB row
4. Log progress and errors

Usage:
    python3 scripts/migrate_dummy_emails_close.py [--dry-run]

Requires: DATABASE_URL, CLOSE_API_KEY env vars (or from config).
"""

import argparse
import json
import logging
import os
import sys
import time

import httpx

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s %(message)s",
)
logger = logging.getLogger(__name__)

OLD_DOMAIN = "@cal.falconnect.org"
NEW_DOMAIN = "@appt.invalid"
CLOSE_API_BASE = "https://api.close.com/api/v1"


def get_db_connection():
    """Get a psycopg2 connection using DATABASE_URL."""
    import psycopg2

    db_url = os.environ.get("DATABASE_URL", "")
    if not db_url:
        # Try loading from config
        try:
            from config import get_settings
            db_url = get_settings().database_url
        except Exception:
            raise RuntimeError("DATABASE_URL not set and config not loadable")

    # Strip asyncpg driver prefix
    db_url = db_url.replace("postgresql+asyncpg://", "postgresql://")
    return psycopg2.connect(db_url)


def get_close_api_key() -> str:
    """Get Close API key from env or config."""
    key = os.environ.get("CLOSE_API_KEY", "")
    if not key:
        try:
            from config import get_settings
            key = get_settings().close_api_key
        except Exception:
            pass
    if not key:
        raise RuntimeError("CLOSE_API_KEY not set")
    return key


def get_contact(api_key: str, contact_id: str) -> dict | None:
    """Fetch a Close contact by ID."""
    try:
        resp = httpx.get(
            f"{CLOSE_API_BASE}/contact/{contact_id}/",
            auth=(api_key, ""),
            timeout=30.0,
        )
        resp.raise_for_status()
        return resp.json()
    except Exception as exc:
        logger.error("Failed to fetch contact %s: %s", contact_id, exc)
        return None


def update_contact_emails(api_key: str, contact_id: str, emails: list[dict]) -> bool:
    """Update a Close contact's email list."""
    try:
        resp = httpx.put(
            f"{CLOSE_API_BASE}/contact/{contact_id}/",
            json={"emails": emails},
            auth=(api_key, ""),
            timeout=30.0,
        )
        resp.raise_for_status()
        return True
    except Exception as exc:
        logger.error("Failed to update contact %s emails: %s", contact_id, exc)
        return False


def main():
    parser = argparse.ArgumentParser(description="Migrate dummy emails on Close contacts")
    parser.add_argument("--dry-run", action="store_true", help="Show what would change without modifying")
    args = parser.parse_args()

    api_key = get_close_api_key()
    conn = get_db_connection()
    cur = conn.cursor()

    # Fetch all rows with old domain
    cur.execute(
        "SELECT id, lead_id, contact_id, dummy_email FROM appointment_calendar_emails "
        "WHERE dummy_email LIKE %s ORDER BY id;",
        (f"%{OLD_DOMAIN}",),
    )
    rows = cur.fetchall()
    logger.info("Found %d rows with old domain", len(rows))

    if not rows:
        logger.info("Nothing to migrate — all emails already use new domain or table is empty.")
        conn.close()
        return

    updated = 0
    failed = 0
    skipped = 0

    for row_id, lead_id, contact_id, old_email in rows:
        new_email = old_email.replace(OLD_DOMAIN, NEW_DOMAIN)
        logger.info("Processing id=%d lead=%s: %s -> %s", row_id, lead_id, old_email, new_email)

        if args.dry_run:
            logger.info("  [DRY RUN] Would update contact %s and DB row %d", contact_id, row_id)
            updated += 1
            continue

        # Fetch current contact
        contact = get_contact(api_key, contact_id)
        if not contact:
            logger.warning("  Contact %s not found — skipping", contact_id)
            skipped += 1
            continue

        # Update email list: replace old with new
        current_emails = contact.get("emails", [])
        new_emails = []
        found_old = False
        for entry in current_emails:
            if entry.get("email", "").lower() == old_email.lower():
                # Replace with new domain
                new_emails.append({"email": new_email, "type": entry.get("type", "Calendar")})
                found_old = True
            else:
                new_emails.append(entry)

        if not found_old:
            # Old email not on contact — just add the new one
            logger.info("  Old email not found on contact — adding new email directly")
            new_emails.append({"email": new_email, "type": "Calendar"})

        # Update Close contact
        if not update_contact_emails(api_key, contact_id, new_emails):
            logger.error("  Failed to update Close contact %s", contact_id)
            failed += 1
            continue

        # Update DB row
        cur.execute(
            "UPDATE appointment_calendar_emails SET dummy_email = %s WHERE id = %s;",
            (new_email, row_id),
        )
        conn.commit()
        updated += 1
        logger.info("  Updated successfully")

        # Rate limit: Close API has ~100 req/min limit
        time.sleep(0.7)

    conn.close()

    logger.info("Migration complete: %d updated, %d failed, %d skipped", updated, failed, skipped)
    print(f"\nSummary: {updated} updated, {failed} failed, {skipped} skipped (of {len(rows)} total)")


if __name__ == "__main__":
    main()
