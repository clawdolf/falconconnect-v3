"""Close.com SMS scheduling service for appointment reminders.

Handles:
- Immediate confirmation SMS on booking
- Scheduled 24hr and 1hr reminder SMS via Close's date_scheduled API
- Cancellation of scheduled SMS on rebooking
"""

import logging
from datetime import datetime, timedelta
from typing import Optional

import httpx
import pytz

from config import get_settings

logger = logging.getLogger("falconconnect.close_sms")

BASE_URL = "https://api.close.com/api/v1"

# Close custom activity field IDs for Book Appointment
CF_APPOINTMENT_DATETIME = "cf_iiDP2BjqqEApsTl1uGQqbzw2cWm5Le8r3wTuUC8uc5Z"
CF_APPOINTMENT_NOTES = "cf_WEM8v7zGSnCDPIEQuxNmdct5l5i19kCRoPCX5BexLqa"
CF_APPOINTMENT_TIMEZONE = "cf_mqWOudG1Apd6FdrzP2qZqC1qUgx0pvGLKg4ZZgFsmn7"

# Timezone choice mapping
TZ_MAP = {
    "ET": "America/New_York",
    "CT": "America/Chicago",
    "MT": "America/Denver",
    "PT": "America/Los_Angeles",
    "AZ": "America/Phoenix",
}
TZ_LABEL_MAP = {
    "ET": "ET",
    "CT": "CT",
    "MT": "MT",
    "PT": "PT",
    "AZ": "AZ",
}
DEFAULT_TZ = "America/Phoenix"
DEFAULT_TZ_LABEL = "AZ"


def _resolve_timezone(tz_choice: Optional[str]) -> tuple[str, str]:
    """Resolve a timezone choice to (pytz timezone name, display label).

    Returns (tz_name, tz_label) — e.g. ("America/New_York", "ET").
    Falls back to America/Phoenix / AZ if empty or unknown.
    """
    if not tz_choice:
        return DEFAULT_TZ, DEFAULT_TZ_LABEL
    choice = tz_choice.strip().upper()
    tz_name = TZ_MAP.get(choice, DEFAULT_TZ)
    tz_label = TZ_LABEL_MAP.get(choice, DEFAULT_TZ_LABEL)
    return tz_name, tz_label


def _format_appointment_time(
    appointment_dt: datetime,
    tz_name: str,
    tz_label: str,
) -> tuple[str, str]:
    """Format appointment datetime for SMS messages.

    Returns (time_str, day_str) — e.g. ("2:00 PM ET", "Tuesday, March 18th").
    """
    tz = pytz.timezone(tz_name)
    local_dt = appointment_dt.astimezone(tz)

    # Time: "2:00 PM ET"
    time_str = f"{local_dt.strftime('%-I:%M %p')} {tz_label}"

    # Day: "Tuesday, March 18th"
    day = local_dt.day
    if 11 <= day <= 13:
        suffix = "th"
    else:
        suffix = {1: "st", 2: "nd", 3: "rd"}.get(day % 10, "th")
    day_str = f"{local_dt.strftime('%A, %B')} {day}{suffix}"

    return time_str, day_str


# SMS templates
def _sms_confirmation(first_name: str, day_str: str, time_str: str) -> str:
    return (
        f"Hi {first_name}, this is Seb from Falcon Financial. "
        f"Just confirming our appointment on {day_str} at {time_str}. "
        f"Looking forward to speaking with you! Reply STOP to opt out."
    )


def _sms_24hr_reminder(first_name: str, time_str: str) -> str:
    return (
        f"Hi {first_name}, just a reminder — we have an appointment "
        f"tomorrow at {time_str}. Talk soon! "
        f"- Seb, Falcon Financial. Reply STOP to opt out."
    )


def _sms_1hr_reminder(first_name: str, time_str: str) -> str:
    return (
        f"Hi {first_name}, our appointment is in about an hour at {time_str}. "
        f"Talk soon! - Seb. Reply STOP to opt out."
    )


