"""iCal generation service — builds .ics feed from Notion appointment data."""

import logging
from datetime import datetime, timedelta
from typing import Any, Dict, List

import pytz
from icalendar import Calendar, Event, Alarm

logger = logging.getLogger("falconconnect.calendar")

PHOENIX_TZ = pytz.timezone("America/Phoenix")


def build_ical_feed(pages: List[Dict[str, Any]]) -> str:
    """Build a valid iCalendar string from Notion page results.

    Each page may have an Appointment Date (timed event) and/or
    a Follow-Up Date (all-day event).
    """
    cal = Calendar()
    cal.add("prodid", "-//FalconConnect v3//falconfinancial.org//")
    cal.add("version", "2.0")
    cal.add("calscale", "GREGORIAN")
    cal.add("method", "PUBLISH")
    cal.add("x-wr-calname", "FalconConnect — Seb")
    cal.add("x-wr-timezone", "America/Phoenix")

    for page in pages:
        props = page.get("properties", {})
        page_id = page.get("id", "unknown")

        first_name = _rich_text(props.get("Name", {}))
        phone = _phone(props.get("Phone", {}))
        status = _select(props.get("Status", {}))
        lage = _number(props.get("LAge", {}))
        notes = _rich_text(props.get("Notes", {}))

        # --- Appointment event ---
        appt_date = _date_value(props.get("Appointment Date", {}))
        if appt_date:
            event = Event()
            event.add("uid", f"appt-{page_id}@falconconnect")
            event.add("summary", f"{first_name} — {phone}" if phone else first_name)
            event.add("dtstart", _to_phoenix_dt(appt_date))
            event.add("duration", timedelta(hours=1))
            event.add(
                "description",
                f"Status: {status or 'N/A'} | LAge: {lage or 'N/A'} months | Notes: {notes or 'N/A'}",
            )
            event.add("dtstamp", datetime.now(PHOENIX_TZ))

            # 60-min reminder
            alarm60 = Alarm()
            alarm60.add("action", "DISPLAY")
            alarm60.add("trigger", timedelta(minutes=-60))
            alarm60.add("description", f"Appointment in 1 hour: {first_name}")
            event.add_component(alarm60)

            # 24-hour reminder
            alarm24 = Alarm()
            alarm24.add("action", "DISPLAY")
            alarm24.add("trigger", timedelta(hours=-24))
            alarm24.add("description", f"Appointment tomorrow: {first_name}")
            event.add_component(alarm24)

            cal.add_component(event)

        # --- Follow-up event ---
        followup_date = _date_value(props.get("Follow-Up Date", {}))
        if followup_date:
            event = Event()
            event.add("uid", f"followup-{page_id}@falconconnect")
            event.add("summary", f"Follow Up — {first_name}")

            fu_dt = _parse_date_only(followup_date)
            if fu_dt:
                event.add("dtstart", fu_dt)  # all-day event
            else:
                event.add("dtstart", _to_phoenix_dt(followup_date))
                event.add("duration", timedelta(minutes=30))

            event.add("dtstamp", datetime.now(PHOENIX_TZ))

            # Morning-of reminder at 8am
            alarm_morning = Alarm()
            alarm_morning.add("action", "DISPLAY")
            alarm_morning.add("trigger", timedelta(hours=-8))  # 8am if event is all-day
            alarm_morning.add("description", f"Follow up today: {first_name}")
            event.add_component(alarm_morning)

            cal.add_component(event)

    return cal.to_ical().decode("utf-8")


# --- Property extractors ---


def _rich_text(prop: Dict[str, Any]) -> str:
    """Extract plain text from a Notion rich_text or title property."""
    for key in ("title", "rich_text"):
        items = prop.get(key, [])
        if items:
            return "".join(item.get("plain_text", "") for item in items)
    return ""


def _phone(prop: Dict[str, Any]) -> str:
    return prop.get("phone_number", "") or ""


def _select(prop: Dict[str, Any]) -> str:
    sel = prop.get("select")
    if sel:
        return sel.get("name", "")
    return ""


def _number(prop: Dict[str, Any]) -> str:
    val = prop.get("number")
    return str(val) if val is not None else ""


def _date_value(prop: Dict[str, Any]) -> str:
    """Extract the start date string from a Notion date property."""
    date_obj = prop.get("date")
    if date_obj:
        return date_obj.get("start", "")
    return ""


def _to_phoenix_dt(date_str: str) -> datetime:
    """Parse an ISO date/datetime string into a Phoenix-timezone datetime."""
    from dateutil import parser as dtparser

    dt = dtparser.parse(date_str)
    if dt.tzinfo is None:
        dt = PHOENIX_TZ.localize(dt)
    return dt.astimezone(PHOENIX_TZ)


def _parse_date_only(date_str: str):
    """If the string is a date-only (no time component), return a date object."""
    from datetime import date

    if len(date_str) == 10:  # YYYY-MM-DD
        try:
            return date.fromisoformat(date_str)
        except ValueError:
            pass
    return None
