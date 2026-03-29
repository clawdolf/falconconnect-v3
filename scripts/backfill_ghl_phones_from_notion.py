#!/usr/bin/env python3
"""Match GHL contacts (no phone) to Notion pages by name, then upsert phone to GHL.

Logic:
  1. Load all GHL contacts with no phone
  2. Load all Notion pages, build name → {phones, page_id} map
  3. Match by normalized name (lowercase, stripped)
  4. Exact matches with unique name → auto-write to GHL
  5. Exact matches with duplicate name → CSV for review
  6. Fuzzy matches (difflib ratio >= 0.85) → CSV for review
  7. No match → CSV for review

Usage:
    python3 scripts/backfill_ghl_phones_from_notion.py --dry-run
    python3 scripts/backfill_ghl_phones_from_notion.py --output /tmp/review.csv
    python3 scripts/backfill_ghl_phones_from_notion.py  # live run
"""

import argparse
import asyncio
import csv
import difflib
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
NOTION_LEADS_DB_ID = os.environ.get("NOTION_LEADS_DB_ID", "REPLACE_WITH_YOUR_NOTION_DATABASE_ID")

GHL_BASE = "https://services.leadconnectorhq.com"
GHL_API_VERSION = "2021-07-28"
NOTION_BASE = "https://api.notion.com/v1"
NOTION_VERSION = "2022-06-28"

GHL_CF_HPHONE = "za04O6KtX9Sg3yn8csZi"
GHL_CF_SPOUSE_CELL = "1MKVvQCPMsAaDb8aL5vi"

FUZZY_THRESHOLD = 0.85

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("backfill_ghl_phones")


def normalize_phone(raw: str) -> str:
    if not raw: return ""
    digits = re.sub(r"[^\d]", "", str(raw).strip())
    if len(digits) == 11 and digits.startswith("1"): return f"+{digits}"
    if len(digits) == 10: return f"+1{digits}"
    if len(digits) > 10: return f"+{digits}"
    return ""


