"""Smart SMS number routing — picks the best outbound number for each prospect.
Priority:
1. Most-used local_phone across last 3 outbound calls + last 3 outbound SMS (frequency wins)
2. Nearest area code match from the phone number pool
3. No hardcoded default — log warning and return None (skip SMS)
"""
import asyncio
import json
import logging
from collections import Counter
from typing import Optional
import httpx
from config import get_settings
from db.database import _get_session_factory
from db.models import PhoneNumber
logger = logging.getLogger("falconconnect.sms_routing")
CLOSE_API_BASE = "https://api.close.com/api/v1"
# Simple state→region map for geographic fallback
# Regions: northeast, southeast, midwest, south, west, southwest
STATE_REGION: dict[str, str] = {
    "AZ": "southwest", "NM": "southwest", "NV": "southwest", "UT": "southwest",
    "TX": "south", "OK": "south", "AR": "south", "LA": "south",
    "FL": "southeast", "GA": "southeast", "SC": "southeast", "NC": "southeast",
    "VA": "southeast", "WV": "southeast", "TN": "southeast", "AL": "southeast",
    "MS": "southeast", "KY": "southeast",
    "PA": "northeast", "NY": "northeast", "NJ": "northeast", "CT": "northeast",
    "MA": "northeast", "RI": "northeast", "VT": "northeast", "NH": "northeast",
    "ME": "northeast", "DE": "northeast", "MD": "northeast", "DC": "northeast",
    "OH": "midwest", "MI": "midwest", "IN": "midwest", "IL": "midwest",
    "WI": "midwest", "MN": "midwest", "IA": "midwest", "MO": "midwest",
    "KS": "midwest", "NE": "midwest", "SD": "midwest", "ND": "midwest",
    "OR": "west", "WA": "west", "CA": "west", "CO": "west",
    "ID": "west", "MT": "west", "WY": "west", "HI": "west", "AK": "west",
}
# Area code → state mapping (covers the area codes in our pool + common ones)
AREA_CODE_STATE: dict[int, str] = {
    480: "AZ", 602: "AZ", 623: "AZ", 520: "AZ",
    406: "MT",
    980: "NC", 984: "NC", 704: "NC", 919: "NC", 336: "NC",
    207: "ME",
    913: "KS", 316: "KS", 785: "KS",
    971: "OR", 541: "OR", 503: "OR",
    832: "TX", 469: "TX", 972: "TX", 214: "TX", 713: "TX", 281: "TX",
    512: "TX", 210: "TX", 817: "TX", 254: "TX", 903: "TX", 940: "TX",
    215: "PA", 267: "PA", 412: "PA", 610: "PA", 717: "PA",
    786: "FL", 305: "FL", 954: "FL", 561: "FL", 407: "FL", 813: "FL",
    727: "FL", 239: "FL", 352: "FL", 904: "FL", 321: "FL", 863: "FL",
}
def _extract_area_code(phone: str) -> Optional[int]:
    """Extract 3-digit area code from a phone number.
    Handles E.164 (+1XXXXXXXXXX) and various domestic formats.
    """
    digits = "".join(c for c in phone if c.isdigit())
    if digits.startswith("1") and len(digits) == 11:
        return int(digits[1:4])
    elif len(digits) == 10:
        return int(digits[:3])
    return None
