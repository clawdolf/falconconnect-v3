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

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

import httpx

from config import get_settings

logger = logging.getLogger("falconconnect.notion")

NOTION_BASE = "https://api.notion.com/v1"
NOTION_VERSION = "2022-06-28"

# Map LAge months to the select options in the Notion DB
LAGE_BRACKETS = [
    (0, 3, "3+ Month"),
    (3, 7, "3+ Month"),
    (7, 12, "7-12M"),
    (13, 24, "13–24M"),
    (25, 36, "25–36M"),
    (37, 48, "37–48M"),
    (49, 60, "49–60M"),
    (60, 9999, "60+M"),
]


def _lage_select(months: Optional[int]) -> Optional[str]:
    """Convert lage months integer to the closest Notion select option."""
    if months is None:
        return None
    for low, high, label in LAGE_BRACKETS:
        if low <= months <= high:
            return label
    return "60+M"


def _headers() -> Dict[str, str]:
    settings = get_settings()
    return {
        "Authorization": f"Bearer {settings.notion_token}",
        "Notion-Version": NOTION_VERSION,
        "Content-Type": "application/json",
    }


async def upsert_lead(
    lead: Dict[str, Any],
    ghl_contact_id: str,
    age: Optional[int] = None,
    lage_months: Optional[int] = None,
) -> str:
    """Create or update a lead page in the Notion leads database.

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
        props = _build_properties(lead, ghl_contact_id, age, lage_months)
        await update_page(page_id, props)
        logger.info("Notion updated existing page %s", page_id)
        return page_id

    # Create new page
    properties = _build_properties(lead, ghl_contact_id, age, lage_months)
    payload = {
        "parent": {"database_id": db_id},
        "properties": properties,
    }

    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(
            f"{NOTION_BASE}/pages",
            headers=_headers(),
            json=payload,
        )
        resp.raise_for_status()
        page_id = resp.json()["id"]
        logger.info("Notion created new page %s", page_id)
        return page_id


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
        resp = await client.post(
            f"{NOTION_BASE}/databases/{database_id}/query",
            headers=_headers(),
            json=payload,
        )
        resp.raise_for_status()
        results = resp.json().get("results", [])
        if results:
            return results[0]["id"]
    return None


def _build_properties(
    lead: Dict[str, Any],
    ghl_contact_id: str,
    age: Optional[int] = None,
    lage_months: Optional[int] = None,
) -> Dict[str, Any]:
    """Build Notion page properties from a lead dict.

    Uses real Notion DB property names and types.
    """
    full_name = f"{lead.get('first_name', '')} {lead.get('last_name', '')}".strip()

    props: Dict[str, Any] = {
        # title
        "Name": {
            "title": [{"text": {"content": full_name}}]
        },
        # phone_number
        "Mobile Phone": {"phone_number": lead.get("phone", "")},
        # rich_text — cross-reference ID
        "Aggregate Comments": {
            "rich_text": [{"text": {"content": f"GHL:{ghl_contact_id}"}}]
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
    if lead.get("zip_code"):
        props["ZIP Code"] = {"rich_text": [{"text": {"content": lead["zip_code"]}}]}

    # State (select)
    if lead.get("state"):
        props["State"] = {"select": {"name": lead["state"]}}

    # Age (number)
    if age is not None:
        props["Age"] = {"number": age}

    # LAge (select — bracket label, not raw number)
    lage_label = _lage_select(lage_months)
    if lage_label:
        props["LAge"] = {"select": {"name": lage_label}}

    # Lead Source (select)
    lead_source = lead.get("lead_source") or lead.get("source")
    if lead_source:
        props["Lead Source"] = {"select": {"name": lead_source}}

    # Mortgage Sale Date (date) — the original mail date
    mail_date = lead.get("mail_date")
    if mail_date:
        if hasattr(mail_date, "isoformat"):
            mail_date = mail_date.isoformat()
        props["Mortgage Sale Date"] = {"date": {"start": str(mail_date)}}

    # Notes → append to Aggregate Comments
    notes = lead.get("notes", "")
    if notes:
        # Prepend GHL ID, then notes
        comment_text = f"GHL:{ghl_contact_id} | {notes}"
        props["Aggregate Comments"] = {
            "rich_text": [{"text": {"content": comment_text[:2000]}}]
        }

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

    Returns pages tagged with _event_type="appointment".
    """
    settings = get_settings()
    today = datetime.now(timezone.utc).date()

    payload = {
        "filter": {
            "property": "Appointment Date",
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


# --- Property extractors ---

def _date_value(prop: Dict[str, Any]) -> str:
    """Extract the start date string from a Notion date property."""
    date_obj = prop.get("date")
    if date_obj:
        return date_obj.get("start", "")
    return ""
