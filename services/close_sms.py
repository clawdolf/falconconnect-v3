"""Close.com SMS scheduling service for appointment reminders.

Handles:
- Immediate confirmation SMS on booking
- Scheduled 24hr and 1hr reminder SMS via Close's date_scheduled API
- Cancellation of scheduled SMS on rebooking
- Template loading from DB (editable via admin UI)
- Smart number routing (call history → area code → geographic fallback)
"""

import logging
from datetime import datetime, timedelta, time
from typing import Optional
from zoneinfo import ZoneInfo

import httpx
import pytz
from sqlalchemy import select

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

# ---------------------------------------------------------------------------
# TCPA Quiet Hours — proactive SMS reminders only (confirmations exempt)
# Federal TCPA: no automated messages before 8am or after 9pm *recipient* local time.
# Violations: $500-$1,500 per message.
# ---------------------------------------------------------------------------

TCPA_QUIET_START = time(21, 0)  # 9:00 PM — no messages after this
TCPA_QUIET_END = time(8, 0)     # 8:00 AM — no messages before this

# Map lead's US state abbreviation → IANA timezone for quiet hours calculation.
# Covers all states in Seb's current market footprint.
STATE_TIMEZONES: dict[str, str] = {
    "AZ": "America/Phoenix",
    "FL": "America/New_York",
    "ID": "America/Boise",
    "KS": "America/Chicago",
    "ME": "America/New_York",
    "MT": "America/Denver",
    "NC": "America/New_York",
    "OR": "America/Los_Angeles",
    "PA": "America/New_York",
    "TX": "America/Chicago",
}


def _enforce_tcpa_quiet_hours(
    send_at_utc: datetime,
    lead_state: Optional[str],
    reminder_type: str,
) -> datetime:
    """Shift a scheduled send time to comply with TCPA quiet hours (8am-9pm).

    If the computed send time falls outside 8am-9pm in the lead's local
    timezone, shifts it to the nearest compliant window:
      - Before 8am → shift to 8:00am same day
      - After 9pm → shift to 8:00am next day

    Args:
        send_at_utc: The originally computed send time (timezone-aware).
        lead_state: Two-letter US state abbreviation (e.g. "AZ", "TX").
        reminder_type: "1hr" or "24hr" — for logging only.

    Returns: Adjusted send time (timezone-aware, may be unchanged).
    """
    if not lead_state:
        # No state info — default to Arizona (Seb's home market)
        lead_tz_name = "America/Phoenix"
    else:
        lead_tz_name = STATE_TIMEZONES.get(
            lead_state.strip().upper(), "America/Phoenix"
        )

    lead_tz = ZoneInfo(lead_tz_name)
    local_send = send_at_utc.astimezone(lead_tz)
    local_time = local_send.time()

    if TCPA_QUIET_END <= local_time < TCPA_QUIET_START:
        # Within allowed window — no adjustment needed
        return send_at_utc

    # Outside quiet hours — shift to 8:00am
    if local_time < TCPA_QUIET_END:
        # Before 8am same day → shift to 8:00am same day
        adjusted_local = local_send.replace(
            hour=8, minute=0, second=0, microsecond=0
        )
    else:
        # After 9pm → shift to 8:00am next day
        next_day = local_send.date() + timedelta(days=1)
        adjusted_local = datetime.combine(
            next_day, TCPA_QUIET_END, tzinfo=lead_tz
        )

    logger.info(
        "TCPA quiet hours: %s reminder shifted %s → %s (lead state=%s, tz=%s)",
        reminder_type,
        local_send.strftime("%I:%M %p %Z"),
        adjusted_local.strftime("%I:%M %p %Z"),
        lead_state or "unknown",
        lead_tz_name,
    )

    return adjusted_local


# Default SMS templates — used if DB has no entries yet
DEFAULT_TEMPLATES: dict[str, str] = {
    "confirmation": (
        "Hi {{name}}, your appointment with Seb at Falcon Financial is confirmed "
        "for {{date}} at {{time}} {{timezone}}."
    ),
    "reminder_24hr": (
        "Hey {{name}}, just a reminder — you have an appointment tomorrow "
        "at {{time}} {{timezone}}. Talk soon."
    ),
    "reminder_1hr": (
        "Hey {{name}}, your appointment is in 1 hour at {{time}} {{timezone}}. "
        "See you soon."
    ),
}


def _resolve_timezone(tz_choice: Optional[str]) -> tuple[str, str]:
    """Resolve a timezone choice to (pytz timezone name, display label).

    Returns (tz_name, tz_label) — e.g. ("America/New_York", "ET").
    Falls back to America/Phoenix / AZ if empty or unknown.

    Handles Close dropdown values like "AZ (MST, no DST)" or "ET (Eastern)"
    by extracting the abbreviation before the first space or parenthesis.
    """
    if not tz_choice:
        return DEFAULT_TZ, DEFAULT_TZ_LABEL
    # Extract the timezone abbreviation — take text before first space or paren
    # e.g. "AZ (MST, no DST)" → "AZ", "ET (Eastern)" → "ET"
    choice = tz_choice.strip().split("(")[0].strip().split()[0].upper()
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


# ---------------------------------------------------------------------------
# Template loading from DB
# ---------------------------------------------------------------------------

async def _load_template(template_key: str) -> str:
    """Load an SMS template from the DB. Falls back to hardcoded default."""
    try:
        from db.database import _get_session_factory
        from db.models import SmsTemplate

        async with _get_session_factory()() as session:
            result = await session.execute(
                select(SmsTemplate).where(SmsTemplate.template_key == template_key)
            )
            tpl = result.scalar_one_or_none()
            if tpl:
                return tpl.body
    except Exception as exc:
        logger.warning("Failed to load SMS template '%s' from DB: %s", template_key, exc)

    return DEFAULT_TEMPLATES.get(template_key, "")


