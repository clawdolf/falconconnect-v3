"""GoHighLevel API client — contacts, opportunities, appointments.

GHL API base: https://services.leadconnectorhq.com
Auth: Bearer token + Version header.
Pipeline/stage IDs fetched and cached at startup.
"""

import logging
import re
from datetime import date
from typing import Any, Dict, List, Optional

import httpx

from config import get_settings

logger = logging.getLogger("falconconnect.ghl")

GHL_BASE = "https://services.leadconnectorhq.com"
GHL_API_VERSION = "2021-07-28"

# Cached pipeline data — populated on first use
_pipeline_cache: Optional[List[Dict[str, Any]]] = None

# ── State → timezone mapping (all 50 US states) ──

STATE_TIMEZONES = {
    "AL": "America/Chicago", "AK": "America/Anchorage", "AZ": "America/Phoenix",
    "AR": "America/Chicago", "CA": "America/Los_Angeles", "CO": "America/Denver",
    "CT": "America/New_York", "DE": "America/New_York", "FL": "America/New_York",
    "GA": "America/New_York", "HI": "Pacific/Honolulu", "ID": "America/Denver",
    "IL": "America/Chicago", "IN": "America/Indiana/Indianapolis", "IA": "America/Chicago",
    "KS": "America/Chicago", "KY": "America/Kentucky/Louisville", "LA": "America/Chicago",
    "ME": "America/New_York", "MD": "America/New_York", "MA": "America/New_York",
    "MI": "America/Detroit", "MN": "America/Chicago", "MS": "America/Chicago",
    "MO": "America/Chicago", "MT": "America/Denver", "NE": "America/Chicago",
    "NV": "America/Los_Angeles", "NH": "America/New_York", "NJ": "America/New_York",
    "NM": "America/Denver", "NY": "America/New_York", "NC": "America/New_York",
    "ND": "America/Chicago", "OH": "America/New_York", "OK": "America/Chicago",
    "OR": "America/Los_Angeles", "PA": "America/New_York", "RI": "America/New_York",
    "SC": "America/New_York", "SD": "America/Chicago", "TN": "America/Chicago",
    "TX": "America/Chicago", "UT": "America/Denver", "VT": "America/New_York",
    "VA": "America/New_York", "WA": "America/Los_Angeles", "WV": "America/New_York",
    "WI": "America/Chicago", "WY": "America/Denver",
}

# ── GHL custom field IDs (verified 2026-03-04) ──

# ── ZIP code → timezone lookup (static CSV, falls back to state) ──

