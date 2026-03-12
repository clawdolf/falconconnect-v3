"""Notion API client — upsert leads, poll for changes, query upcoming events.

Property names match the actual Notion Leads DB schema (verified 2026-03-03):
  Name (title), Mobile Phone (phone_number), Email (email),
  Lead Status (status), Opportunity Stage (status), Appointment Date (date),
  Follow-Up Date (date), LAge (select), Age (number), Lead Source (select),
  State (select), Aggregate Comments (rich_text), Address (rich_text),
  City (rich_text), ZIP Code (rich_text), Mortgage Sale Date (date),
  Lead Type (select), Gender (rich_text), DOB (date),
  + custom "GHL Contact ID" rich_text (created if missing).
"""

import asyncio
import logging
import re
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

import httpx

from config import get_settings

logger = logging.getLogger("falconconnect.notion")

NOTION_BASE = "https://api.notion.com/v1"
NOTION_VERSION = "2022-06-28"

# Map LAge months to the select options in the Notion DB
# Uses exclusive upper bound (low <= months < high) to avoid boundary overlap
LAGE_BRACKETS = [
    (0,  7,    "3+ Month"),   # 0–6 months
    (7,  13,   "7-12M"),      # 7–12 months
    (13, 25,   "13–24M"),
    (25, 37,   "25–36M"),
    (37, 49,   "37–48M"),
    (49, 61,   "49–60M"),
    (61, 9999, "60+M"),
]


def _lage_select(months: Optional[int]) -> Optional[str]:
    """Convert lage months integer to the closest Notion select option."""
    if months is None:
        return None
    for low, high, label in LAGE_BRACKETS:
        if low <= months < high:
            return label
    return "60+M"


def _headers() -> Dict[str, str]:
    settings = get_settings()
    return {
        "Authorization": f"Bearer {settings.notion_token}",
        "Notion-Version": NOTION_VERSION,
        "Content-Type": "application/json",
    }


async def _notion_post_with_retry(client: httpx.AsyncClient, url: str, **kwargs) -> httpx.Response:
    """POST to Notion with automatic 429 retry (up to 3 attempts, 1s backoff)."""
    for attempt in range(3):
        resp = await client.post(url, **kwargs)
        if resp.status_code == 429:
            retry_after = int(resp.headers.get("Retry-After", "1"))
            logger.warning("Notion 429 rate limit — waiting %ss (attempt %d)", retry_after, attempt + 1)
            await asyncio.sleep(retry_after)
            continue
        return resp
    return resp  # return last response after 3 attempts


async def upsert_lead(
    lead: Dict[str, Any],
    ghl_contact_id: str,
    age: Optional[int] = None,
    lage_months: Optional[int] = None,
) -> str:
    """Create or update a lead page in the Notion leads database.

    Bug 7 fix: On update, reads existing Aggregate Comments first
    and merges/preserves them instead of overwriting.

    Searches for an existing page by phone; creates if not found.
    Returns the Notion page ID.
    """
    settings = get_settings()
    db_id = settings.notion_leads_db_id

    phone = lead.get("phone", "")

    # Check if lead already exists by phone
    existing = await _find_page_by_phone(db_id, phone)
    if existing:
        page_id = existing

        # Bug 7: Read existing Aggregate Comments before building properties
        existing_comments = await _read_aggregate_comments(page_id)
        props = _build_properties(
            lead, ghl_contact_id, age, lage_months,
            existing_comments=existing_comments,
            is_create=False,  # Don't overwrite Call In Date on update
        )
        await update_page(page_id, props)
        logger.info("Notion updated existing page %s (dupe: %s)", page_id, lead.get("phone", ""))
        return page_id

    # Create new page
    properties = _build_properties(lead, ghl_contact_id, age, lage_months)
    payload = {
        "parent": {"database_id": db_id},
        "properties": properties,
    }

    async with httpx.AsyncClient(timeout=30) as client:
        resp = await _notion_post_with_retry(
            client,
            f"{NOTION_BASE}/pages",
            headers=_headers(),
            json=payload,
        )
        resp.raise_for_status()
        page_id = resp.json()["id"]
        logger.info("Notion created new page %s", page_id)
        return page_id


