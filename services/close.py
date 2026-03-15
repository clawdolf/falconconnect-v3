"""Close.com API service — bulk lead import (replaces Notion + GHL write path).

Creates Leads with embedded Contacts, custom fields, notes, and spouse
detection.  Field IDs are fetched dynamically on first call and cached.

Rate limiting: caller manages 0.3s sleep between calls.
429 retry: handled internally with Retry-After header.
"""

import asyncio
import logging
import re
from datetime import datetime
from typing import Any, Dict, List, Optional

import httpx

from config import get_settings

logger = logging.getLogger("falconconnect.close_bulk")

BASE_URL = "https://api.close.com/api/v1"

# Module-level cache for custom field name → ID mapping
_custom_field_cache: Optional[Dict[str, str]] = None

# Default status for new bulk-imported leads
DEFAULT_STATUS_ID = "stat_FncoFJQfuuXdXbNx0HbwsKVR7EA95OhoQmqEPNMXl7T"  # "New Lead"


# ── Phone normalization ──


def normalize_phone(raw: str) -> str:
    """Normalize a phone number to +1XXXXXXXXXX (E.164 US).

    Strips all non-digit chars, prepends +1 if missing.
    Returns empty string if result doesn't look like a valid US number.
    """
    if not raw:
        return ""
    digits = re.sub(r"[^\d]", "", str(raw).strip())
    if len(digits) == 11 and digits.startswith("1"):
        return f"+{digits}"
    if len(digits) == 10:
        return f"+1{digits}"
    if len(digits) >= 10:
        return f"+{digits}" if not raw.startswith("+") else raw.strip()
    return ""


# ── Date parsing (reused from notion.py pattern) ──


def _parse_date_flexible(val) -> Optional[str]:
    """Parse a date value to YYYY-MM-DD string.  Handles date objects,
    isoformat strings, and common vendor formats (M/D/YY, M/D/YYYY).
    Returns None if unparseable.
    """
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


# ── Auth helper ──


def _auth() -> tuple:
    """Return (api_key, '') tuple for httpx basic auth."""
    settings = get_settings()
    api_key = settings.close_api_key
    if not api_key:
        raise RuntimeError("CLOSE_API_KEY not configured")
    return (api_key, "")


# ── Custom field ID fetching + caching ──


async def fetch_custom_field_ids() -> Dict[str, str]:
    """Fetch custom field name → ID mapping from Close.com.

    Caches the result in module-level dict.  Call this once at startup
    or on first use.  Returns {field_name: field_id}.
    """
    global _custom_field_cache
    if _custom_field_cache is not None:
        return _custom_field_cache

    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.get(
            f"{BASE_URL}/custom_field/lead/",
            auth=_auth(),
        )
        resp.raise_for_status()
        data = resp.json()

    _custom_field_cache = {}
    for field in data.get("data", []):
        name = field.get("name", "")
        field_id = field.get("id", "")
        if name and field_id:
            _custom_field_cache[name] = field_id

    logger.info("Cached %d Close custom field IDs", len(_custom_field_cache))
    return _custom_field_cache


def _get_cf_id(name: str, cf_map: Dict[str, str]) -> Optional[str]:
    """Look up a custom field ID by name (case-insensitive fallback)."""
    # Exact match first
    if name in cf_map:
        return cf_map[name]
    # Case-insensitive
    name_lower = name.lower()
    for k, v in cf_map.items():
        if k.lower() == name_lower:
            return v
    return None


# ── Spouse / co-borrower detection ──


def _detect_spouse(full_name: str) -> tuple:
    """Detect spouse/co-borrower in a name field.

    Splits on " + " or " & " (common in mortgage lead lists).
    Returns (primary_name, spouse_name) or (full_name, None).
    """
    if not full_name:
        return (full_name, None)
    for sep in (" + ", " & "):
        if sep in full_name:
            parts = full_name.split(sep, 1)
            return (parts[0].strip(), parts[1].strip())
    return (full_name, None)


# ── Gender normalization ──


def _normalize_gender(raw: str) -> Optional[str]:
    """Normalize gender to M/F for Close choices field."""
    if not raw:
        return None
    g = str(raw).strip().lower()
    if g in {"m", "male", "man"}:
        return "M"
    if g in {"f", "female", "woman"}:
        return "F"
    return None


# ── State normalization ──

