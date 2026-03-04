"""iCal feed endpoint — serves .ics calendar from Notion appointment data."""

import logging

from fastapi import APIRouter, Query, Response

from services.calendar import build_ical_feed
from services.notion import query_upcoming_appointments
from utils.auth import verify_calendar_token

logger = logging.getLogger("falconconnect.calendar")

router = APIRouter()


@router.get("/seb.ics")
async def ical_feed(token: str = Query(..., description="Calendar feed secret token")):
    """Serve an iCal (.ics) feed of upcoming appointments and follow-ups.

    Reads from Notion, generates a valid iCalendar file with:
    - Appointment events (1-hour, with 60-min and 24-hour alarms)
    - Follow-up events (all-day, with 8am morning alarm)

    Secured by a shared secret token passed as a query parameter.
    """
    verify_calendar_token(token)

    try:
        pages = await query_upcoming_appointments(days=90)
        logger.info("Calendar feed: %d pages with upcoming dates", len(pages))
    except Exception as exc:
        logger.error("Failed to query Notion for calendar data: %s", exc)
        return Response(
            content="Error fetching calendar data",
            status_code=502,
            media_type="text/plain",
        )

    ical_str = build_ical_feed(pages)

    return Response(
        content=ical_str,
        media_type="text/calendar",
        headers={
            "Content-Disposition": "inline; filename=seb.ics",
            "Cache-Control": "no-cache, no-store, must-revalidate",
        },
    )
