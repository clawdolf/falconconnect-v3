#!/usr/bin/env python3
"""
Robust GHL ID backfill with proper error handling, retries, and progress.
"""
import os, sys, asyncio, re, time, httpx
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / ".env")

GHL_API_KEY    = os.environ["GHL_API_KEY"]
GHL_LOC        = os.environ["GHL_LOCATION_ID"]
NOTION_TOKEN   = os.environ["NOTION_TOKEN"]
NOTION_DB_ID   = "184d58e63823800f9b13f06aaa14e0e6"

GHL_HEADERS    = {"Authorization": f"Bearer {GHL_API_KEY}", "Version": "2021-07-28"}
NOTION_HEADERS = {
    "Authorization": f"Bearer {NOTION_TOKEN}",
    "Notion-Version": "2022-06-28",
    "Content-Type": "application/json",
}

def norm_phone(p):
    if not p: return None
    d = re.sub(r'\D', '', str(p))
    if len(d) == 10: d = '1' + d
    if len(d) == 11 and d[0] == '1': return '+' + d
    return None

def norm_name(first, last):
    f = (first or "").lower().strip()
    l = (last or "").lower().strip()
    return f"{f}|{l}" if (f or l) else None

# ── Step 1: Fetch all GHL contacts with retries ──────────────────────────────
async def fetch_ghl(client):
    by_phone, by_name = {}, {}
    url = "https://services.leadconnectorhq.com/contacts/"
    params = {"locationId": GHL_LOC, "limit": 100}
    total = 0
    page_num = 0

    while url:
        page_num += 1
        retry = 0
        while retry < 3:
            try:
                resp = await client.get(url, params=params if params else None, headers=GHL_HEADERS, timeout=30)
                if resp.status_code == 429:
                    print(f"    Rate limit on page {page_num}, sleeping 2s...")
                    await asyncio.sleep(2)
                    continue
                resp.raise_for_status()
                break
            except Exception as e:
                retry += 1
                if retry < 3:
                    await asyncio.sleep(1)
                else:
                    print(f"  ERROR: Page {page_num} failed after 3 retries: {e}")
                    return by_phone, by_name

        data = resp.json()
        contacts = data.get("contacts", [])

        for c in contacts:
            cid = c["id"]
            # All phone variants
            raw_phones = [c.get("phone"), c.get("phone2"), c.get("phone3")]
            for cf in c.get("customFields", []):
                v = cf.get("value")
                if isinstance(v, str): raw_phones.append(v)
            for ph in raw_phones:
                n = norm_phone(ph)
                if n and n not in by_phone:
                    by_phone[n] = cid
            # Name fallback
            nk = norm_name(c.get("firstName"), c.get("lastName"))
            if nk and nk not in by_name:
                by_name[nk] = cid

        total += len(contacts)
        if page_num % 10 == 0:
            sys.stdout.write(f"\r  GHL: page {page_num} ({total} total contacts)..."); sys.stdout.flush()

        meta = data.get("meta", {})
        next_url = meta.get("nextPageUrl")
        if next_url and len(contacts) == 100:
            url = next_url
            params = None
        else:
            url = None

    print(f"\n  GHL done: {total} contacts | {len(by_phone)} phone keys | {len(by_name)} name keys")
    return by_phone, by_name