async def send_sms(
    *,
    lead_id: str,
    contact_id: str,
    phone: str,
    text: str,
    status: str = "inbox",
    date_scheduled: Optional[str] = None,
) -> Optional[str]:
    """Send or schedule an SMS via Close.com API.

    Args:
        lead_id: Close lead ID
        contact_id: Close contact ID
        phone: Recipient phone number (E.164)
        text: SMS message body
        status: "inbox" for immediate, "scheduled" for future
        date_scheduled: ISO 8601 datetime for scheduled SMS

    Returns: SMS activity ID on success, None on failure.
    """
    settings = get_settings()
    api_key = settings.close_api_key
    from_number = settings.close_sms_from_number

    if not api_key:
        logger.error("CLOSE_API_KEY not configured — cannot send SMS")
        return None
    if not from_number:
        logger.error("CLOSE_SMS_FROM_NUMBER not configured — cannot send SMS")
        return None

    payload = {
        "lead_id": lead_id,
        "contact_id": contact_id,
        "local_phone": from_number,
        "remote_phone": phone,
        "text": text,
        "status": status,
        "direction": "outbound",
    }

    if status == "scheduled" and date_scheduled:
        payload["date_scheduled"] = date_scheduled

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                f"{BASE_URL}/activity/sms/",
                json=payload,
                auth=(api_key, ""),
            )
            resp.raise_for_status()
            sms_data = resp.json()
            sms_id = sms_data.get("id")
            logger.info(
                "SMS %s (status=%s) to %s: %s",
                sms_id,
                status,
                phone,
                text[:60],
            )
            return sms_id
    except httpx.HTTPStatusError as exc:
        logger.error(
            "Close SMS API error %s: %s",
            exc.response.status_code,
            exc.response.text[:300],
        )
        return None
    except Exception as exc:
        logger.error("Close SMS send failed: %s", exc)
        return None


async def cancel_scheduled_sms(sms_id: str) -> bool:
    """Cancel a scheduled SMS by deleting it via Close API.

    Returns True on success, False on failure.
    """
    settings = get_settings()
    api_key = settings.close_api_key

    if not api_key or not sms_id:
        return False

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.delete(
                f"{BASE_URL}/activity/sms/{sms_id}/",
                auth=(api_key, ""),
            )
            if resp.status_code in (200, 204):
                logger.info("Cancelled scheduled SMS: %s", sms_id)
                return True
            else:
                logger.warning(
                    "Failed to cancel SMS %s: %s %s",
                    sms_id,
                    resp.status_code,
                    resp.text[:200],
                )
                return False
    except Exception as exc:
        logger.error("Cancel SMS %s failed: %s", sms_id, exc)
        return False


async def schedule_appointment_sms(
    *,
    lead_id: str,
    contact_id: str,
    phone: str,
    first_name: str,
    appointment_dt: datetime,
    tz_choice: Optional[str] = None,
) -> dict[str, Optional[str]]:
    """Schedule all three SMS messages for an appointment.

    Returns dict with keys: confirmation, reminder_24hr, reminder_1hr
    Each value is the SMS activity ID or None on failure.
    """
    tz_name, tz_label = _resolve_timezone(tz_choice)
    time_str, day_str = _format_appointment_time(appointment_dt, tz_name, tz_label)

    results: dict[str, Optional[str]] = {
        "confirmation": None,
        "reminder_24hr": None,
        "reminder_1hr": None,
    }

    # 1. Confirmation SMS — send immediately
    confirmation_text = _sms_confirmation(first_name, day_str, time_str)
    results["confirmation"] = await send_sms(
        lead_id=lead_id,
        contact_id=contact_id,
        phone=phone,
        text=confirmation_text,
        status="inbox",
    )

    # 2. 24hr reminder — scheduled
    reminder_24hr_dt = appointment_dt - timedelta(hours=24)
    if reminder_24hr_dt > datetime.now(pytz.utc):
        reminder_24hr_text = _sms_24hr_reminder(first_name, time_str)
        results["reminder_24hr"] = await send_sms(
            lead_id=lead_id,
            contact_id=contact_id,
            phone=phone,
            text=reminder_24hr_text,
            status="scheduled",
            date_scheduled=reminder_24hr_dt.isoformat(),
        )
    else:
        logger.info(
            "Skipping 24hr reminder — appointment in less than 24hrs (lead=%s)",
            lead_id,
        )

    # 3. 1hr reminder — scheduled
    reminder_1hr_dt = appointment_dt - timedelta(hours=1)
    if reminder_1hr_dt > datetime.now(pytz.utc):
        reminder_1hr_text = _sms_1hr_reminder(first_name, time_str)
        results["reminder_1hr"] = await send_sms(
            lead_id=lead_id,
            contact_id=contact_id,
            phone=phone,
            text=reminder_1hr_text,
            status="scheduled",
            date_scheduled=reminder_1hr_dt.isoformat(),
        )
    else:
        logger.info(
            "Skipping 1hr reminder — appointment in less than 1hr (lead=%s)",
            lead_id,
        )

    return results