def normalize_name(raw: str) -> str:
    """Lowercase, strip punctuation, collapse whitespace."""
    if not raw: return ""
    s = raw.lower().strip()
    s = re.sub(r"[^\w\s]", "", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


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


async def fetch_all_ghl_contacts() -> List[Dict[str, Any]]:
    contacts = []
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
            page += 1
            if not batch:
                break
    logger.info("GHL: %d total contacts", len(contacts))
    return contacts


async def fetch_all_notion_pages() -> Dict[str, List[Dict[str, Any]]]:
    """Returns {normalized_name: [list of {page_id, mobile, home, spouse, raw_name}]}"""
    name_map: Dict[str, List[Dict[str, Any]]] = {}
    has_more = True
    start_cursor = None
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

                # Name
                name_items = props.get("Name", {}).get("title", [])
                raw_name = "".join(i.get("plain_text", "") for i in name_items).strip()
                norm_name = normalize_name(raw_name)
                if not norm_name:
                    continue

                # Phones
                def get_phone(field):
                    prop = props.get(field, {})
                    raw = prop.get("phone_number", "") or ""
                    if not raw and prop.get("type") == "rich_text":
                        raw = "".join(t.get("plain_text", "") for t in prop.get("rich_text", []))
                    return normalize_phone(str(raw))

                mobile = get_phone("Mobile Phone")
                home = get_phone("Home Phone")
                spouse = get_phone("Spouse Phone")

                entry = {
                    "page_id": page_id,
                    "raw_name": raw_name,
                    "mobile": mobile,
                    "home": home,
                    "spouse": spouse,
                }

                if norm_name not in name_map:
                    name_map[norm_name] = []
                name_map[norm_name].append(entry)

            has_more = data.get("has_more", False)
            start_cursor = data.get("next_cursor")
            if api_calls % 10 == 0 or not has_more:
                logger.info("Notion: %d API calls, %d pages", api_calls, total)
            await asyncio.sleep(0.35)

    logger.info("Notion: %d pages, %d unique names", total, len(name_map))
    return name_map


async def update_ghl_phone(contact_id: str, mobile: str, home: str, spouse: str) -> bool:
    """Write phone fields to GHL contact."""
    payload: Dict[str, Any] = {}
    if mobile:
        payload["phone"] = mobile
    custom_fields = []
    if home:
        custom_fields.append({"id": GHL_CF_HPHONE, "key": "contact.hphone", "field_value": home})
    if spouse:
        custom_fields.append({"id": GHL_CF_SPOUSE_CELL, "key": "contact.spouse_cell", "field_value": spouse})
    if custom_fields:
        payload["customFields"] = custom_fields

    if not payload:
        return False

    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.put(
            f"{GHL_BASE}/contacts/{contact_id}",
            headers=ghl_headers(),
            json=payload,
        )
        if resp.status_code in (200, 201):
            return True
        logger.warning("GHL PUT failed for %s: %s %s", contact_id, resp.status_code, resp.text[:200])
        return False


async def main(dry_run: bool = False, output_path: Optional[str] = None):
    start_time = time.time()
    mode = "DRY RUN" if dry_run else "LIVE"
    logger.info("=== Backfill GHL phones from Notion — %s ===", mode)

    notion_map = await fetch_all_notion_pages()
    notion_names = list(notion_map.keys())

    all_ghl = await fetch_all_ghl_contacts()

    # Filter to contacts with no phone at all
    no_phone = []
    for c in all_ghl:
        primary = normalize_phone(c.get("phone", ""))
        hphone = ""
        spouse = ""
        for cf in (c.get("customFields") or []):
            if cf.get("id") == GHL_CF_HPHONE:
                hphone = normalize_phone(str(cf.get("value", "") or ""))
            elif cf.get("id") == GHL_CF_SPOUSE_CELL:
                spouse = normalize_phone(str(cf.get("value", "") or ""))
        if not primary and not hphone and not spouse:
            no_phone.append(c)

    logger.info("GHL contacts with no phone: %d", len(no_phone))

    auto_write = 0
    write_errors = 0
    review_rows: List[List[str]] = []

    output_file = output_path or "/tmp/ghl_phone_backfill_review.csv"

    for c in no_phone:
        ghl_id = c.get("id", "")
        first = c.get("firstName", "") or ""
        last = c.get("lastName", "") or ""
        raw_name = f"{first} {last}".strip()
        norm = normalize_name(raw_name)
        tags = "|".join(c.get("tags", []))

        if not norm or norm in ("none none", ""):
            review_rows.append([ghl_id, raw_name, "", "", "", "", tags, "no_name"])
            continue

        # Exact match
        if norm in notion_map:
            entries = notion_map[norm]
            if len(entries) == 1:
                entry = entries[0]
            else:
                # Duplicate name — use first entry that has a phone
                entry = next((e for e in entries if e["mobile"] or e["home"] or e["spouse"]), entries[0])

            mobile = entry["mobile"]
            home = entry["home"]
            spouse = entry["spouse"]

            # Sanity-check phone lengths (skip malformed like dana matthews)
            def valid_phone(p):
                if not p: return ""
                digits = re.sub(r"[^\d]", "", p)
                return p if 10 <= len(digits) <= 12 else ""

            mobile = valid_phone(mobile)
            home = valid_phone(home)
            spouse = valid_phone(spouse)
            best_phone = mobile or home or spouse

            if not best_phone:
                review_rows.append([ghl_id, raw_name, entry["mobile"], entry["home"], entry["spouse"], entry["raw_name"], tags, "exact_match_no_notion_phone"])
            else:
                if dry_run:
                    logger.info("[DRY RUN] AUTO-WRITE: %s → mobile=%s home=%s spouse=%s", raw_name, mobile, home, spouse)
                else:
                    ok = await update_ghl_phone(ghl_id, mobile, home, spouse)
                    if not ok:
                        write_errors += 1
                        review_rows.append([ghl_id, raw_name, mobile, home, spouse, entry["raw_name"], tags, "write_error"])
                        continue
                    await asyncio.sleep(0.2)

                auto_write += 1

        else:
            # Fuzzy match
            close = difflib.get_close_matches(norm, notion_names, n=1, cutoff=FUZZY_THRESHOLD)
            if close:
                match_name = close[0]
                entries = notion_map[match_name]
                entry = entries[0]
                ratio = difflib.SequenceMatcher(None, norm, match_name).ratio()
                review_rows.append([
                    ghl_id, raw_name,
                    entry["mobile"], entry["home"], entry["spouse"],
                    entry["raw_name"], tags,
                    f"fuzzy_{ratio:.2f}",
                ])
            else:
                review_rows.append([ghl_id, raw_name, "", "", "", "", tags, "no_match"])

    # Write review CSV
    with open(output_file, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["ghl_contact_id", "ghl_name", "notion_mobile", "notion_home", "notion_spouse", "notion_name_or_note", "ghl_tags", "status"])
        writer.writerows(review_rows)

    elapsed = time.time() - start_time
    print(f"""
=== {'DRY RUN' if dry_run else 'LIVE RUN'} COMPLETE ===
  GHL no-phone contacts : {len(no_phone)}
  Auto-written          : {auto_write}
  Write errors          : {write_errors}
  Flagged for review    : {len(review_rows)}
  Review CSV            : {output_file}
  Elapsed               : {elapsed:.1f}s
""")

    # Count review breakdown
    from collections import Counter
    statuses = Counter(r[-1] for r in review_rows)
    for k, v in statuses.most_common():
        print(f"    {k}: {v}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--output", type=str, default=None)
    args = parser.parse_args()
    asyncio.run(main(dry_run=args.dry_run, output_path=args.output))