def _render_template(
    template: str,
    *,
    name: str = "",
    date: str = "",
    time: str = "",
    timezone: str = "",
    phone: str = "",
) -> str:
    """Render merge fields in an SMS template."""
    return (
        template
        .replace("{{name}}", name)
        .replace("{{date}}", date)
        .replace("{{time}}", time)
        .replace("{{timezone}}", timezone)
        .replace("{{phone}}", phone)
    )


async def _sms_confirmation(first_name: str, day_str: str, time_str: str, tz_label: str, phone: str = "") -> str:
    template = await _load_template("confirmation")
    return _render_template(template, name=first_name, date=day_str, time=time_str, timezone=tz_label, phone=phone)


async def _sms_24hr_reminder(first_name: str, time_str: str, tz_label: str, phone: str = "") -> str:
    template = await _load_template("reminder_24hr")
    return _render_template(template, name=first_name, time=time_str, timezone=tz_label, phone=phone)


async def _sms_1hr_reminder(first_name: str, time_str: str, tz_label: str, phone: str = "") -> str:
    template = await _load_template("reminder_1hr")
    return _render_template(template, name=first_name, time=time_str, timezone=tz_label, phone=phone)


async def send_sms(
    *,
    lead_id: str,
    contact_id: str,
    phone: str,
    text: str,
    from_number: Optional[str] = None,
    status: str = "inbox",
    date_scheduled: Optional[str] = None,
) -> Optional[str]:
    """Send or schedule an SMS via Close.com API.

    Args:
        lead_id: Close lead ID
        contact_id: Close contact ID
        phone: Recipient phone number (E.164)
        text: SMS message body
        from_number: Outbound number (resolved by caller via smart routing)
        status: "inbox" for immediate, "scheduled" for future
        date_scheduled: ISO 8601 datetime for scheduled SMS

    Returns: SMS activity ID on success, None on failure.
    """
    settings = get_settings()
    api_key = settings.close_api_key

    if not api_key:
        logger.error("CLOSE_API_KEY not configured — cannot send SMS")
        return None
    if not from_number:
        logger.error("No from_number provided — cannot send SMS for lead %s", lead_id)
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
                "SMS %s (status=%s) from %s to %s: %s",
                sms_id,
                status,
                from_number,
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
    lead_state: Optional[str] = None,
) -> dict[str, Optional[str]]:
    """Schedule all three SMS messages for an appointment.

    Uses smart number routing (call history → area code → geographic fallback)
    and loads templates from DB.

    Returns dict with keys: confirmation, reminder_24hr, reminder_1hr
    Each value is the SMS activity ID or None on failure.
    """
    from services.sms_routing import resolve_sms_from_number

    tz_name, tz_label = _resolve_timezone(tz_choice)
    time_str, day_str = _format_appointment_time(appointment_dt, tz_name, tz_label)

    results: dict[str, Optional[str]] = {
        "confirmation": None,
        "reminder_24hr": None,
        "reminder_1hr": None,
    }

    # Resolve outbound number via smart routing
    from_number = await resolve_sms_from_number(lead_id, phone)
    if not from_number:
        logger.warning(
            "No outbound number resolved for lead %s / phone %s — skipping all SMS",
            lead_id,
            phone,
        )
        return results

    logger.info(
        "SMS routing resolved: lead=%s prospect=%s → from=%s",
        lead_id,
        phone,
        from_number,
    )

    # 1. Confirmation SMS — send immediately
    confirmation_text = await _sms_confirmation(first_name, day_str, time_str, tz_label, phone)
    results["confirmation"] = await send_sms(
        lead_id=lead_id,
        contact_id=contact_id,
        phone=phone,
        text=confirmation_text,
        from_number=from_number,
        status="inbox",
    )

    # 2. 24hr reminder — scheduled (TCPA quiet hours enforced)
    reminder_24hr_dt = appointment_dt - timedelta(hours=24)
    if reminder_24hr_dt > datetime.now(pytz.utc):
        # Enforce TCPA: if 24hr reminder lands outside 8am-9pm lead local → shift
        reminder_24hr_dt = _enforce_tcpa_quiet_hours(
            reminder_24hr_dt, lead_state, "24hr"
        )
        reminder_24hr_text = await _sms_24hr_reminder(first_name, time_str, tz_label, phone)
        results["reminder_24hr"] = await send_sms(
            lead_id=lead_id,
            contact_id=contact_id,
            phone=phone,
            text=reminder_24hr_text,
            from_number=from_number,
            status="scheduled",
            date_scheduled=reminder_24hr_dt.isoformat(),
        )
    else:
        logger.info(
            "Skipping 24hr reminder — appointment in less than 24hrs (lead=%s)",
            lead_id,
        )

    # 3. 1hr reminder — scheduled (TCPA quiet hours enforced)
    reminder_1hr_dt = appointment_dt - timedelta(hours=1)
    if reminder_1hr_dt > datetime.now(pytz.utc):
        # Enforce TCPA: if 1hr reminder lands outside 8am-9pm lead local → shift
        reminder_1hr_dt = _enforce_tcpa_quiet_hours(
            reminder_1hr_dt, lead_state, "1hr"
        )
        reminder_1hr_text = await _sms_1hr_reminder(first_name, time_str, tz_label, phone)
        results["reminder_1hr"] = await send_sms(
            lead_id=lead_id,
            contact_id=contact_id,
            phone=phone,
            text=reminder_1hr_text,
            from_number=from_number,
            status="scheduled",
            date_scheduled=reminder_1hr_dt.isoformat(),
        )
    else:
        logger.info(
            "Skipping 1hr reminder — appointment in less than 1hr (lead=%s)",
            lead_id,
        )

    return results