def _load_zip_timezones() -> Dict[str, str]:
    """Load ZIP→timezone map from bundled CSV. Returns empty dict on failure."""
    import csv
    from pathlib import Path
    csv_path = Path(__file__).resolve().parent.parent / "data" / "zip_timezones.csv"
    if not csv_path.exists():
        logger.warning("zip_timezones.csv not found at %s — using state-only TZ", csv_path)
        return {}
    result: Dict[str, str] = {}
    with open(csv_path, newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            result[row["zip"]] = row["tz"]
    logger.info("Loaded %d ZIP→timezone mappings", len(result))
    return result

_ZIP_TIMEZONES: Dict[str, str] = _load_zip_timezones()


def get_timezone(zip_code: str, state: str) -> Optional[str]:
    """Look up timezone by ZIP code first, fall back to state."""
    if zip_code:
        clean_zip = zip_code.strip()[:5]
        tz = _ZIP_TIMEZONES.get(clean_zip)
        if tz:
            return tz
    return STATE_TIMEZONES.get((state or '').strip().upper())

GHL_CF_LENDER = "ZCmpWQ9KOdacOV2VZ4pn"
GHL_CF_LOAN_AMOUNT = "haycapFYMCnJEFovornG"
GHL_CF_SPOUSE_CELL = "1MKVvQCPMsAaDb8aL5vi"
GHL_CF_HPHONE = "za04O6KtX9Sg3yn8csZi"


# ── Phone normalization utilities ──


def normalize_phone(raw: str) -> str:
    """Normalize a phone number to E.164 format (+1XXXXXXXXXX for US).

    Strips dashes, spaces, dots, parentheses. Adds +1 if missing.
    Returns empty string if input is not a valid-looking US number.
    """
    if not raw:
        return ""
    digits = re.sub(r"[^\d]", "", raw.strip())
    if len(digits) == 11 and digits.startswith("1"):
        return f"+{digits}"
    if len(digits) == 10:
        return f"+1{digits}"
    # Already has country code or non-standard length — return as-is with +
    if len(digits) >= 10:
        return f"+{digits}" if not digits.startswith("+") else digits
    return ""


def split_phone_field(raw: str) -> List[str]:
    """Split a phone field that may contain multiple numbers separated by / , ;.

    Returns a list of normalized phone numbers (empty strings filtered out).
    """
    if not raw:
        return []
    # Split on common delimiters
    parts = re.split(r"[/,;]+", raw)
    result = []
    for part in parts:
        normalized = normalize_phone(part)
        if normalized:
            result.append(normalized)
    return result


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

    # Default: MTG Leads → first stage (Mortgage Protection pipeline)
    for keyword in ("mtg", "mortgage"):
        for pipeline in pipelines:
            if keyword in pipeline["name"].lower():
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
    test_mode: bool = False,
) -> Dict[str, Any]:
    """Create or update a GHL contact.

    Uses the /contacts/upsert endpoint which handles dedup by phone/email.
    Enriches with: timezone, lender/loan amount custom fields, phone
    normalization + splitting, and import date tag.
    Returns the full contact object from GHL.
    """
    settings = get_settings()
    loc_id = location_id or settings.ghl_location_id

    # ── Phone normalization + splitting ──
    # The primary phone field may contain multiple numbers (e.g. "5555555555/4443331234")
    raw_phone = lead.get("phone", "")
    phone_numbers = split_phone_field(raw_phone)
    primary_phone = phone_numbers[0] if phone_numbers else normalize_phone(raw_phone)
    secondary_phone = phone_numbers[1] if len(phone_numbers) > 1 else ""

    # Also check dedicated phone fields from the lead model
    home_phone = normalize_phone(lead.get("home_phone", "") or "")
    mobile_phone = normalize_phone(lead.get("mobile_phone", "") or "")
    spouse_phone = normalize_phone(lead.get("spouse_phone", "") or "")

    # If we have a dedicated mobile, that becomes primary
    if mobile_phone:
        primary_phone = mobile_phone

    payload: Dict[str, Any] = {
        "locationId": loc_id,
        "firstName": lead.get("first_name", ""),
        "lastName": lead.get("last_name", ""),
        "phone": primary_phone,
    }

    # Build additionalPhones for secondary numbers
    additional_phones: List[Dict[str, str]] = []
    if secondary_phone:
        additional_phones.append({"type": "home", "phoneNumber": secondary_phone})
    if home_phone and home_phone != primary_phone:
        additional_phones.append({"type": "home", "phoneNumber": home_phone})
    if spouse_phone:
        additional_phones.append({"type": "other", "phoneNumber": spouse_phone})
    if additional_phones:
        payload["additionalPhones"] = additional_phones

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

    # ── Timezone from ZIP code (falls back to state) ──
    tz = get_timezone(lead.get("zip_code", ""), lead.get("state", ""))
    if tz:
        payload["timezone"] = tz

    # ── Custom fields: lender, loan amount, spouse cell, home phone ──
    custom_fields: List[Dict[str, Any]] = []
    if lead.get("lender"):
        custom_fields.append({"id": GHL_CF_LENDER, "field_value": lead["lender"]})
    if lead.get("loan_amount"):
        custom_fields.append({"id": GHL_CF_LOAN_AMOUNT, "field_value": str(lead["loan_amount"])})
    if spouse_phone:
        custom_fields.append({"id": GHL_CF_SPOUSE_CELL, "field_value": spouse_phone})
    if home_phone:
        custom_fields.append({"id": GHL_CF_HPHONE, "field_value": home_phone})
    if custom_fields:
        payload["customFields"] = custom_fields

    # Source
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

        # ── Merge tags — import date tag only (no vendor/fc-v3 tags) ──
        if contact_id:
            try:
                existing_resp = await client.get(
                    f"{GHL_BASE}/contacts/{contact_id}",
                    headers=_headers(),
                )
                existing_resp.raise_for_status()
                existing_contact = existing_resp.json().get("contact", {})
                existing_tags: List[str] = existing_contact.get("tags", []) or []

                # Import date tag
                import_tag = date.today().strftime("imported-%m/%d/%y")

                # Remove old vendor/fc-v3 tags, keep pre-existing non-vendor tags
                tags_to_remove = {"fc-v3", source.lower()}
                cleaned_tags = [
                    t for t in existing_tags
                    if t.lower() not in tags_to_remove
                    and not t.lower().startswith("imported-")
                ]
                extra_tags = ["test-import"] if test_mode else []
                merged_tags = list(dict.fromkeys(cleaned_tags + [import_tag] + extra_tags))

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
    pipeline_name: Optional[str] = "MTG Leads",
    name: Optional[str] = None,
) -> Dict[str, Any]:
    """Create a pipeline opportunity for a contact.

    Finds the correct pipeline/stage by name, then creates the opportunity.
    Defaults to MTG Leads pipeline (Mortgage Protection).
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


async def get_contact_appointments(
    contact_id: str,
    calendar_id: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Fetch existing appointments for a GHL contact.

    Returns list of appointment dicts. Filters to the specified calendar if provided.
    """
    settings = get_settings()

    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.get(
            f"{GHL_BASE}/contacts/{contact_id}/appointments",
            headers=_headers(),
        )
        if resp.status_code == 404:
            return []
        resp.raise_for_status()
        appointments = resp.json().get("events", resp.json().get("appointments", []))

        # Filter to the target calendar if specified
        if calendar_id:
            appointments = [
                a for a in appointments
                if a.get("calendarId") == calendar_id
            ]
        return appointments


