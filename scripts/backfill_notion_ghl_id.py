#!/usr/bin/env python3
"""Write GHL contact IDs directly into the Notion 'GHL ID' field.

Matches GHL contacts → Notion pages by phone (E.164 normalized).
In dry-run mode: prints a preview report with no Notion writes.
In live mode: writes GHL contact ID into the 'GHL ID' rich_text field on each matched page.

Usage:
    python3 scripts/backfill_notion_ghl_id.py --dry-run                # preview only
    python3 scripts/backfill_notion_ghl_id.py --dry-run --output /tmp/preview.csv
    python3 scripts/backfill_notion_ghl_id.py --output /tmp/results.csv  # live run + CSV

Reads GHL_API_KEY, GHL_LOCATION_ID, NOTION_TOKEN, NOTION_LEADS_DB_ID from .env
"""

import argparse
import asyncio
import csv
import logging
import os
import re
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import httpx
from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(PROJECT_ROOT / ".env")

GHL_API_KEY = os.environ["GHL_API_KEY"]
GHL_LOCATION_ID = os.environ["GHL_LOCATION_ID"]
NOTION_TOKEN = os.environ["NOTION_TOKEN"]
NOTION_LEADS_DB_ID = os.environ.get("NOTION_LEADS_DB_ID", "184d58e63823800f9b13f06aaa14e0e6")

GHL_BASE = "https://services.leadconnectorhq.com"
GHL_API_VERSION = "2021-07-28"
NOTION_BASE = "https://api.notion.com/v1"
NOTION_VERSION = "2022-06-28"
NOTION_FIELD = "GHL ID"  # The Notion property name to write into

# GHL custom field IDs for additional phone fields
GHL_CF_HPHONE = "za04O6KtX9Sg3yn8csZi"       # contact.hphone (home phone)
GHL_CF_SPOUSE_CELL = "1MKVvQCPMsAaDb8aL5vi"  # contact.spouse_cell

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("backfill_notion_ghl_id")


# ── Helpers ──────────────────────────────────────────────────────────────────

def normalize_phone(raw: str) -> str:
    """Normalize to E.164 (+1XXXXXXXXXX). Returns '' if invalid."""
    if not raw:
        return ""
    digits = re.sub(r"[^\d]", "", raw.strip())
    if len(digits) == 11 and digits.startswith("1"):
        return f"+{digits}"
    if len(digits) == 10:
        return f"+1{digits}"
    if len(digits) > 10:
        return f"+{digits}"
    return ""


def ghl_headers() -> Dict[str, str]:
    return {
        "Authorization": f"Bearer {GHL_API_KEY}",
        "Version": GHL_API_VERSION,
        "Content-Type": "application/json",
        "Accept": "application/json",
    }


def notion_headers() -> Dict[str, str]:
    return {
        "Authorization": f"Bearer {NOTION_TOKEN}",
        "Notion-Version": NOTION_VERSION,
        "Content-Type": "application/json",
    }


# ── GHL ───────────────────────────────────────────────────────────────────────

async def fetch_all_ghl_contacts() -> List[Dict[str, Any]]:
    """Paginate through ALL GHL contacts."""
    contacts: List[Dict[str, Any]] = []
    async with httpx.AsyncClient(timeout=60) as client:
        params = {"locationId": GHL_LOCATION_ID, "limit": 100}
        resp = await client.get(f"{GHL_BASE}/contacts/", headers=ghl_headers(), params=params)
        resp.raise_for_status()
        data = resp.json()
        contacts.extend(data.get("contacts", []))
        next_url = data.get("meta", {}).get("nextPageUrl")
        page = 2
        while next_url:
            resp = await client.get(next_url, headers=ghl_headers())
            resp.raise_for_status()
            data = resp.json()
            batch = data.get("contacts", [])
            contacts.extend(batch)
            next_url = data.get("meta", {}).get("nextPageUrl")
            logger.info("GHL page %d: %d contacts (total: %d)", page, len(batch), len(contacts))
            page += 1
            if not batch:
                break
    logger.info("GHL fetch complete: %d contacts", len(contacts))
    return contacts


# ── Notion ────────────────────────────────────────────────────────────────────

async def fetch_all_notion_pages() -> Dict[str, Dict[str, Any]]:
    """Fetch ALL Notion pages. Returns {normalized_phone: {page_id, name, existing_ghl_id}}."""
    phone_map: Dict[str, Dict[str, Any]] = {}
    has_more = True
    start_cursor: Optional[str] = None
    total = 0
    api_calls = 0

    async with httpx.AsyncClient(timeout=60) as client:
        while has_more:
            api_calls += 1
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
            total += len(results)

            for page in results:
                page_id = page["id"]
                props = page.get("properties", {})

                # Extract name
                name_items = props.get("Name", {}).get("title", [])
                name = "".join(i.get("plain_text", "") for i in name_items)

                # Extract existing GHL ID (if already set)
                ghl_id_texts = props.get(NOTION_FIELD, {}).get("rich_text", [])
                existing_ghl_id = "".join(i.get("plain_text", "") for i in ghl_id_texts).strip()

                # Check all phone fields
                phone_fields = ["Mobile Phone", "Home Phone", "Spouse Phone"]
                for field_name in phone_fields:
                    prop = props.get(field_name, {})
                    raw = ""
                    if prop.get("type") == "phone_number":
                        raw = prop.get("phone_number") or ""
                    elif prop.get("type") == "rich_text":
                        raw = "".join(t.get("plain_text", "") for t in prop.get("rich_text", []))

                    if raw:
                        normalized = normalize_phone(str(raw))
                        if normalized and normalized not in phone_map:
                            phone_map[normalized] = {
                                "page_id": page_id,
                                "name": name,
                                "existing_ghl_id": existing_ghl_id,
                            }

            has_more = data.get("has_more", False)
            start_cursor = data.get("next_cursor")

            if api_calls % 10 == 0 or not has_more:
                logger.info("Notion: %d API calls, %d pages, %d phone entries", api_calls, total, len(phone_map))

            await asyncio.sleep(0.35)  # Notion rate limit: ~3 req/s

    logger.info("Notion fetch complete: %d pages, %d phone entries", total, len(phone_map))
    return phone_map