_STATE_MAP = {
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


def _normalize_state(raw: str) -> str:
    """Normalize full state name to 2-letter code."""
    if not raw:
        return ""
    return _STATE_MAP.get(raw.strip().lower(), raw.strip().upper()[:2])


# ── LAge bracket (matches Notion / Close choices) ──

LAGE_BRACKETS = [
    (0,  7,    "3+ Month"),
    (7,  13,   "7-12M"),
    (13, 25,   "13-24M"),
    (25, 37,   "25-36M"),
    (37, 49,   "37-48M"),
    (49, 61,   "49-60M"),
    (61, 9999, "60+M"),
]


def _lage_select(months: Optional[int]) -> Optional[str]:
    """Convert lage months to bracket label."""
    if months is None:
        return None
    for low, high, label in LAGE_BRACKETS:
        if low <= months < high:
            return label
    return "60+M"


# ── Core API: create lead ──


async def create_lead(lead_dict: dict) -> dict:
    """Create a lead in Close.com from an FC lead dict.

    Maps all FC fields to the Close API payload:
    - Primary contact with phones + email
    - Spouse as second contact (detected from name or spouse fields)
    - Address as native Close address object
    - Custom fields by dynamically-fetched field ID
    - Default status: "New Lead"

    Returns: {"id": "lead_xxx", "is_new": True}
    Raises on API failure (after retry on 429).
    """
    # Ensure custom field cache is populated
    cf_map = await fetch_custom_field_ids()

    # ── Build lead name ──
    first = lead_dict.get("first_name", "").strip()
    last = lead_dict.get("last_name", "").strip()
    full_name = f"{first} {last}".strip()

    # Spouse detection from name (split on " + " or " & ")
    primary_name, spouse_name = _detect_spouse(full_name)

    # ── Primary contact ──
    primary_phone = normalize_phone(lead_dict.get("phone", ""))
    home_phone = normalize_phone(lead_dict.get("home_phone", ""))

    phones: List[Dict[str, str]] = []
    if primary_phone:
        phones.append({"phone": primary_phone, "type": "mobile"})
    if home_phone and home_phone != primary_phone:
        phones.append({"phone": home_phone, "type": "home"})

    primary_contact: Dict[str, Any] = {"name": primary_name}
    if phones:
        primary_contact["phones"] = phones
    if lead_dict.get("email"):
        primary_contact["emails"] = [{"email": lead_dict["email"], "type": "office"}]

    contacts = [primary_contact]

    # ── Spouse contact (if detected) ──
    if spouse_name:
        spouse_contact: Dict[str, Any] = {"name": spouse_name}
        spouse_phone = normalize_phone(lead_dict.get("spouse_phone", ""))
        if spouse_phone:
            spouse_contact["phones"] = [{"phone": spouse_phone, "type": "mobile"}]
        contacts.append(spouse_contact)

    # ── Address ──
    addresses: List[Dict[str, str]] = []
    addr_parts: Dict[str, str] = {}
    if lead_dict.get("address"):
        addr_parts["address_1"] = lead_dict["address"]
    if lead_dict.get("city"):
        addr_parts["city"] = lead_dict["city"]
    state_norm = _normalize_state(lead_dict.get("state", ""))
    if state_norm:
        addr_parts["state"] = state_norm
    if lead_dict.get("zip_code"):
        # Normalize ZIP: first 5 digits, zero-padded
        zip_digits = re.sub(r"\D", "", str(lead_dict["zip_code"]))[:5]
        zip_norm = zip_digits.zfill(5) if 1 <= len(zip_digits) <= 5 else zip_digits
        if zip_norm:
            addr_parts["zipcode"] = zip_norm
    if addr_parts:
        addr_parts["label"] = "business"
        addr_parts["country"] = "US"
        addresses.append(addr_parts)

    # ── Custom fields ──
    custom: Dict[str, Any] = {}

    def _set_cf(field_name: str, value: Any):
        """Set a custom field if the field exists and value is non-empty."""
        if value is None or value == "":
            return
        cf_id = _get_cf_id(field_name, cf_map)
        if cf_id:
            custom[f"custom.{cf_id}"] = value

    # Text / choices fields
    _set_cf("County", lead_dict.get("county"))
    _set_cf("Lead Source", lead_dict.get("lead_source"))
    _set_cf("Lead Type", lead_dict.get("lead_type"))
    _set_cf("Lender", lead_dict.get("lender"))
    _set_cf("Best Time to Call", lead_dict.get("best_time_to_call"))
    _set_cf("Tier", lead_dict.get("tier"))
    _set_cf("Vendor Lead ID", lead_dict.get("vendor_lead_id"))

    # Loan Amount (number) — strip non-numeric chars, convert to float
    loan_raw = lead_dict.get("loan_amount")
    if loan_raw:
        try:
            loan_num = float(re.sub(r"[^\d.]", "", str(loan_raw)))
            _set_cf("Loan Amount", loan_num)
        except (ValueError, TypeError):
            _set_cf("Loan Amount", str(loan_raw))

    # Lead Purchase Date (date) — from lpd or mail_date
    lpd_raw = lead_dict.get("lpd") or lead_dict.get("mail_date")
    if lpd_raw:
        lpd_parsed = _parse_date_flexible(lpd_raw)
        if lpd_parsed:
            _set_cf("Lead Purchase Date", lpd_parsed)

    # Lead Age bracket (LAge)
    lead_age_bucket = lead_dict.get("lead_age_bucket")
    if lead_age_bucket:
        _set_cf("Lead Age", lead_age_bucket)

    # Age (number: current year - birth_year)
    birth_year = lead_dict.get("birth_year")
    if birth_year:
        try:
            age = datetime.now().year - int(birth_year)
            if 0 < age < 150:
                _set_cf("Age", age)
        except (ValueError, TypeError):
            pass

    # DOB — Close doesn't have a DOB custom field currently, but if one
    # gets created we'll pick it up via dynamic field fetch
    if lead_dict.get("dob"):
        dob_parsed = _parse_date_flexible(lead_dict["dob"])
        if dob_parsed:
            _set_cf("DOB", dob_parsed)

    # Gender (choices: M/F)
    gender = _normalize_gender(lead_dict.get("gender"))
    if gender:
        _set_cf("Gender", gender)

    # Boolean-as-string fields (choices: Yes/No)
    if lead_dict.get("tobacco") is not None:
        _set_cf("Tobacco", "Yes" if lead_dict["tobacco"] else "No")
    if lead_dict.get("medical") is not None:
        _set_cf("Medical Issues", "Yes" if lead_dict["medical"] else "No")
    if lead_dict.get("spanish") is not None:
        _set_cf("Spanish", "Yes" if lead_dict["spanish"] else "No")

    # Spouse flag
    if spouse_name:
        _set_cf("Spouse", "Yes")

    # Spouse Age
    if lead_dict.get("spouse_age") is not None:
        try:
            _set_cf("Spouse Age", int(lead_dict["spouse_age"]))
        except (ValueError, TypeError):
            pass

    # ── Build payload ──
    payload: Dict[str, Any] = {
        "name": primary_name,
        "status_id": DEFAULT_STATUS_ID,
        "contacts": contacts,
    }
    if addresses:
        payload["addresses"] = addresses
    # Merge custom fields into payload top-level (Close API uses "custom.cf_xxx" keys)
    payload.update(custom)

    # ── Send to Close.com with 429 retry ──
    async with httpx.AsyncClient(timeout=30.0) as client:
        lead_data = await _post_with_retry(client, f"{BASE_URL}/lead/", payload)

    lead_id = lead_data["id"]
    logger.info("Close lead created: %s (%s)", lead_id, primary_name)

    return {"id": lead_id, "is_new": True}


# ── Add note to lead ──


async def add_note(lead_id: str, note_text: str) -> Optional[str]:
    """Create an activity note on a Close lead.

    Returns note ID on success, None on failure (non-fatal).
    """
    if not note_text or not lead_id:
        return None

    payload = {
        "lead_id": lead_id,
        "note": note_text,
    }

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            data = await _post_with_retry(client, f"{BASE_URL}/activity/note/", payload)
        note_id = data.get("id", "")
        logger.info("Close note created on %s: %s", lead_id, note_id)
        return note_id
    except Exception as exc:
        logger.warning("Close add_note failed for %s (non-fatal): %s", lead_id, exc)
        return None


# ── HTTP helper with 429 retry ──


async def _post_with_retry(
    client: httpx.AsyncClient,
    url: str,
    payload: dict,
    max_retries: int = 3,
) -> dict:
    """POST to Close.com with automatic 429 retry using Retry-After header."""
    for attempt in range(max_retries):
        resp = await client.post(url, json=payload, auth=_auth())
        if resp.status_code == 429:
            retry_after = int(resp.headers.get("Retry-After", "2"))
            logger.warning(
                "Close 429 rate limit — waiting %ds (attempt %d/%d)",
                retry_after, attempt + 1, max_retries,
            )
            await asyncio.sleep(retry_after)
            continue
        resp.raise_for_status()
        return resp.json()

    # Last attempt failed with 429 — raise
    resp.raise_for_status()
    return resp.json()