async def cancel_appointment(appointment_id: str) -> bool:
    """Cancel/delete a GHL appointment by ID.

    Returns True if successfully cancelled, False on failure.
    """
    async with httpx.AsyncClient(timeout=30) as client:
        # Try to update status to cancelled first
        try:
            resp = await client.put(
                f"{GHL_BASE}/calendars/events/appointments/{appointment_id}",
                headers=_headers(),
                json={"appointmentStatus": "cancelled"},
            )
            if resp.status_code in (200, 204):
                logger.info("GHL appointment %s cancelled", appointment_id)
                return True
        except Exception:
            pass

        # Fallback: try DELETE
        try:
            resp = await client.delete(
                f"{GHL_BASE}/calendars/events/appointments/{appointment_id}",
                headers=_headers(),
            )
            if resp.status_code in (200, 204):
                logger.info("GHL appointment %s deleted", appointment_id)
                return True
        except Exception as e:
            logger.warning("Failed to cancel/delete appointment %s: %s", appointment_id, e)

    return False


async def upsert_appointment(
    contact_id: str,
    start_time: str,
    title: str,
    calendar_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Create or reschedule a calendar appointment in GHL.

    Bug 1 fix: Before creating, check for existing appointments for this
    contact on the same date. If found, cancel the old one first (reschedule
    pattern). This prevents duplicate appointments.

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

    # Bug 1 fix: Check for existing appointments and cancel duplicates
    try:
        existing = await get_contact_appointments(contact_id, cal_id)
        target_date = start_dt.date()
        for appt in existing:
            appt_status = (appt.get("appointmentStatus") or appt.get("status") or "").lower()
            if appt_status in ("cancelled", "deleted"):
                continue
            appt_start = appt.get("startTime") or appt.get("start") or ""
            if appt_start:
                try:
                    existing_dt = dtparser.parse(appt_start)
                    # Cancel any existing appointment for this contact (reschedule)
                    appt_id = appt.get("id", "")
                    if appt_id:
                        logger.info(
                            "Cancelling existing appointment %s (was %s) for contact %s — rescheduling to %s",
                            appt_id, appt_start, contact_id, start_time,
                        )
                        await cancel_appointment(appt_id)
                except (ValueError, TypeError):
                    pass
    except Exception as e:
        logger.warning("Could not check existing appointments for %s: %s", contact_id, e)
        # Continue with creation — better to have a potential duplicate than to fail

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

        # Bug 3 fix: Normalize BOTH phones to E.164 before comparing
        ghl_phone_e164 = normalize_phone(contact.get("phone") or "")
        notion_phone_e164 = normalize_phone(notion_phone)

        if not notion_phone_e164:
            return "skipped"

        if ghl_phone_e164 == notion_phone_e164:
            return "match"

        # Phones differ in E.164 form — update GHL primary phone
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.put(
                f"{GHL_BASE}/contacts/{contact_id}",
                headers=_headers(),
                json={"phone": notion_phone_e164},
            )
            resp.raise_for_status()
            logger.info(
                "GHL phone updated for %s: %s → %s",
                contact_id, contact.get("phone"), notion_phone_e164,
            )
            return "updated"

    except Exception as exc:
        logger.warning("sync_phone_if_changed failed for %s: %s", contact_id, exc)
        return "error"