async def write_ghl_id_to_notion(page_id: str, ghl_contact_id: str) -> bool:
    """Write the GHL contact ID into the 'GHL ID' rich_text field on a Notion page."""
    payload = {
        "properties": {
            NOTION_FIELD: {
                "rich_text": [
                    {"type": "text", "text": {"content": ghl_contact_id}}
                ]
            }
        }
    }
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.patch(
            f"{NOTION_BASE}/pages/{page_id}",
            headers=notion_headers(),
            json=payload,
        )
        if resp.status_code == 200:
            return True
        else:
            logger.warning("Notion PATCH failed for page %s: %s %s", page_id, resp.status_code, resp.text[:200])
            return False


# ── Main ──────────────────────────────────────────────────────────────────────

async def main(dry_run: bool = False, output_path: Optional[str] = None):
    start_time = time.time()
    mode = "DRY RUN" if dry_run else "LIVE"
    logger.info("=== Backfill Notion GHL ID — %s mode ===", mode)

    # 1. Load all Notion pages
    logger.info("Step 1: Loading all Notion pages...")
    notion_map = await fetch_all_notion_pages()

    # 2. Load all GHL contacts
    logger.info("Step 2: Loading all GHL contacts...")
    ghl_contacts = await fetch_all_ghl_contacts()

    # 3. Match and write
    logger.info("Step 3: Matching and %s...", "previewing" if dry_run else "writing to Notion")

    matched = 0
    already_set = 0
    no_phone = 0
    not_found = 0
    write_errors = 0
    csv_rows: List[Tuple[str, str, str, str]] = []  # (ghl_id, notion_page_id, phone, name)

    for contact in ghl_contacts:
        ghl_id = contact.get("id", "")
        if not ghl_id:
            continue

        first = contact.get("firstName", "")
        last = contact.get("lastName", "")
        name = f"{first} {last}".strip()

        # Collect all phones from GHL contact
        phones_to_try = []
        raw = contact.get("phone", "")
        if raw:
            norm = normalize_phone(raw)
            if norm:
                phones_to_try.append(norm)

        # Pull home phone + spouse cell from customFields
        for cf in (contact.get("customFields") or []):
            cf_id = cf.get("id", "")
            if cf_id in (GHL_CF_HPHONE, GHL_CF_SPOUSE_CELL):
                cf_val = cf.get("value", "") or ""
                norm = normalize_phone(str(cf_val))
                if norm and norm not in phones_to_try:
                    phones_to_try.append(norm)

        if not phones_to_try:
            no_phone += 1
            continue

        # Find matching Notion page
        notion_entry = None
        matched_phone = None
        for phone in phones_to_try:
            entry = notion_map.get(phone)
            if entry:
                notion_entry = entry
                matched_phone = phone
                break

        if not notion_entry:
            not_found += 1
            continue

        page_id = notion_entry["page_id"]
        existing = notion_entry["existing_ghl_id"]

        # Skip if already set to this ID
        if existing == ghl_id:
            already_set += 1
            continue

        if dry_run:
            status = "WOULD OVERWRITE" if existing else "WOULD WRITE"
            if matched < 20:
                logger.info("[DRY RUN] %s: name=%s phone=%s ghl_id=%s notion_page=%s existing=%s",
                            status, name, matched_phone, ghl_id, page_id, existing or "(none)")
        else:
            ok = await write_ghl_id_to_notion(page_id, ghl_id)
            if not ok:
                write_errors += 1
                continue
            await asyncio.sleep(0.35)  # Notion rate limit

        csv_rows.append((ghl_id, page_id, matched_phone or "", name))
        matched += 1

    # Write CSV
    if output_path and csv_rows:
        with open(output_path, "w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(["ghl_contact_id", "notion_page_id", "phone", "name"])
            writer.writerows(csv_rows)
        logger.info("CSV written: %s (%d rows)", output_path, len(csv_rows))

    elapsed = time.time() - start_time
    print(f"""
=== {'DRY RUN' if dry_run else 'LIVE RUN'} COMPLETE ===
  GHL contacts fetched : {len(ghl_contacts)}
  Notion pages indexed : {len(notion_map)} (by phone)
  Matched              : {matched}
  Already set (skip)   : {already_set}
  No phone (GHL)       : {no_phone}
  Not found in Notion  : {not_found}
  Write errors         : {write_errors}
  Elapsed              : {elapsed:.1f}s
  {'Output CSV          : ' + output_path if output_path else ''}
""")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Backfill GHL contact IDs into Notion 'GHL ID' field")
    parser.add_argument("--dry-run", action="store_true", help="Preview without writing to Notion")
    parser.add_argument("--output", type=str, default=None, help="Path for CSV output")
    args = parser.parse_args()
    asyncio.run(main(dry_run=args.dry_run, output_path=args.output))
