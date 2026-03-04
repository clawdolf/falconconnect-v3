#!/usr/bin/env python3
"""Backfill lead_xref table by matching GHL contacts to Notion pages by phone.

Usage:
    python3 scripts/backfill_xref.py --dry-run   # preview what would be inserted
    python3 scripts/backfill_xref.py              # actually insert rows

Reads DATABASE_URL, GHL_API_KEY, GHL_LOCATION_ID, NOTION_TOKEN, and
NOTION_LEADS_DB_ID from .env in the project root.
"""

import argparse
import asyncio
import logging
import os
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

import httpx
from dotenv import load_dotenv

# Load .env from project root
PROJECT_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(PROJECT_ROOT / ".env")

# -- Config --
DATABASE_URL = os.environ.get("DATABASE_URL", "")
GHL_API_KEY = os.environ.get("GHL_API_KEY", "")
GHL_LOCATION_ID = os.environ.get("GHL_LOCATION_ID", "")
NOTION_TOKEN = os.environ.get("NOTION_TOKEN", "")
NOTION_LEADS_DB_ID = os.environ.get("NOTION_LEADS_DB_ID", "REPLACE_WITH_YOUR_NOTION_DATABASE_ID")

GHL_BASE = "https://services.leadconnectorhq.com"
GHL_API_VERSION = "2021-07-28"
NOTION_BASE = "https://api.notion.com/v1"
NOTION_VERSION = "2022-06-28"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger("backfill_xref")


def normalize_phone(raw: str) -> str:
    """Strip to digits only (no +, no dashes). Returns 10 digits for US numbers."""
    if not raw:
        return ""
    digits = re.sub(r"[^\d]", "", raw.strip())
    if len(digits) == 11 and digits.startswith("1"):
        return digits[1:]  # strip leading 1
    if len(digits) == 10:
        return digits
    return digits  # return whatever we have


def normalize_phone_e164(raw: str) -> str:
    """Normalize to E.164 (+1XXXXXXXXXX) for storage."""
    digits = normalize_phone(raw)
    if len(digits) == 10:
        return f"+1{digits}"
    if len(digits) == 11 and digits.startswith("1"):
        return f"+{digits}"
    return f"+{digits}" if digits else ""


# -- GHL helpers --

def ghl_headers() -> Dict[str, str]:
    return {
        "Authorization": f"Bearer {GHL_API_KEY}",
        "Version": GHL_API_VERSION,
        "Content-Type": "application/json",
        "Accept": "application/json",
    }


async def fetch_all_ghl_contacts() -> List[Dict[str, Any]]:
    """Paginate through all GHL contacts. Returns list of contact dicts."""
    contacts: List[Dict[str, Any]] = []
    next_page_url: Optional[str] = None

    async with httpx.AsyncClient(timeout=60) as client:
        # First request
        params = {"locationId": GHL_LOCATION_ID, "limit": 100}
        resp = await client.get(
            f"{GHL_BASE}/contacts/",
            headers=ghl_headers(),
            params=params,
        )
        resp.raise_for_status()
        data = resp.json()
        contacts.extend(data.get("contacts", []))
        next_page_url = data.get("meta", {}).get("nextPageUrl")
        logger.info("GHL page 1: %d contacts (total so far: %d)", len(data.get("contacts", [])), len(contacts))

        page = 2
        while next_page_url:
            resp = await client.get(next_page_url, headers=ghl_headers())
            resp.raise_for_status()
            data = resp.json()
            batch = data.get("contacts", [])
            contacts.extend(batch)
            next_page_url = data.get("meta", {}).get("nextPageUrl")
            logger.info("GHL page %d: %d contacts (total: %d)", page, len(batch), len(contacts))
            page += 1
            if not batch:
                break

    return contacts


# -- Notion helpers --

def notion_headers() -> Dict[str, str]:
    return {
        "Authorization": f"Bearer {NOTION_TOKEN}",
        "Notion-Version": NOTION_VERSION,
        "Content-Type": "application/json",
    }


async def search_notion_by_phone(phone_digits: str) -> Optional[Dict[str, Any]]:
    """Search the Notion leads DB for a page whose Mobile Phone matches.

    Tries both raw digits and E.164 format since Notion may store either.
    """
    e164 = f"+1{phone_digits}" if len(phone_digits) == 10 else phone_digits

    for phone_variant in [e164, phone_digits]:
        payload = {
            "filter": {
                "property": "Mobile Phone",
                "phone_number": {"equals": phone_variant},
            },
            "page_size": 1,
        }
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                f"{NOTION_BASE}/databases/{NOTION_LEADS_DB_ID}/query",
                headers=notion_headers(),
                json=payload,
            )
            resp.raise_for_status()
            results = resp.json().get("results", [])
            if results:
                return results[0]

    return None


# -- DB helpers (sync via psycopg2 since this is a one-off script) --

def get_db_connection():
    """Create a sync DB connection from DATABASE_URL."""
    url = DATABASE_URL
    if not url:
        raise ValueError("DATABASE_URL not set in .env")

    # SQLAlchemy async URL → sync psycopg2 URL
    url = url.replace("postgresql+asyncpg://", "postgresql://")
    url = url.replace("sqlite+aiosqlite:///", "sqlite:///")

    if url.startswith("postgresql://"):
        import psycopg2
        return psycopg2.connect(url)
    elif url.startswith("sqlite:///"):
        import sqlite3
        db_path = url.replace("sqlite:///", "")
        return sqlite3.connect(db_path)
    else:
        raise ValueError(f"Unsupported DATABASE_URL scheme: {url}")


