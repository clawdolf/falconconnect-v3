"""Google Calendar service — creates/deletes events via OAuth refresh token.

Uses google-auth + google-api-python-client with a stored OAuth refresh token
for server-to-server access to Seb's Google Calendar.

Setup:
1. Create Google Cloud project → enable Calendar API
2. Create OAuth 2.0 Desktop App credentials
3. Run one-time auth flow to get refresh token
4. Set GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET, GOOGLE_REFRESH_TOKEN env vars
"""

import logging
from datetime import datetime, timedelta
from typing import Optional

from config import get_settings

logger = logging.getLogger("falconconnect.gcal")


def _get_calendar_service():
    """Build and return an authenticated Google Calendar API service.

    Uses OAuth refresh token — no browser flow needed at runtime.
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


async def create_appointment_event(
    *,
    summary: str,
    description: str,
    start_dt: datetime,
    duration_minutes: int = 30,
    attendee_email: Optional[str] = None,
    calendar_id: Optional[str] = None,
) -> Optional[str]:
    """Create a Google Calendar event for an appointment.

    Args:
        summary: Event title (e.g. "Call with John Smith")
        description: Event description/notes
        start_dt: Appointment start time (timezone-aware)
        duration_minutes: Event duration (default 30 min)
        attendee_email: Dummy email to add as attendee for Close linking
        calendar_id: Google Calendar ID (defaults to settings)

    Returns: Google Calendar event ID on success, None on failure.
    """
    import asyncio

    settings = get_settings()
    cal_id = calendar_id or settings.google_calendar_id

    end_dt = start_dt + timedelta(minutes=duration_minutes)

    event_body = {
        "summary": summary,
        "description": description,
        "start": {
            "dateTime": start_dt.isoformat(),
            "timeZone": "UTC",
        },
        "end": {
            "dateTime": end_dt.isoformat(),
            "timeZone": "UTC",
        },
        "reminders": {
            "useDefault": False,
            "overrides": [
                {"method": "popup", "minutes": 5},
            ],
        },
    }

    if attendee_email:
        event_body["attendees"] = [
            {"email": attendee_email, "responseStatus": "accepted"},
        ]
        # Don't send invitation emails to the dummy address
        send_updates = "none"
    else:
        send_updates = "none"

    try:
        service = _get_calendar_service()
        # google-api-python-client is synchronous — run in executor
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(
            None,
            lambda: service.events()
            .insert(
                calendarId=cal_id,
                body=event_body,
                sendUpdates=send_updates,
            )
            .execute(),
        )
        event_id = result.get("id")
        logger.info(
            "GCal event created: %s (%s) on calendar %s",
            event_id,
            summary,
            cal_id,
        )
        return event_id
    except Exception as exc:
        logger.error("Failed to create GCal event: %s", exc)
        return None


async def delete_event(
    event_id: str,
    calendar_id: Optional[str] = None,
) -> bool:
    """Delete a Google Calendar event.

    Returns True on success, False on failure.
    """
    import asyncio

    settings = get_settings()
    cal_id = calendar_id or settings.google_calendar_id

    try:
        service = _get_calendar_service()
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(
            None,
            lambda: service.events()
            .delete(calendarId=cal_id, eventId=event_id, sendUpdates="none")
            .execute(),
        )
        logger.info("GCal event deleted: %s", event_id)
        return True
    except Exception as exc:
        # 404/410 = already deleted — treat as success
        error_str = str(exc)
        if "404" in error_str or "410" in error_str:
            logger.info("GCal event %s already deleted (404/410)", event_id)
            return True
        logger.error("Failed to delete GCal event %s: %s", event_id, exc)
        return False
