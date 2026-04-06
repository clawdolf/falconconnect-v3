"""Notion API client — query upcoming calendar events for iCal feeds.

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




# --- Property extractors ---

def _date_value(prop: Dict[str, Any]) -> str:
    """Extract the start date string from a Notion date property."""
    date_obj = prop.get("date")
    if date_obj:
        return date_obj.get("start", "")
    return ""
