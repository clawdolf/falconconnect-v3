#!/usr/bin/env python3
"""Backfill lead_xref table by matching GHL contacts to Notion pages by phone.

Loads ALL Notion pages into memory first (one paginated fetch ~60 API calls),
then loops GHL contacts doing dict lookups — no API calls in the inner loop.

Usage:
    python3 scripts/backfill_xref.py --dry-run                          # preview
    python3 scripts/backfill_xref.py --dry-run --output /tmp/preview.csv # preview + CSV
    python3 scripts/backfill_xref.py                                     # actually insert rows

Reads DATABASE_URL, GHL_API_KEY, GHL_LOCATION_ID, NOTION_TOKEN, and
NOTION_LEADS_DB_ID from .env in the project root.
"""

import argparse
import asyncio
import csv
import logging
import os
import re
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

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
NOTION_LEADS_DB_ID = os.environ.get("NOTION_LEADS_DB_ID", "184d58e63823800f9b13f06aaa14e0e6")

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
    """Strip to digits, keep last 10, prefix with +1.

    Returns E.164 (+1XXXXXXXXXX) or empty string.
    """
    if not raw:
        return ""
    digits = re.sub(r"[^\d]", "", raw.strip())
    if not digits:
        return ""
    # Keep last 10 digits (handles +1, 1-prefix, or raw 10)
    if len(digits) >= 10:
        last10 = digits[-10:]
        return f"+1{last10}"
    return ""  # too short to be a US number


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


async def fetch_all_notion_pages() -> Dict[str, str]:
    """Fetch ALL pages from the Notion leads DB and build phone → page_id map.

    Bug 3 fix: Normalizes ALL phone numbers to E.164 before matching.
    Also checks Home Phone and Spouse Phone fields for additional matches.

    Uses paginated query (100 per page, ~60 API calls for 6000 pages).
    Returns dict: { normalized_phone: notion_page_id }
    """
    phone_map: Dict[str, str] = {}
    has_more = True
    start_cursor: Optional[str] = None
    total_pages = 0
    pages_with_phone = 0
    api_call = 0

    async with httpx.AsyncClient(timeout=60) as client:
        while has_more:
            api_call += 1
            payload: Dict[str, Any] = {"page_size": 100}
            if start_cursor:
                payload["start_cursor"] = start_cursor

            resp = await client.post(
                f"{NOTION_BASE}/databases/{NOTION_LEADS_DB_ID}/query",
                headers=notion_headers(),
                json=payload,
            )
            resp.raise_for_status()
            data = resp.json()

            results = data.get("results", [])
            total_pages += len(results)

            for page in results:
                page_id = page.get("id", "")
                props = page.get("properties", {})

                # Check all phone fields for maximum matching
                phone_fields = ["Mobile Phone", "Home Phone", "Spouse Phone"]
                found_phone = False

                for field_name in phone_fields:
                    prop = props.get(field_name, {})
                    raw_phone = ""
                    if prop.get("type") == "phone_number":
                        raw_phone = prop.get("phone_number") or ""
                    elif prop.get("type") == "rich_text":
                        texts = prop.get("rich_text", [])
                        raw_phone = "".join(t.get("plain_text", "") for t in texts)

                    if raw_phone and page_id:
                        # Bug 3 fix: Normalize to E.164 consistently
                        normalized = normalize_phone(str(raw_phone))
                        if normalized and normalized not in phone_map:
                            phone_map[normalized] = page_id
                            if not found_phone:
                                pages_with_phone += 1
                                found_phone = True

            has_more = data.get("has_more", False)
            start_cursor = data.get("next_cursor")

            if api_call % 10 == 0 or not has_more:
                logger.info(
                    "Notion fetch: %d API calls, %d pages loaded, %d with phone",
                    api_call, total_pages, pages_with_phone,
                )

            # Small delay to be kind to Notion rate limits (3 req/s for integrations)
            await asyncio.sleep(0.35)

    logger.info(
        "Notion fetch complete: %d total pages, %d with valid phone, %d phone entries in map, %d API calls",
        total_pages, pages_with_phone, len(phone_map), api_call,
    )
    return phone_map


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


