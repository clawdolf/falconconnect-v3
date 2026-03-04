"""GoHighLevel API client — contacts, opportunities, appointments.

GHL API base: https://services.leadconnectorhq.com
Auth: Bearer token + Version header.
Pipeline/stage IDs fetched and cached at startup.
"""

import logging
from typing import Any, Dict, List, Optional

import httpx

from config import get_settings

logger = logging.getLogger("falconconnect.ghl")

GHL_BASE = "https://services.leadconnectorhq.com"
GHL_API_VERSION = "2021-07-28"

# Cached pipeline data — populated on first use
_pipeline_cache: Optional[List[Dict[str, Any]]] = None


def _headers() -> Dict[str, str]:
    settings = get_settings()
    return {
        "Authorization": f"Bearer {settings.ghl_api_key}",
        "Version": GHL_API_VERSION,
        "Content-Type": "application/json",
        "Accept": "application/json",
    }


async def _get_pipelines() -> List[Dict[str, Any]]:
    """Fetch and cache pipeline data from GHL."""
    global _pipeline_cache
    if _pipeline_cache is not None:
        return _pipeline_cache

    settings = get_settings()
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.get(
            f"{GHL_BASE}/opportunities/pipelines",
            headers=_headers(),
            params={"locationId": settings.ghl_location_id},
        )
        resp.raise_for_status()
        _pipeline_cache = resp.json().get("pipelines", [])
        logger.info("Cached %d GHL pipelines", len(_pipeline_cache))
        return _pipeline_cache


async def _find_stage(stage_name: str, pipeline_name: Optional[str] = None) -> Dict[str, str]:
    """Find a pipeline stage by name. Returns {pipelineId, stageId}.

    If pipeline_name is None, searches all pipelines and returns the first match.
    Defaults to FEX Leads pipeline → "New Lead" stage if nothing matches.
    """
    pipelines = await _get_pipelines()

    for pipeline in pipelines:
        if pipeline_name and pipeline_name.lower() not in pipeline["name"].lower():
            continue
        for stage in pipeline.get("stages", []):
            # Strip emojis for comparison
            clean_name = stage["name"].split("\u200b")[0].strip()
            # Match by prefix (handles emoji suffixes)
            if stage_name.lower() in clean_name.lower():
                return {
                    "pipelineId": pipeline["id"],
                    "stageId": stage["id"],
                    "pipelineName": pipeline["name"],
                    "stageName": stage["name"],
                }

    # Default: FEX Leads → New Lead
    for pipeline in pipelines:
        if "fex" in pipeline["name"].lower():
            if pipeline.get("stages"):
                first = pipeline["stages"][0]
                return {
                    "pipelineId": pipeline["id"],
                    "stageId": first["id"],
                    "pipelineName": pipeline["name"],
                    "stageName": first["name"],
                }

    # Last resort: first pipeline, first stage
    if pipelines and pipelines[0].get("stages"):
        p = pipelines[0]
        s = p["stages"][0]
        return {
            "pipelineId": p["id"],
            "stageId": s["id"],
            "pipelineName": p["name"],
            "stageName": s["name"],
        }

    raise ValueError("No pipelines/stages found in GHL")