async def _read_aggregate_comments(page_id: str) -> str:
    """Bug 7 helper: Read existing Aggregate Comments from a Notion page."""
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(
                f"{NOTION_BASE}/pages/{page_id}",
                headers=_headers(),
            )
            resp.raise_for_status()
            props = resp.json().get("properties", {})
            comments_items = props.get("Aggregate Comments", {}).get("rich_text", [])
            return "".join(item.get("plain_text", "") for item in comments_items) if comments_items else ""
    except Exception as e:
        logger.warning("Failed to read Aggregate Comments for %s: %s", page_id, e)
        return ""


async def _find_page_by_phone(database_id: str, phone: str) -> Optional[str]:
    """Search the leads database for a page matching the given phone number."""
    if not phone:
        return None

    payload = {
        "filter": {
            "property": "Mobile Phone",
            "phone_number": {"equals": phone},
        },
        "page_size": 1,
    }

    async with httpx.AsyncClient(timeout=30) as client:
        resp = await _notion_post_with_retry(
            client,
            f"{NOTION_BASE}/databases/{database_id}/query",
            headers=_headers(),
            json=payload,
        )
        resp.raise_for_status()
        results = resp.json().get("results", [])
        if results:
            return results[0]["id"]
    return None


def _parse_date_flexible(val) -> Optional[str]:
    """Parse a date value to YYYY-MM-DD string. Handles date objects, isoformat strings,
    and common vendor formats (M/D/YY, M/D/YYYY). Returns None if unparseable."""
    if not val:
        return None
    if hasattr(val, "isoformat"):
        return val.isoformat()[:10]
    s = str(val).strip()
    if not s:
        return None
    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%m/%d/%y", "%m-%d-%Y", "%m-%d-%y", "%Y/%m/%d"):
        try:
            return datetime.strptime(s, fmt).strftime("%Y-%m-%d")
        except ValueError:
            pass
    return None


