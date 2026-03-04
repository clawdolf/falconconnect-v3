"""GoHighLevel API client — contacts, opportunities, appointments."""

import logging
from typing import Any, Dict, Optional

import httpx

from config import get_settings

logger = logging.getLogger("falconconnect.ghl")

GHL_BASE = "https://services.leadconnectorhq.com"
GHL_API_VERSION = "2021-07-28"


def _headers() -> Dict[str, str]:
    settings = get_settings()
    return {
        "Authorization": f"Bearer {settings.ghl_api_key}",
        "Version": GHL_API_VERSION,
        "Content-Type": "application/json",
        "Accept": "application/json",
    }


async def upsert_contact(
    lead: Dict[str, Any],
    location_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Create or update a GHL contact.

    If a contact with the same phone already exists, GHL updates it.
    Returns the full contact object from GHL.
    """
    settings = get_settings()
    loc_id = location_id or settings.ghl_location_id

    payload: Dict[str, Any] = {
        "locationId": loc_id,
        "firstName": lead.get("first_name", ""),
        "lastName": lead.get("last_name", ""),
        "phone": lead.get("phone", ""),
    }

    if lead.get("email"):
        payload["email"] = lead["email"]
    if lead.get("address"):
        payload["address1"] = lead["address"]
    if lead.get("city"):
        payload["city"] = lead["city"]
    if lead.get("state"):
        payload["state"] = lead["state"]
    if lead.get("zip_code"):
        payload["postalCode"] = lead["zip_code"]
    if lead.get("source"):
        payload["source"] = lead["source"]
    if lead.get("notes"):
        payload["tags"] = [lead["source"]] if lead.get("source") else []

    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(
            f"{GHL_BASE}/contacts/upsert",
            headers=_headers(),
            json=payload,
        )
        resp.raise_for_status()
        data = resp.json()
        contact = data.get("contact", data)
        logger.info("GHL upsert_contact → %s", contact.get("id", "unknown"))
        return contact


async def create_opportunity(
    contact_id: str,
    stage: str = "new",
    pipeline_id: Optional[str] = None,
    name: Optional[str] = None,
) -> Dict[str, Any]:
    """Create a pipeline opportunity for a contact.

    Returns the opportunity object from GHL.
    """
    settings = get_settings()

    payload: Dict[str, Any] = {
        "locationId": settings.ghl_location_id,
        "contactId": contact_id,
        "status": "open",
        "stageId": stage,
    }
    if pipeline_id:
        payload["pipelineId"] = pipeline_id
    if name:
        payload["name"] = name

    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(
            f"{GHL_BASE}/opportunities/",
            headers=_headers(),
            json=payload,
        )
        resp.raise_for_status()
        data = resp.json()
        opp = data.get("opportunity", data)
        logger.info("GHL create_opportunity → %s", opp.get("id", "unknown"))
        return opp


async def upsert_appointment(
    contact_id: str,
    start_time: str,
    title: str,
    calendar_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Create or update a calendar appointment in GHL.

    Args:
        contact_id: GHL contact ID.
        start_time: ISO-8601 datetime string.
        title: Appointment title.
        calendar_id: Override the default calendar.

    Returns the appointment object from GHL.
    """
    settings = get_settings()
    cal_id = calendar_id or settings.ghl_calendar_id

    payload = {
        "calendarId": cal_id,
        "locationId": settings.ghl_location_id,
        "contactId": contact_id,
        "startTime": start_time,
        "title": title,
        "appointmentStatus": "confirmed",
    }

    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(
            f"{GHL_BASE}/calendars/events/appointments",
            headers=_headers(),
            json=payload,
        )
        resp.raise_for_status()
        data = resp.json()
        logger.info("GHL upsert_appointment → %s", data.get("id", "unknown"))
        return data


async def get_contact_by_phone(phone: str) -> Optional[Dict[str, Any]]:
    """Look up a GHL contact by phone number."""
    settings = get_settings()

    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.get(
            f"{GHL_BASE}/contacts/search",
            headers=_headers(),
            params={
                "locationId": settings.ghl_location_id,
                "query": phone,
            },
        )
        resp.raise_for_status()
        contacts = resp.json().get("contacts", [])
        if contacts:
            return contacts[0]
    return None