async def main(dry_run: bool = False, output_path: Optional[str] = None):
    start_time = time.time()
    logger.info("=== Backfill lead_xref — %s mode ===", "DRY RUN" if dry_run else "LIVE")

    # 1. Load ALL Notion pages into memory (phone → page_id map)
    logger.info("Step 1: Loading all Notion pages into memory...")
    notion_phone_map = await fetch_all_notion_pages()
    logger.info("Notion phone map built: %d entries", len(notion_phone_map))

    # 2. Connect to DB and get existing xrefs
    conn = get_db_connection()
    is_sqlite = DATABASE_URL.startswith("sqlite")
    existing_ghl_ids = fetch_existing_xrefs(conn)
    existing_phones = fetch_existing_phones(conn)
    logger.info("Existing xref rows: %d (by ghl_id), %d (by phone)", len(existing_ghl_ids), len(existing_phones))

    # 3. Fetch all GHL contacts
    logger.info("Step 2: Fetching all GHL contacts...")
    ghl_contacts = await fetch_all_ghl_contacts()
    logger.info("Total GHL contacts fetched: %d", len(ghl_contacts))

    # 4. Match GHL contacts to Notion pages via dict lookup (no API calls)
    logger.info("Step 3: Matching contacts to Notion pages (dict lookups, no API calls)...")
    matched = 0
    skipped_existing = 0
    skipped_no_phone = 0
    not_found = 0
    errors = 0

    # CSV output
    csv_rows: List[Tuple[str, str, str, str]] = []

    for contact in ghl_contacts:
        contact_id = contact.get("id", "")
        if not contact_id:
            continue

        # Skip if already in xref
        if contact_id in existing_ghl_ids:
            skipped_existing += 1
            continue

        # Bug 3 fix: Try ALL phone fields on the GHL contact for matching
        phones_to_try = []

        # Primary phone
        raw_phone = contact.get("phone", "")
        if raw_phone:
            phone_e164 = normalize_phone(raw_phone)
            if phone_e164:
                phones_to_try.append(phone_e164)

        # Additional phones (GHL stores these as a list)
        additional = contact.get("additionalPhones", []) or []
        for ap in additional:
            ap_phone = ap.get("phoneNumber", "") or ap.get("phone", "")
            if ap_phone:
                ap_e164 = normalize_phone(ap_phone)
                if ap_e164 and ap_e164 not in phones_to_try:
                    phones_to_try.append(ap_e164)

        if not phones_to_try:
            skipped_no_phone += 1
            continue

        # Try each phone for a match
        notion_page_id = None
        matched_phone = None
        for phone_e164 in phones_to_try:
            if phone_e164 in existing_phones:
                continue
            notion_page_id = notion_phone_map.get(phone_e164)
            if notion_page_id:
                matched_phone = phone_e164
                break

        if not notion_page_id:
            not_found += 1
            continue

        phone_e164 = matched_phone

        first_name = contact.get("firstName", "")
        last_name = contact.get("lastName", "")
        name = f"{first_name} {last_name}".strip()

        if dry_run:
            if matched < 10:  # Only log first 10 matches to avoid spam
                logger.info(
                    "[DRY RUN] Would insert: ghl=%s notion=%s phone=%s name=%s",
                    contact_id, notion_page_id, phone_e164, name,
                )
        else:
            try:
                if is_sqlite:
                    insert_xref_sqlite(conn, contact_id, notion_page_id, phone_e164, first_name, last_name)
                else:
                    insert_xref(conn, contact_id, notion_page_id, phone_e164, first_name, last_name)
            except Exception as exc:
                logger.warning("Insert failed for %s: %s", contact_id, exc)
                errors += 1
                continue

        csv_rows.append((contact_id, notion_page_id, phone_e164, name))
        matched += 1
        existing_ghl_ids.add(contact_id)
        existing_phones.add(phone_e164)

    if not dry_run:
        conn.commit()

    conn.close()

    # Write CSV if requested
    if output_path and csv_rows:
        with open(output_path, "w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(["ghl_contact_id", "notion_page_id", "phone", "name"])
            writer.writerows(csv_rows)
        logger.info("CSV written to %s (%d rows)", output_path, len(csv_rows))

    elapsed = time.time() - start_time
    prefix = "DRY RUN COMPLETE" if dry_run else "BACKFILL COMPLETE"
    summary = (
        f"=== {prefix} === "
        f"matched={matched} skipped={skipped_existing} "
        f"no_phone={skipped_no_phone} not_found={not_found} "
        f"errors={errors} total_ghl={len(ghl_contacts)} "
        f"notion_phones={len(notion_phone_map)} "
        f"elapsed={elapsed:.1f}s"
    )
    logger.info(summary)
    print(f"\n{summary}\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Backfill lead_xref by matching GHL contacts to Notion pages")
    parser.add_argument("--dry-run", action="store_true", help="Preview without inserting")
    parser.add_argument("--output", type=str, default=None, help="Path to save matched pairs CSV")
    args = parser.parse_args()

    asyncio.run(main(dry_run=args.dry_run, output_path=args.output))