def _build_properties(
    lead: Dict[str, Any],
    ghl_contact_id: str,
    age: Optional[int] = None,
    lage_months: Optional[int] = None,
    existing_comments: str = "",
    is_create: bool = True,
) -> Dict[str, Any]:
    """Build Notion page properties from a lead dict.

    Bug 7 fix: When existing_comments is provided (update path), preserves
    existing content and merges the GHL ID + notes instead of overwriting.

    Uses real Notion DB property names and types.
    """
    full_name = f"{lead.get('first_name', '')} {lead.get('last_name', '')}".strip()

    # Bug 7: Build Aggregate Comments with merge logic
    new_ghl_ref = f"GHL:{ghl_contact_id}" if ghl_contact_id else ""
    if existing_comments:
        # Check if GHL ID is already in existing comments
        if ghl_contact_id and f"GHL:{ghl_contact_id}" in existing_comments:
            # GHL ID already present — preserve existing comments entirely
            comment_text = existing_comments
        elif ghl_contact_id and "GHL:" in existing_comments:
            # Different GHL ID exists — update the ID portion but keep notes
            comment_text = re.sub(r"GHL:[^\s|]+", f"GHL:{ghl_contact_id}", existing_comments, count=1)
        elif ghl_contact_id:
            # No GHL ID yet — prepend it
            comment_text = f"GHL:{ghl_contact_id} | {existing_comments}"
        else:
            # No new GHL ID — preserve existing
            comment_text = existing_comments
    else:
        comment_text = new_ghl_ref

    props: Dict[str, Any] = {
        # title
        "Name": {
            "title": [{"text": {"content": full_name}}]
        },
        # phone_number
        "Mobile Phone": {"phone_number": lead.get("phone", "")},
        # rich_text — cross-reference ID (Bug 7: merged, not overwritten)
        "Aggregate Comments": {
            "rich_text": [{"text": {"content": comment_text[:2000]}}]
        },
    }

    # Email
    if lead.get("email"):
        props["Email"] = {"email": lead["email"]}

    # Lead Status (status type) — default to "No Contact" for new leads
    segment = lead.get("segment", "Never Worked")
    status_map = {
        "Never Worked": "No Contact",
        "Active Working": "Contacted",
        "Appointments": "Appointment Booked",
        "Client": "Appointment Booked",
        "Not Interested": "Not Interested/Lost",
        "DNC": "Invalid",
        "Follow Up": "Re Engaged",
    }
    status_name = status_map.get(segment, "No Contact")
    props["Lead Status"] = {"status": {"name": status_name}}

    # Address fields (rich_text)
    if lead.get("address"):
        props["Address"] = {"rich_text": [{"text": {"content": lead["address"]}}]}
    if lead.get("city"):
        props["City"] = {"rich_text": [{"text": {"content": lead["city"]}}]}
    if lead.get("county"):
        props["County"] = {"rich_text": [{"text": {"content": lead["county"]}}]}
    if lead.get("zip_code"):
        # Normalize ZIP: extract first 5 digits, left-pad with zeros if short (Maine etc.)
        _zip_digits = re.sub(r"\D", "", str(lead["zip_code"]))[:5]
        _zip_norm = _zip_digits.zfill(5) if 1 <= len(_zip_digits) <= 5 else _zip_digits
        if _zip_norm:
            props["ZIP Code"] = {"rich_text": [{"text": {"content": _zip_norm}}]}

    # State (select) — normalize full names to 2-letter codes (matches old import script)
    if lead.get("state"):
        _state_raw = str(lead["state"]).strip()
        _state_map = {
            "arizona": "AZ", "california": "CA", "pennsylvania": "PA", "maine": "ME",
            "new york": "NY", "texas": "TX", "florida": "FL", "ohio": "OH",
            "illinois": "IL", "georgia": "GA", "michigan": "MI", "washington": "WA",
            "oregon": "OR", "colorado": "CO", "nevada": "NV", "utah": "UT",
            "new mexico": "NM", "idaho": "ID", "montana": "MT", "wyoming": "WY",
            "north carolina": "NC", "south carolina": "SC", "alabama": "AL",
            "mississippi": "MS", "louisiana": "LA", "tennessee": "TN", "kentucky": "KY",
            "indiana": "IN", "iowa": "IA", "minnesota": "MN", "wisconsin": "WI",
            "missouri": "MO", "kansas": "KS", "oklahoma": "OK", "virginia": "VA",
            "west virginia": "WV", "maryland": "MD", "district of columbia": "DC",
            "dc": "DC", "delaware": "DE", "new jersey": "NJ", "connecticut": "CT",
            "rhode island": "RI", "massachusetts": "MA", "vermont": "VT",
            "new hampshire": "NH", "alaska": "AK", "hawaii": "HI", "arkansas": "AR",
            "nebraska": "NE", "south dakota": "SD", "north dakota": "ND",
        }
        state_norm = _state_map.get(_state_raw.lower(), _state_raw.upper()[:2])
        props["State"] = {"select": {"name": state_norm}}

    # Age (number)
    if age is not None:
        props["Age"] = {"number": age}

    # LAge (select — bracket label, not raw number)
    lage_label = _lage_select(lage_months)
    if lage_label:
        props["LAge"] = {"select": {"name": lage_label}}

    # Lead Type (select) — BUG 3 FIX: was never written to Notion
    if lead.get("lead_type"):
        props["Lead Type"] = {"select": {"name": lead["lead_type"]}}

    # Lead Source (select)
    lead_source = lead.get("lead_source") or lead.get("source")
    if lead_source:
        props["Lead Source"] = {"select": {"name": lead_source}}

    # Mortgage Sale Date (date) — normalize to YYYY-MM-DD (same as DOB/LPD)
    mail_date = lead.get("mail_date")
    if mail_date:
        mail_date_parsed = _parse_date_flexible(mail_date)
        if mail_date_parsed:
            props["Mortgage Sale Date"] = {"date": {"start": mail_date_parsed}}

    # BUG 4 FIX: Always write GHL ID first, append notes after.
    # Format: "GHL:{id} | {notes}" — never overwrite the GHL ID portion.
    notes = lead.get("notes", "")
    if notes:
        comment_text = f"GHL:{ghl_contact_id} | {notes}" if ghl_contact_id else notes
        props["Aggregate Comments"] = {
            "rich_text": [{"text": {"content": comment_text[:2000]}}]
        }
    # If no notes, the default "GHL:{id}" set above is preserved

    # ── Field-parity additions (match old Notion import script) ──

    # Tier (select)
    if lead.get("tier"):
        props["Tier"] = {"select": {"name": lead["tier"]}}

    # LPD — Lead Purchase Date (date) — normalize to YYYY-MM-DD
    if lead.get("lpd"):
        lpd_parsed = _parse_date_flexible(lead["lpd"])
        if lpd_parsed:
            props["LPD"] = {"date": {"start": lpd_parsed}}

    # Call In Date — set to today, but only on CREATE (not update)
    if is_create:
        props["Call In Date"] = {"date": {"start": datetime.now().strftime("%Y-%m-%d")}}

    # Best Time to Call (rich_text)
    if lead.get("best_time_to_call"):
        props["Best Time to Call"] = {
            "rich_text": [{"text": {"content": str(lead["best_time_to_call"])[:2000]}}]
        }

    # Gender (rich_text) — normalize to M/F like old import script
    if lead.get("gender"):
        _g = str(lead["gender"]).strip().lower()
        gender_norm = "M" if _g in {"m", "male", "man"} else "F" if _g in {"f", "female", "woman"} else str(lead["gender"]).strip()
        props["Gender"] = {
            "rich_text": [{"text": {"content": gender_norm}}]
        }

    # DOB (date) — normalize to YYYY-MM-DD (Notion rejects non-ISO dates)
    if lead.get("dob"):
        dob_parsed = _parse_date_flexible(lead["dob"])
        if dob_parsed:
            props["DOB"] = {"date": {"start": dob_parsed}}

    # Home Phone (phone_number) — skip if empty/None (Notion rejects null)
    if lead.get("home_phone"):
        props["Home Phone"] = {"phone_number": str(lead["home_phone"])}

    # Spouse Cell (phone_number) — skip if empty/None
    if lead.get("spouse_phone"):
        props["Spouse Cell"] = {"phone_number": str(lead["spouse_phone"])}

    # Lender (rich_text)
    if lead.get("lender"):
        props["Lender"] = {
            "rich_text": [{"text": {"content": str(lead["lender"])}}]
        }

    # Loan Amount (rich_text)
    if lead.get("loan_amount"):
        props["Loan Amount"] = {
            "rich_text": [{"text": {"content": str(lead["loan_amount"])}}]
        }

    # Checkbox fields
    if lead.get("tobacco") is not None:
        props["Tobacco?"] = {"checkbox": bool(lead["tobacco"])}
    if lead.get("medical") is not None:
        props["Medical Issues?"] = {"checkbox": bool(lead["medical"])}
    if lead.get("spanish") is not None:
        props["Spanish?"] = {"checkbox": bool(lead["spanish"])}

    return props