# ── Step 2: Fetch Notion pages missing GHL ID ─────────────────────────────────
async def fetch_notion_missing(client):
    pages = []
    total_seen = 0
    cursor = None

    while True:
        payload = {"page_size": 100}
        if cursor: payload["start_cursor"] = cursor
        
        retry = 0
        while retry < 3:
            try:
                resp = await client.post(
                    f"https://api.notion.com/v1/databases/{NOTION_DB_ID}/query",
                    json=payload, headers=NOTION_HEADERS, timeout=30
                )
                if resp.status_code == 429:
                    await asyncio.sleep(1)
                    continue
                resp.raise_for_status()
                break
            except Exception as e:
                retry += 1
                if retry < 3:
                    await asyncio.sleep(1)
                else:
                    print(f"  ERROR: Notion query failed after 3 retries: {e}")
                    return pages

        data = resp.json()

        for p in data.get("results", []):
            total_seen += 1
            props = p.get("properties", {})
            ghl_field = props.get("GHL ID", {}).get("rich_text", [])
            if ghl_field and ghl_field[0].get("plain_text","").strip():
                continue  # Already linked

            phone = props.get("Mobile Phone", {}).get("phone_number","") or ""
            name_parts = props.get("Name", {}).get("title", [])
            name_raw = name_parts[0].get("plain_text","").strip() if name_parts else ""
            parts = name_raw.split()
            fn = parts[0].lower() if parts else ""
            ln = parts[-1].lower() if len(parts) > 1 else ""

            pages.append({
                "notion_id": p["id"],
                "phone": norm_phone(phone),
                "name_key": norm_name(fn, ln),
            })

        if total_seen % 500 == 0:
            sys.stdout.write(f"\r  Notion: scanned {total_seen}..."); sys.stdout.flush()
        if not data.get("has_more"): break
        cursor = data.get("next_cursor")

    print(f"\n  Notion done: {total_seen} total | {len(pages)} missing GHL ID")
    return pages

# ── Step 3: Write GHL IDs concurrently with retries ─────────────────────────
async def backfill(client, pages, by_phone, by_name):
    written = 0
    unmatched = 0
    errors = 0
    sem = asyncio.Semaphore(10)

    async def write_one(page):
        nonlocal written, unmatched, errors
        ghl_id = None
        if page["phone"]:
            ghl_id = by_phone.get(page["phone"])
        if not ghl_id and page["name_key"]:
            ghl_id = by_name.get(page["name_key"])
        if not ghl_id:
            unmatched += 1
            return

        payload = {"properties": {"GHL ID": {"rich_text": [{"text": {"content": ghl_id}}]}}}
        
        async with sem:
            retry = 0
            while retry < 3:
                try:
                    r = await client.patch(
                        f"https://api.notion.com/v1/pages/{page['notion_id']}",
                        json=payload, headers=NOTION_HEADERS, timeout=15
                    )
                    if r.status_code == 200:
                        written += 1
                        return
                    elif r.status_code == 429:
                        await asyncio.sleep(1)
                        retry += 1
                    else:
                        errors += 1
                        return
                except Exception as e:
                    retry += 1
                    if retry >= 3:
                        errors += 1
                    else:
                        await asyncio.sleep(0.5)

    # Batch in chunks
    chunk_size = 100
    t0 = time.time()
    for i in range(0, len(pages), chunk_size):
        chunk = pages[i:i+chunk_size]
        await asyncio.gather(*[write_one(p) for p in chunk], return_exceptions=True)
        done = min(i + chunk_size, len(pages))
        elapsed = time.time() - t0
        rate = written / elapsed if elapsed > 0 else 0
        pct = round(100 * done / len(pages), 0)
        print(f"  [{done}/{len(pages)} {pct}%] written={written} unmatched={unmatched} errors={errors} ({rate:.1f}/s)")

    return written, unmatched, errors

# ── Main ──────────────────────────────────────────────────────────────────────
async def main():
    print("=== GHL ID Backfill (Robust) ===")
    t0 = time.time()

    async with httpx.AsyncClient(timeout=120, limits=httpx.Limits(max_connections=30)) as client:
        print("Step 1: Fetching all GHL contacts...")
        by_phone, by_name = await fetch_ghl(client)

        print("Step 2: Fetching Notion pages missing GHL ID...")
        pages = await fetch_notion_missing(client)

        if not pages:
            print("✓ All Notion records already have GHL ID.")
            return

        print(f"Step 3: Writing {len(pages)} GHL IDs to Notion...")
        written, unmatched, errors = await backfill(client, pages, by_phone, by_name)

    elapsed = time.time() - t0
    print(f"\n=== COMPLETE ({elapsed:.0f}s) ===")
    print(f"Written:   {written}")
    print(f"Unmatched: {unmatched}  (no phone/name match in GHL)")
    print(f"Errors:    {errors}")
    
    total_linked = 4320 + written
    pct = round(100 * total_linked / 6442, 1)
    print(f"\nTotal GHL IDs in Notion: {total_linked} / 6442 ({pct}%)")

if __name__ == "__main__":
    asyncio.run(main())
