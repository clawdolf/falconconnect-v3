"""Quo (OpenPhone) API integration — sync contacts after Notion/GHL import.

API structure from Seb's working script:
- GET /v1/contacts?externalIds=[phone] → check if contact exists
- PATCH /v1/contacts/{id} → update existing
- POST /v1/contacts → create new
- Payload uses defaultFields.firstName + defaultFields.phoneNumbers (not top-level)
- externalId = primary phone (E.164) — used as dedup key
- customFields uses { key, value } pairs
"""

import asyncio
import logging
from typing import Dict, Any, List, Optional

import httpx

from config import get_settings

logger = logging.getLogger("falconconnect.quo")

QUO_BASE = "https://api.openphone.com/v1"

# Custom field keys — from Seb's working helper script
CUSTOM_FIELDS_MAP = {
    "State":   "690bbacefd425c5afcd20b24",
    "Lender":  "690bbaeffd425c5afcd20b2e",
    "Address": "690bbaf5fd425c5afcd20b37",
}

# Rate limit safety between calls (200ms matches working script)
RATE_LIMIT_DELAY = 0.2


def _headers() -> Dict[str, str]:
    settings = get_settings()
    return {
        "Authorization": settings.quo_api_key,
        "Content-Type": "application/json",
    }


def _to_e164(phone: str) -> str:
    """Normalize phone to E.164 — matches logic from Seb's script."""
    cleaned = "".join(c for c in str(phone) if c.isdigit())
    if cleaned and not cleaned.startswith("1"):
        cleaned = "1" + cleaned
    if len(cleaned) == 11:
        cleaned = "+" + cleaned
    return cleaned if cleaned.startswith("+") and len(cleaned) >= 12 else ""


async def sync_contact(
    lead: Dict[str, Any],
    test_mode: bool = False,
) -> Optional[str]:
    """Sync a single lead to Quo (OpenPhone) using the correct API structure.

    Returns Quo contact ID on success, None on failure (non-fatal).
    Flow: GET to check exists → PATCH if yes → POST if no.
    """
    # Primary phone (E.164)
    raw_phone = lead.get("phone") or lead.get("mobile_phone") or ""
    primary_e164 = _to_e164(str(raw_phone))
    if not primary_e164:
        logger.debug("Quo sync skipped — no valid phone for %s %s", lead.get("first_name"), lead.get("last_name"))
        return None

    # Home phone (secondary)
    raw_home = lead.get("home_phone") or ""
    home_e164 = _to_e164(str(raw_home)) if raw_home else ""

    # Build phone numbers list
    phone_numbers: List[Dict[str, str]] = [{"name": "Mobile", "value": primary_e164}]
    if home_e164 and home_e164 != primary_e164:
        phone_numbers.append({"name": "Home", "value": home_e164})

    # Build custom fields
    custom_fields = []
    if lead.get("state"):
        custom_fields.append({"key": CUSTOM_FIELDS_MAP["State"], "value": lead["state"]})
    if lead.get("lender"):
        custom_fields.append({"key": CUSTOM_FIELDS_MAP["Lender"], "value": lead["lender"]})
    # Build address string
    addr_parts = [p for p in [
        lead.get("address"),
        lead.get("city"),
        lead.get("state"),
        lead.get("zip_code"),
    ] if p]
    if addr_parts:
        custom_fields.append({"key": CUSTOM_FIELDS_MAP["Address"], "value": ", ".join(addr_parts)})

    # Contact name — test mode appends [TEST] so it's easy to find/delete
    first = lead.get("first_name", "")
    last = lead.get("last_name", "")

    payload: Dict[str, Any] = {
        "externalId": primary_e164,
        "defaultFields": {
            "firstName": first,
            "lastName": last,
            "phoneNumbers": phone_numbers,
        },
    }
    if lead.get("email"):
        payload["defaultFields"]["emails"] = [{"name": "Primary", "value": lead["email"]}]
    if custom_fields:
        payload["customFields"] = custom_fields

    try:
        async with httpx.AsyncClient(timeout=30) as client:
            # Step 1: Check if contact already exists by externalId (primary phone)
            check_resp = await client.get(
                f"{QUO_BASE}/contacts",
                headers=_headers(),
                params={"externalIds": [primary_e164]},
            )
            await asyncio.sleep(RATE_LIMIT_DELAY)

            if check_resp.status_code == 200 and check_resp.json().get("data"):
                # Exists — PATCH
                existing_id = check_resp.json()["data"][0]["id"]
                r = await client.patch(
                    f"{QUO_BASE}/contacts/{existing_id}",
                    headers=_headers(),
                    json=payload,
                )
                if r.status_code not in (200, 201):
                    logger.warning("Quo PATCH %s → HTTP %s: %s", primary_e164, r.status_code, r.text[:200])
                    return None
                logger.info("Quo PATCH → %s %s (%s)", first, last, existing_id)
                return existing_id
            else:
                # New — POST
                r = await client.post(
                    f"{QUO_BASE}/contacts",
                    headers=_headers(),
                    json=payload,
                )
                if r.status_code not in (200, 201):
                    logger.warning("Quo POST %s → HTTP %s: %s", primary_e164, r.status_code, r.text[:200])
                    return None
                data = r.json()
                contact_id = (data.get("data") or {}).get("id") or data.get("id", "")
                logger.info("Quo POST → %s %s (%s)", first, last, contact_id)
                return contact_id

    except Exception as exc:
        logger.warning("Quo sync failed for %s %s (non-fatal): %s", first, last, exc)
        return None