async def update_page(page_id: str, properties: Dict[str, Any]) -> None:
    """Update specific properties on a Notion page."""
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.patch(
            f"{NOTION_BASE}/pages/{page_id}",
            headers=_headers(),
            json={"properties": properties},
        )
        resp.raise_for_status()
        logger.info("Notion page %s updated", page_id)


# ---------------------------------------------------------------------------
# Calendar queries — split into appointments-only and follow-ups-only
# ---------------------------------------------------------------------------

async def get_upcoming_appointments(days: int = 90) -> List[Dict[str, Any]]:
    """Query Notion for leads with Appointment Date in the next N days.

    Bug 8 fix: Actually applies upper bound based on the `days` parameter.
    Returns pages tagged with _event_type="appointment".
    """
    settings = get_settings()
    today = datetime.now(timezone.utc).date()
    end_date = today + timedelta(days=days)

    payload = {
        "filter": {
            "and": [
                {
                    "property": "Appointment Date",
                    "date": {"on_or_after": today.isoformat()},
                },
                {
                    "property": "Appointment Date",
                    "date": {"on_or_before": end_date.isoformat()},
                },
            ]
        },
        "page_size": 100,
    }

    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(
            f"{NOTION_BASE}/databases/{settings.notion_leads_db_id}/query",
            headers=_headers(),
            json=payload,
        )
        resp.raise_for_status()
        pages = resp.json().get("results", [])

    return [{**p, "_event_type": "appointment"} for p in pages if _date_value(p.get("properties", {}).get("Appointment Date", {}))]


