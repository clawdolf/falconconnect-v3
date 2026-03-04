"""Notion API client — upsert leads, poll for changes, update pages."""

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

import httpx

from config import get_settings

logger = logging.getLogger("falconconnect.notion")

NOTION_BASE = "https://api.notion.com/v1"
NOTION_VERSION = "2022-06-28"


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

    # Check if lead already exists by phone
    existing = await _find_page_by_phone(db_id, lead.get("phone", ""))
    if existing:
        page_id = existing
        await update_page(page_id, _build_properties(lead, ghl_contact_id, age, lage_months))
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
            "property": "Phone",
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
    """Build Notion page properties from a lead dict."""
    props: Dict[str, Any] = {
        "Name": {
            "title": [
                {
                    "text": {
                        "content": f"{lead.get('first_name', '')} {lead.get('last_name', '')}".strip()
                    }
                }
            ]
        },
        "Phone": {"phone_number": lead.get("phone", "")},
        "GHL Contact ID": {
            "rich_text": [{"text": {"content": ghl_contact_id}}]
        },
        "Source": {
            "rich_text": [{"text": {"content": lead.get("source", "website")}}]
        },
        "Status": {"select": {"name": "New Lead"}},
    }

    if lead.get("email"):
        props["Email"] = {"email": lead["email"]}
    if lead.get("address"):
        props["Address"] = {
            "rich_text": [{"text": {"content": lead["address"]}}]
        }
    if lead.get("city"):
        props["City"] = {
            "rich_text": [{"text": {"content": lead["city"]}}]
        }
    if lead.get("state"):
        props["State"] = {
            "rich_text": [{"text": {"content": lead["state"]}}]
        }
    if lead.get("zip_code"):
        props["Zip"] = {
            "rich_text": [{"text": {"content": lead["zip_code"]}}]
        }
    if age is not None:
        props["Age"] = {"number": age}
    if lage_months is not None:
        props["LAge"] = {"number": lage_months}
    if lead.get("notes"):
        props["Notes"] = {
            "rich_text": [{"text": {"content": lead["notes"]}}]
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


async def get_recently_modified(minutes: int = 6) -> List[Dict[str, Any]]:
    """Poll the leads database for pages modified in the last N minutes.

    Useful for detecting appointment date changes made directly in Notion.
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
        return resp.json().get("results", [])


async def query_upcoming_appointments(days: int = 90) -> List[Dict[str, Any]]:
    """Query Notion for leads with Appointment Date in the next N days.

    Returns pages with Appointment Date or Follow-Up Date set.
    """
    settings = get_settings()
    today = datetime.now(timezone.utc).date()
    future = today + timedelta(days=days)

    payload = {
        "filter": {
            "or": [
                {
                    "property": "Appointment Date",
                    "date": {
                        "on_or_after": today.isoformat(),
                        "on_or_before": future.isoformat(),
                    },
                },
                {
                    "property": "Follow-Up Date",
                    "date": {
                        "on_or_after": today.isoformat(),
                        "on_or_before": future.isoformat(),
                    },
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
        return resp.json().get("results", [])
