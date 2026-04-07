"""Google Calendar service — creates/deletes events via OAuth refresh token.

Uses google-auth + google-api-python-client with a stored OAuth refresh token
for server-to-server access to Seb's Google Calendar.

Required env vars:
  GOOGLE_CLIENT_ID       — OAuth 2.0 client ID
  GOOGLE_CLIENT_SECRET   — OAuth 2.0 client secret
  GOOGLE_REFRESH_TOKEN   — OAuth refresh token (from one-time auth flow)
  GOOGLE_CALENDAR_ID     — Calendar ID (default: "primary")

Required OAuth scopes:
  https://www.googleapis.com/auth/calendar

Setup:
1. Create Google Cloud project → enable Calendar API
2. Create OAuth 2.0 Desktop App credentials
3. Run one-time auth flow to get refresh token
4. Set the 4 env vars above
"""

import asyncio
import logging
import traceback
from datetime import datetime, timedelta
from typing import Optional
from zoneinfo import ZoneInfo

from config import get_settings

logger = logging.getLogger("falconconnect.gcal")

# Retry config for transient failures
MAX_RETRIES = 3
RETRY_BASE_DELAY = 1.0  # seconds, exponential backoff

# Default timezone for all calendar events — Seb operates in Arizona (no DST)
DEFAULT_GCAL_TIMEZONE = "America/Phoenix"

# Timezone abbreviation → IANA name map (mirrors close_sms.TZ_MAP)
_TZ_MAP = {
    "ET": "America/New_York",
    "CT": "America/Chicago",
    "MT": "America/Denver",
    "PT": "America/Los_Angeles",
    "AZ": "America/Phoenix",
}


class GCalError(Exception):
    """Raised when a Google Calendar operation fails after retries."""

    pass


def _get_calendar_service():
    """Build and return an authenticated Google Calendar API service.

    Uses OAuth refresh token — no browser flow needed at runtime.
    Token refresh happens automatically via google-auth library.
    Raises RuntimeError if credentials are not configured.
    """
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build

    settings = get_settings()

    if not settings.google_refresh_token:
        raise RuntimeError(
            "GOOGLE_REFRESH_TOKEN not configured — "
            "cannot access Google Calendar"
        )

    if not settings.google_client_id or not settings.google_client_secret:
        raise RuntimeError(
            "GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET must be set — "
            "cannot access Google Calendar"
        )

    credentials = Credentials(
        token=None,
        refresh_token=settings.google_refresh_token,
        token_uri="https://oauth2.googleapis.com/token",
        client_id=settings.google_client_id,
        client_secret=settings.google_client_secret,
        scopes=["https://www.googleapis.com/auth/calendar"],
    )

    service = build("calendar", "v3", credentials=credentials)
    return service


async def _run_in_executor(func):
    """Run a blocking function in the default executor.

    Uses asyncio.get_running_loop() (not deprecated get_event_loop()).
    """
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, func)


async def _retry_gcal_operation(operation_name: str, func):
    """Execute a GCal operation with retry logic (3 attempts, exponential backoff).

    Args:
        operation_name: Human-readable operation name for logging.
        func: Callable that performs the blocking GCal API call.

    Returns: The result from the API call.
    Raises: GCalError if all retries are exhausted.
    """
    last_exc = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            result = await _run_in_executor(func)
            if attempt > 1:
                logger.info(
                    "GCal %s succeeded on attempt %d/%d",
                    operation_name,
                    attempt,
                    MAX_RETRIES,
                )
            return result
        except Exception as exc:
            last_exc = exc
            logger.warning(
                "GCal %s attempt %d/%d failed: %s: %s",
                operation_name,
                attempt,
                MAX_RETRIES,
                type(exc).__name__,
                exc,
            )
            if attempt < MAX_RETRIES:
                delay = RETRY_BASE_DELAY * (2 ** (attempt - 1))
                await asyncio.sleep(delay)

    # All retries exhausted
    error_msg = (
        f"GCal {operation_name} failed after {MAX_RETRIES} attempts. "
        f"Last error: {type(last_exc).__name__}: {last_exc}"
    )
    logger.error(error_msg)
    logger.error("Full traceback:\n%s", traceback.format_exc())
    raise GCalError(error_msg) from last_exc