async def get_upcoming_followups(days: int = 90) -> List[Dict[str, Any]]:
    """Query Notion for leads with Follow-Up Date in the next N days.

    Returns pages tagged with _event_type="followup".
    """
    settings = get_settings()
    today = datetime.now(timezone.utc).date()

    payload = {
        "filter": {
            "property": "Follow Up Date",
            "date": {"on_or_after": today.isoformat()},
        },
        "page_size": 100,
    }

    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(
            f"{NOTION_BASE}/databases/{settings.notion_leads_db_id}/query",
            headers=_headers(),
            json=payload,
        )
        resp.raise_for_status()
        pages = resp.json().get("results", [])

    return [{**p, "_event_type": "followup"} for p in pages if _date_value(p.get("properties", {}).get("Follow Up Date", {}))]


async def get_upcoming_events(days: int = 90) -> List[Dict[str, Any]]:
    """Query both appointment and follow-up events (convenience wrapper)."""
    appts = await get_upcoming_appointments(days)
    fups = await get_upcoming_followups(days)
    return appts + fups


async def poll_recent_changes(minutes: int = 6) -> List[Dict[str, Any]]:
    """Poll the leads database for pages modified in the last N minutes.

    Returns only pages that have an Appointment Date set.
    """
    settings = get_settings()
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=minutes)

    payload = {
        "filter": {
            "timestamp": "last_edited_time",
            "last_edited_time": {
                "on_or_after": cutoff.isoformat(),
            },
        },
        "sorts": [
            {"timestamp": "last_edited_time", "direction": "descending"}
        ],
        "page_size": 50,
    }

    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(
            f"{NOTION_BASE}/databases/{settings.notion_leads_db_id}/query",
            headers=_headers(),
            json=payload,
        )
        resp.raise_for_status()
        results = resp.json().get("results", [])

    # Filter to only pages with Appointment Date set
    return [
        page for page in results
        if _date_value(page.get("properties", {}).get("Appointment Date", {}))
    ]


async def poll_recent_changes_no_appointment(minutes: int = 6) -> List[Dict[str, Any]]:
    """Bug 4 fix: Poll for recently modified pages WITHOUT Appointment Date.

    These may be leads whose appointment was cancelled (date removed in Notion).
    Only returns pages that have a GHL Contact ID in Aggregate Comments,
    indicating they previously had a sync relationship.
    """
    settings = get_settings()
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=minutes)

    payload = {
        "filter": {
            "and": [
                {
                    "timestamp": "last_edited_time",
                    "last_edited_time": {
                        "on_or_after": cutoff.isoformat(),
                    },
                },
                {
                    "property": "Appointment Date",
                    "date": {"is_empty": True},
                },
            ]
        },
        "sorts": [
            {"timestamp": "last_edited_time", "direction": "descending"}
        ],
        "page_size": 50,
    }

    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(
            f"{NOTION_BASE}/databases/{settings.notion_leads_db_id}/query",
            headers=_headers(),
            json=payload,
        )
        resp.raise_for_status()
        results = resp.json().get("results", [])

    # Only return pages that have a GHL Contact ID (they were previously synced)
    filtered = []
    for page in results:
        props = page.get("properties", {})
        comments_items = props.get("Aggregate Comments", {}).get("rich_text", [])
        comments = "".join(item.get("plain_text", "") for item in comments_items) if comments_items else ""
        if "GHL:" in comments:
            filtered.append(page)

    return filtered


# --- Property extractors ---

def _date_value(prop: Dict[str, Any]) -> str:
    """Extract the start date string from a Notion date property."""
    date_obj = prop.get("date")
    if date_obj:
        return date_obj.get("start", "")
    return ""