async def _get_most_used_contact_number(lead_id: str) -> Optional[str]:
    """Query Close API for the most-used outbound number across last 3 calls and last 3 SMS.
    Fetches both activity types in parallel, tallies local_phone by frequency,
    and returns the winner. Falls back to None if no contact history exists.
    """
    settings = get_settings()
    api_key = settings.close_api_key
    if not api_key:
        return None
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            call_task = client.get(
                f"{CLOSE_API_BASE}/activity/call/",
                params={
                    "lead_id": lead_id,
                    "direction": "outbound",
                    "_order_by": "-date_created",
                    "_limit": "3",
                },
                auth=(api_key, ""),
            )
            sms_task = client.get(
                f"{CLOSE_API_BASE}/activity/sms/",
                params={
                    "lead_id": lead_id,
                    "direction": "outbound",
                    "_order_by": "-date_created",
                    "_limit": "3",
                },
                auth=(api_key, ""),
            )
            call_resp, sms_resp = await asyncio.gather(
                call_task, sms_task, return_exceptions=True
            )
        numbers: list[str] = []
        if isinstance(call_resp, Exception):
            logger.warning(
                "Failed to fetch call history for lead %s: %s", lead_id, call_resp
            )
        else:
            try:
                call_resp.raise_for_status()
                for activity in call_resp.json().get("data", []):
                    num = activity.get("local_phone")
                    if num:
                        numbers.append(num)
            except Exception as exc:
                logger.warning("Call history parse error for lead %s: %s", lead_id, exc)
        if isinstance(sms_resp, Exception):
            logger.warning(
                "Failed to fetch SMS history for lead %s: %s", lead_id, sms_resp
            )
        else:
            try:
                sms_resp.raise_for_status()
                for activity in sms_resp.json().get("data", []):
                    num = activity.get("local_phone")
                    if num:
                        numbers.append(num)
            except Exception as exc:
                logger.warning("SMS history parse error for lead %s: %s", lead_id, exc)
        if not numbers:
            return None
        freq = Counter(numbers)
        winner, count = freq.most_common(1)[0]
        logger.info(
            "Most-used contact number for lead %s: %s (used %d/%d times)",
            lead_id, winner, count, len(numbers),
        )
        return winner
    except Exception as exc:
        logger.warning(
            "Failed to query Close contact history for lead %s: %s", lead_id, exc
        )
        return None
async def _match_by_area_code(prospect_phone: str) -> Optional[str]:
    """Find a number from the pool matching the prospect's area code.
    Falls back to geographic region matching if no exact area code match.
    """
    area_code = _extract_area_code(prospect_phone)
    if not area_code:
        logger.warning("Could not extract area code from phone: %s", prospect_phone)
        return None
    # Load phone pool from DB
    async with _get_session_factory()() as session:
        from sqlalchemy import select
        result = await session.execute(
            select(PhoneNumber).where(PhoneNumber.is_active == True)
        )
        pool = result.scalars().all()
    if not pool:
        logger.warning("Phone number pool is empty")
        return None
    # Direct area code match
    for entry in pool:
        entry_codes = json.loads(entry.area_codes_json)
        if area_code in entry_codes:
            logger.info(
                "Area code match: prospect %s → %s (area code %d)",
                prospect_phone, entry.number, area_code,
            )
            return entry.number
    # Geographic fallback — find the region for the prospect's area code
    prospect_state = AREA_CODE_STATE.get(area_code)
    if prospect_state:
        prospect_region = STATE_REGION.get(prospect_state)
        if prospect_region:
            for entry in pool:
                if STATE_REGION.get(entry.state) == prospect_region:
                    logger.info(
                        "Region match: prospect %s (state=%s, region=%s) → %s (state=%s)",
                        prospect_phone, prospect_state, prospect_region,
                        entry.number, entry.state,
                    )
                    return entry.number
    logger.info(
        "No area code or region match for %s (area code %d)",
        prospect_phone, area_code,
    )
    return None
async def resolve_sms_from_number(
    lead_id: str,
    prospect_phone: str,
) -> Optional[str]:
    """Resolve the best outbound SMS number for a prospect.
    Priority:
    1. Most-used local_phone across last 3 outbound calls + last 3 outbound SMS
    2. Area code / geographic match from phone pool
    3. None (caller should skip SMS and log a warning)
    """
    # 1. Check contact history (calls + SMS, frequency-ranked)
    from_number = await _get_most_used_contact_number(lead_id)
    if from_number:
        return from_number
    # 2. Area code match
    from_number = await _match_by_area_code(prospect_phone)
    if from_number:
        return from_number
    # 3. No match — legacy fallback to env var if set
    settings = get_settings()
    if settings.close_sms_from_number:
        logger.warning(
            "No smart route found for lead %s / phone %s — using legacy CLOSE_SMS_FROM_NUMBER",
            lead_id, prospect_phone,
        )
        return settings.close_sms_from_number
    logger.warning(
        "No outbound number resolved for lead %s / phone %s — skipping SMS",
        lead_id, prospect_phone,
    )
    return None
