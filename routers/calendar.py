"""iCal feed endpoints — two separate feeds for appointments and follow-ups.

/api/calendar/appointments.ics — timed appointment events only
/api/calendar/followups.ics    — all-day follow-up events only

Both secured by the same CALENDAR_SECRET query param.
"""

import logging

from fastapi import APIRouter, Query, Response

from services.calendar import build_appointments_feed, build_followups_feed
from services.notion import get_upcoming_appointments, get_upcoming_followups
from utils.auth import verify_calendar_token

logger = logging.getLogger("falconconnect.calendar")

router = APIRouter()


@router.get("/appointments.ics")
async def appointments_feed(token: str = Query(..., description="Calendar feed secret token")):
    """iCal feed of upcoming appointments only.

    1-hour timed events with 60-min and 24-hour VALARM reminders.
    Calendar name: "FC Appointments — Seb"
    """
    verify_calendar_token(token)

    try:
        pages = await get_upcoming_appointments(days=90)
        logger.info("Appointments feed: %d events", len(pages))
    except Exception as exc:
        logger.error("Failed to query Notion for appointments: %s", exc)
        return Response(content="Error fetching appointment data", status_code=502, media_type="text/plain")

    return Response(
        content=build_appointments_feed(pages),
        media_type="text/calendar",
        headers={
            "Content-Disposition": "inline; filename=appointments.ics",
            "Cache-Control": "no-cache, no-store, must-revalidate",
        },
    )


@router.get("/followups.ics")
async def followups_feed(token: str = Query(..., description="Calendar feed secret token")):
    """iCal feed of upcoming follow-ups only.

    All-day events with 8am morning VALARM reminder.
    Calendar name: "FC Follow-Ups — Seb"
    """
    verify_calendar_token(token)

    try:
        pages = await get_upcoming_followups(days=90)
        logger.info("Follow-ups feed: %d events", len(pages))
    except Exception as exc:
        logger.error("Failed to query Notion for follow-ups: %s", exc)
        return Response(content="Error fetching follow-up data", status_code=502, media_type="text/plain")

    return Response(
        content=build_followups_feed(pages),
        media_type="text/calendar",
        headers={
            "Content-Disposition": "inline; filename=followups.ics",
            "Cache-Control": "no-cache, no-store, must-revalidate",
        },
    )