def fetch_existing_xrefs(conn) -> Set[str]:
    """Return set of ghl_contact_ids that already have xref rows."""
    cursor = conn.cursor()
    cursor.execute("SELECT ghl_contact_id FROM lead_xref")
    return {row[0] for row in cursor.fetchall()}


def fetch_existing_phones(conn) -> Set[str]:
    """Return set of phones that already have xref rows."""
    cursor = conn.cursor()
    cursor.execute("SELECT phone FROM lead_xref")
    return {row[0] for row in cursor.fetchall()}


def insert_xref(conn, ghl_contact_id: str, notion_page_id: str, phone: str,
                first_name: str = "", last_name: str = ""):
    """Insert a new lead_xref row."""
    cursor = conn.cursor()
    cursor.execute(
        """INSERT INTO lead_xref (ghl_contact_id, notion_page_id, phone, first_name, last_name)
           VALUES (%s, %s, %s, %s, %s)""",
        (ghl_contact_id, notion_page_id, phone, first_name, last_name),
    )


def insert_xref_sqlite(conn, ghl_contact_id: str, notion_page_id: str, phone: str,
                        first_name: str = "", last_name: str = ""):
    """Insert a new lead_xref row (SQLite variant)."""
    cursor = conn.cursor()
    cursor.execute(
        """INSERT INTO lead_xref (ghl_contact_id, notion_page_id, phone, first_name, last_name)
           VALUES (?, ?, ?, ?, ?)""",
        (ghl_contact_id, notion_page_id, phone, first_name, last_name),
    )


async def main(dry_run: bool = False):
    logger.info("=== Backfill lead_xref — %s mode ===", "DRY RUN" if dry_run else "LIVE")

    # 1. Connect to DB and get existing xrefs
    conn = get_db_connection()
    is_sqlite = DATABASE_URL.startswith("sqlite")
    existing_ghl_ids = fetch_existing_xrefs(conn)
    existing_phones = fetch_existing_phones(conn)
    logger.info("Existing xref rows: %d (by ghl_id), %d (by phone)", len(existing_ghl_ids), len(existing_phones))

    # 2. Fetch all GHL contacts
    ghl_contacts = await fetch_all_ghl_contacts()
    logger.info("Total GHL contacts fetched: %d", len(ghl_contacts))

    # 3. For each contact, try to match to Notion
    matched = 0
    skipped_existing = 0
    not_found = 0
    errors = 0

    for i, contact in enumerate(ghl_contacts):
        contact_id = contact.get("id", "")
        if not contact_id:
            continue

        # Skip if already in xref
        if contact_id in existing_ghl_ids:
            skipped_existing += 1
            continue

        # Get primary phone from GHL contact
        raw_phone = contact.get("phone", "")
        if not raw_phone:
            not_found += 1
            continue

        phone_digits = normalize_phone(raw_phone)
        if not phone_digits or len(phone_digits) < 10:
            not_found += 1
            continue

        phone_e164 = normalize_phone_e164(raw_phone)

        # Skip if this phone is already mapped
        if phone_e164 in existing_phones or phone_digits in existing_phones:
            skipped_existing += 1
            continue

        # Search Notion for this phone
        try:
            notion_page = await search_notion_by_phone(phone_digits)
        except Exception as exc:
            logger.warning("Notion search failed for %s: %s", phone_digits, exc)
            errors += 1
            continue

        if not notion_page:
            not_found += 1
            continue

        notion_page_id = notion_page["id"]
        first_name = contact.get("firstName", "")
        last_name = contact.get("lastName", "")

        if dry_run:
            logger.info(
                "[DRY RUN] Would insert: ghl=%s notion=%s phone=%s name=%s %s",
                contact_id, notion_page_id, phone_e164, first_name, last_name,
            )
        else:
            try:
                if is_sqlite:
                    insert_xref_sqlite(conn, contact_id, notion_page_id, phone_e164, first_name, last_name)
                else:
                    insert_xref(conn, contact_id, notion_page_id, phone_e164, first_name, last_name)
                logger.info(
                    "Inserted xref: ghl=%s notion=%s phone=%s name=%s %s",
                    contact_id, notion_page_id, phone_e164, first_name, last_name,
                )
            except Exception as exc:
                logger.warning("Insert failed for %s: %s", contact_id, exc)
                errors += 1
                continue

        matched += 1
        existing_ghl_ids.add(contact_id)
        existing_phones.add(phone_e164)

        # Rate limit: avoid hammering Notion API
        if (i + 1) % 10 == 0:
            await asyncio.sleep(0.5)

    if not dry_run:
        conn.commit()

    conn.close()

    logger.info("=== Backfill complete ===")
    logger.info("Matched & inserted: %d", matched)
    logger.info("Skipped (already exists): %d", skipped_existing)
    logger.info("Not found in Notion: %d", not_found)
    logger.info("Errors: %d", errors)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Backfill lead_xref by matching GHL contacts to Notion pages")
    parser.add_argument("--dry-run", action="store_true", help="Preview without inserting")
    args = parser.parse_args()

    asyncio.run(main(dry_run=args.dry_run))