async def upsert_contact(
    lead: Dict[str, Any],
    location_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Create or update a GHL contact.

    Uses the /contacts/upsert endpoint which handles dedup by phone/email.
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

    # Source / tags — upsert first, then merge tags to avoid replacing existing ones
    source = lead.get("lead_source") or lead.get("source") or "FC v3"
    payload["source"] = source
    # Do NOT include tags in the upsert payload — we merge them separately below

    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(
            f"{GHL_BASE}/contacts/upsert",
            headers=_headers(),
            json=payload,
        )
        resp.raise_for_status()
        data = resp.json()
        contact = data.get("contact", data)
        contact_id = contact.get("id", "")
        logger.info("GHL upsert_contact → %s (new=%s)", contact_id, data.get("new", "?"))

        # Merge tags — GET existing, union with new, PUT back
        if contact_id:
            try:
                existing_resp = await client.get(
                    f"{GHL_BASE}/contacts/{contact_id}",
                    headers=_headers(),
                )
                existing_resp.raise_for_status()
                existing_contact = existing_resp.json().get("contact", {})
                existing_tags: List[str] = existing_contact.get("tags", []) or []
                new_tags = [source, "fc-v3"]
                merged_tags = list(dict.fromkeys(existing_tags + new_tags))  # preserve order, dedupe

                tag_resp = await client.put(
                    f"{GHL_BASE}/contacts/{contact_id}",
                    headers=_headers(),
                    json={"tags": merged_tags},
                )
                tag_resp.raise_for_status()
                logger.debug("GHL tags merged for %s: %s", contact_id, merged_tags)
            except Exception as tag_exc:
                logger.warning("GHL tag merge failed (non-fatal): %s", tag_exc)

        return contact


async def create_opportunity(
    contact_id: str,
    stage_name: str = "New Lead",
    pipeline_name: Optional[str] = None,
    name: Optional[str] = None,
) -> Dict[str, Any]:
    """Create a pipeline opportunity for a contact.

    Finds the correct pipeline/stage by name, then creates the opportunity.
    Returns the opportunity object from GHL.
    """
    settings = get_settings()

    stage_info = await _find_stage(stage_name, pipeline_name)
    logger.info(
        "Creating opportunity in %s → %s",
        stage_info["pipelineName"],
        stage_info["stageName"],
    )

    payload: Dict[str, Any] = {
        "locationId": settings.ghl_location_id,
        "contactId": contact_id,
        "pipelineId": stage_info["pipelineId"],
        "pipelineStageId": stage_info["stageId"],
        "status": "open",
    }
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
    """Create a calendar appointment in GHL.

    Args:
        contact_id: GHL contact ID.
        start_time: ISO-8601 datetime string.
        title: Appointment title.
        calendar_id: Override the default calendar.

    Returns the appointment object from GHL.
    """
    settings = get_settings()
    cal_id = calendar_id or settings.ghl_calendar_id

    # End time is 1 hour after start
    from dateutil import parser as dtparser
    from datetime import timedelta
    start_dt = dtparser.parse(start_time)
    end_dt = start_dt + timedelta(hours=1)

    payload = {
        "calendarId": cal_id,
        "locationId": settings.ghl_location_id,
        "contactId": contact_id,
        "startTime": start_dt.isoformat(),
        "endTime": end_dt.isoformat(),
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
            f"{GHL_BASE}/contacts/search/duplicate",
            headers=_headers(),
            params={
                "locationId": settings.ghl_location_id,
                "phone": phone,
            },
        )
        resp.raise_for_status()
        contact = resp.json().get("contact")
        if contact:
            return contact
    return None


async def get_contact_by_id(contact_id: str) -> Optional[Dict[str, Any]]:
    """Look up a GHL contact by ID."""
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.get(
            f"{GHL_BASE}/contacts/{contact_id}",
            headers=_headers(),
        )
        if resp.status_code == 404:
            return None
        resp.raise_for_status()
        return resp.json().get("contact", resp.json())


async def sync_phone_if_changed(contact_id: str, notion_phone: str) -> Optional[str]:
    """Compare Notion best phone against GHL primary phone. Update only if different.

    Returns:
        "updated" if GHL phone was changed.
        "match" if phones already match.
        "skipped" if notion_phone is empty or contact not found.
        "error" on failure.
    """
    if not notion_phone or not contact_id:
        return "skipped"

    try:
        contact = await get_contact_by_id(contact_id)
        if not contact:
            return "skipped"

        # GHL stores phone as E.164 or raw — normalize both for comparison
        ghl_phone = (contact.get("phone") or "").strip().replace(" ", "").replace("-", "").replace("(", "").replace(")", "")
        n_phone = notion_phone.strip().replace(" ", "").replace("-", "").replace("(", "").replace(")", "")

        if ghl_phone == n_phone:
            return "match"

        # Phones differ — update GHL primary phone to Notion best phone
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.put(
                f"{GHL_BASE}/contacts/{contact_id}",
                headers=_headers(),
                json={"phone": notion_phone},
            )
            resp.raise_for_status()
            logger.info(
                "GHL phone updated for %s: %s → %s",
                contact_id, contact.get("phone"), notion_phone,
            )
            return "updated"

    except Exception as exc:
        logger.warning("sync_phone_if_changed failed for %s: %s", contact_id, exc)
        return "error"
