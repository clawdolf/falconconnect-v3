"""Google Calendar service — creates/deletes events via Service Account.

Uses google-auth + google-api-python-client with a service account
for server-to-server auth (no OAuth browser flow needed).

Setup:
1. Create Google Cloud project → enable Calendar API
2. Create Service Account → download JSON key
3. Share Seb's Google Calendar with service account email (editor)
4. Set GOOGLE_SERVICE_ACCOUNT_JSON env var = JSON key contents
"""

import json
import logging
from datetime import datetime, timedelta
from typing import Optional

from config import get_settings

logger = logging.getLogger("falconconnect.gcal")


def _get_calendar_service():
    """Build and return an authenticated Google Calendar API service.

    Raises RuntimeError if credentials are not configured.
    """
    from google.oauth2 import service_account
    from googleapiclient.discovery import build

    settings = get_settings()
    sa_json = settings.google_service_account_json

    if not sa_json:
        raise RuntimeError(
            "GOOGLE_SERVICE_ACCOUNT_JSON not configured — "
            "cannot access Google Calendar"
        )

    try:
        creds_info = json.loads(sa_json)
    except json.JSONDecodeError as exc:
        raise RuntimeError(
            f"GOOGLE_SERVICE_ACCOUNT_JSON is not valid JSON: {exc}"
        ) from exc

    credentials = service_account.Credentials.from_service_account_info(
        creds_info,
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