async def create_appointment_event(
    *,
    summary: str,
    description: str,
    start_dt: datetime,
    duration_minutes: int = 30,
    attendee_email: Optional[str] = None,
    calendar_id: Optional[str] = None,
    tz_choice: Optional[str] = None,
) -> str:
    """Create a Google Calendar event for an appointment.

    Args:
        summary: Event title (e.g. "Call with John Smith")
        description: Event description/notes
        start_dt: Appointment start time (timezone-aware)
        duration_minutes: Event duration (default 30 min)
        attendee_email: Optional attendee email for Close linking
        calendar_id: Google Calendar ID (defaults to settings)
        tz_choice: Lead timezone abbreviation (ET/CT/MT/PT/AZ). Falls back
                   to America/Phoenix if omitted or unrecognised.

    Returns: Google Calendar event ID on success.
    Raises: GCalError on failure (after 3 retries).
    """
    settings = get_settings()
    cal_id = calendar_id or settings.google_calendar_id
    tz_name = _TZ_MAP.get((tz_choice or "").strip().upper(), DEFAULT_GCAL_TIMEZONE)

    end_dt = start_dt + timedelta(minutes=duration_minutes)

    event_body = {
        "summary": summary,
        "description": description,
        "start": {
            "dateTime": start_dt.isoformat(),
            "timeZone": tz_name,
        },
        "end": {
            "dateTime": end_dt.isoformat(),
            "timeZone": tz_name,
        },
        "reminders": {
            "useDefault": False,
            "overrides": [
                {"method": "popup", "minutes": 5},
            ],
        },
    }

    # Attendees intentionally omitted — adding a dummy email (lead-xxx@appt.invalid)
    # causes Google to generate undeliverable bounce emails to the calendar owner.
    # The event description already contains the Close lead URL for lookup.
    # attendee_email arg kept for API compatibility but not used.

    service = _get_calendar_service()

    def _insert():
        return (
            service.events()
            .insert(
                calendarId=cal_id,
                body=event_body,
                sendUpdates="none",
            )
            .execute()
        )

    result = await _retry_gcal_operation("create_event", _insert)
    event_id = result.get("id")
    logger.info(
        "GCal event created: %s (%s) on calendar %s",
        event_id,
        summary,
        cal_id,
    )
    return event_id


async def update_appointment_event(
    event_id: str,
    *,
    summary: str | None = None,
    description: str | None = None,
    start_dt: datetime | None = None,
    duration_minutes: int = 30,
    calendar_id: str | None = None,
) -> bool:
    """Update an existing Google Calendar event.

    Only updates the fields that are provided (non-None).
    Returns True on success.
    Raises: GCalError on failure (after 3 retries).
    """
    settings = get_settings()
    cal_id = calendar_id or settings.google_calendar_id

    event_body: dict = {}

    if summary is not None:
        event_body["summary"] = summary

    if description is not None:
        event_body["description"] = description

    if start_dt is not None:
        end_dt = start_dt + timedelta(minutes=duration_minutes)
        event_body["start"] = {
            "dateTime": start_dt.isoformat(),
            "timeZone": DEFAULT_GCAL_TIMEZONE,
        }
        event_body["end"] = {
            "dateTime": end_dt.isoformat(),
            "timeZone": DEFAULT_GCAL_TIMEZONE,
        }

    if not event_body:
        logger.info("No fields to update for GCal event %s", event_id)
        return True

    service = _get_calendar_service()

    def _patch():
        return (
            service.events()
            .patch(
                calendarId=cal_id,
                eventId=event_id,
                body=event_body,
                sendUpdates="none",
            )
            .execute()
        )

    await _retry_gcal_operation(f"update_event({event_id})", _patch)
    logger.info("GCal event updated: %s", event_id)
    return True


async def delete_event(
    event_id: str,
    calendar_id: Optional[str] = None,
) -> bool:
    """Delete a Google Calendar event.

    Returns True on success (including already-deleted).
    Raises: GCalError on non-404/410 failures (after 3 retries).
    """
    settings = get_settings()
    cal_id = calendar_id or settings.google_calendar_id

    service = _get_calendar_service()

    def _delete():
        return (
            service.events()
            .delete(calendarId=cal_id, eventId=event_id, sendUpdates="none")
            .execute()
        )

    try:
        await _retry_gcal_operation(f"delete_event({event_id})", _delete)
        logger.info("GCal event deleted: %s", event_id)
        return True
    except GCalError as exc:
        # 404/410 = already deleted — treat as success
        error_str = str(exc)
        if "404" in error_str or "410" in error_str:
            logger.info("GCal event %s already deleted (404/410)", event_id)
            return True
        raise


async def test_connection() -> dict:
    """Test GCal API connection — used by health check and startup validator.

    Returns dict with:
      - healthy: bool
      - calendar_count: int (if healthy)
      - primary_calendar: str (if healthy)
      - error: str (if unhealthy)
    """
    try:
        service = _get_calendar_service()
        cals = await _run_in_executor(
            lambda: service.calendarList().list(maxResults=5).execute()
        )
        items = cals.get("items", [])
        primary = next(
            (c.get("summary", c.get("id")) for c in items if c.get("primary")),
            items[0].get("summary", "unknown") if items else "none",
        )
        return {
            "healthy": True,
            "calendar_count": len(items),
            "primary_calendar": primary,
        }
    except Exception as exc:
        return {
            "healthy": False,
            "error": f"{type(exc).__name__}: {exc}",
            "traceback": traceback.format_exc(),
        }
