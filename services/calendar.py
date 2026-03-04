"""iCal generation service — builds .ics feeds from Notion data.

Two separate feeds:
  - Appointments: timed 15-minute events with -60min and -24h alarms
  - Follow-ups:   all-day events with 8am morning alarm

Both feeds include a direct Notion page link in every event description.

Uses real Notion property names:
  Name (title), Mobile Phone (phone_number), Lead Status (status),
  LAge (select), Aggregate Comments (rich_text),
  Appointment Date (date), Follow-Up Date (date).
"""

import logging
from datetime import datetime, timedelta, date
from typing import Any, Dict, List, Literal

import pytz
from icalendar import Calendar, Event, Alarm

logger = logging.getLogger("falconconnect.calendar")

PHOENIX_TZ = pytz.timezone("America/Phoenix")


def _notion_url(page_id: str) -> str:
    """Build a direct Notion page URL from a page ID.

    Strips hyphens from the UUID to produce the URL format Notion expects.
    Example: 184d58e6-3823-800f-9b13-f06aaa14e0e6
           → https://www.notion.so/184d58e638238009b13f06aaa14e0e6
    """
    clean_id = page_id.replace("-", "")
    return f"https://www.notion.so/{clean_id}"


def _new_calendar(cal_name: str) -> Calendar:
    """Create a fresh iCalendar object with standard headers."""
    cal = Calendar()
    cal.add("prodid", "-//FalconConnect v3//falconfinancial.org//")
    cal.add("version", "2.0")
    cal.add("calscale", "GREGORIAN")
    cal.add("method", "PUBLISH")
    cal.add("x-wr-calname", cal_name)
    cal.add("x-wr-timezone", "America/Phoenix")
    return cal


def build_appointments_feed(pages: List[Dict[str, Any]]) -> str:
    """Build an iCal string containing only appointment events.

    Each event is 15 minutes with -60min and -24h VALARM reminders.
    Description includes lead status, LAge, notes, and Notion page link.
    """
    cal = _new_calendar("FC Appointments — Seb")
    seen_uids: set = set()

    for page in pages:
        props = page.get("properties", {})
        page_id = page.get("id", "unknown")

        appt_date_str = _date_value(props.get("Appointment Date", {}))
        if not appt_date_str:
            continue

        uid = f"appt-{page_id}@falconconnect"
        if uid in seen_uids:
            continue
        seen_uids.add(uid)

        name = _title_text(props.get("Name", {}))
        phone = _phone(props.get("Mobile Phone", {}))
        lead_status = _status_text(props.get("Lead Status", {}))
        lage = _select_text(props.get("LAge", {}))
        comments = _rich_text(props.get("Aggregate Comments", {}))
        notion_link = _notion_url(page_id)

        event = Event()
        event.add("uid", uid)
        event.add("summary", f"{name} — {phone}" if phone else name)
        event.add("dtstart", _to_phoenix_dt(appt_date_str))
        event.add("duration", timedelta(minutes=15))

        desc_lines = [
            f"Status: {lead_status or 'N/A'} | LAge: {lage or 'N/A'} | Notes: {comments or 'N/A'}",
            f"Notion: {notion_link}",
        ]
        event.add("description", "\n".join(desc_lines))
        event.add("dtstamp", datetime.now(PHOENIX_TZ))

        # 60-min reminder
        a60 = Alarm()
        a60.add("action", "DISPLAY")
        a60.add("trigger", timedelta(minutes=-60))
        a60.add("description", f"Appointment in 1 hour: {name}")
        event.add_component(a60)

        # 24-hour reminder
        a24 = Alarm()
        a24.add("action", "DISPLAY")
        a24.add("trigger", timedelta(hours=-24))
        a24.add("description", f"Appointment tomorrow: {name}")
        event.add_component(a24)

        cal.add_component(event)

    return cal.to_ical().decode("utf-8")


def build_followups_feed(pages: List[Dict[str, Any]]) -> str:
    """Build an iCal string containing only follow-up events.

    All-day events with 8am morning VALARM reminder.
    Description includes Notion page link.
    """
    cal = _new_calendar("FC Follow-Ups — Seb")
    seen_uids: set = set()

    for page in pages:
        props = page.get("properties", {})
        page_id = page.get("id", "unknown")

        fu_date_str = _date_value(props.get("Follow Up Date", {}))
        if not fu_date_str:
            continue

        uid = f"followup-{page_id}@falconconnect"
        if uid in seen_uids:
            continue
        seen_uids.add(uid)

        name = _title_text(props.get("Name", {}))
        lead_status = _status_text(props.get("Lead Status", {}))
        lage = _select_text(props.get("LAge", {}))
        comments = _rich_text(props.get("Aggregate Comments", {}))
        notion_link = _notion_url(page_id)

        event = Event()
        event.add("uid", uid)
        event.add("summary", f"Follow Up — {name}")

        fu_date = _parse_date_only(fu_date_str)
        if fu_date:
            event.add("dtstart", fu_date)  # all-day event
        else:
            event.add("dtstart", _to_phoenix_dt(fu_date_str))
            event.add("duration", timedelta(minutes=30))

        desc_lines = [
            f"Status: {lead_status or 'N/A'} | LAge: {lage or 'N/A'} | Notes: {comments or 'N/A'}",
            f"Notion: {notion_link}",
        ]
        event.add("description", "\n".join(desc_lines))
        event.add("dtstamp", datetime.now(PHOENIX_TZ))

        # 8am morning-of reminder
        a_morning = Alarm()
        a_morning.add("action", "DISPLAY")
        a_morning.add("trigger", timedelta(hours=8))  # 8am on the day
        a_morning.add("description", f"Follow up today: {name}")
        event.add_component(a_morning)

        cal.add_component(event)

    return cal.to_ical().decode("utf-8")


# --- Property extractors matching real Notion schema ---

def _title_text(prop: Dict[str, Any]) -> str:
    items = prop.get("title", [])
    return "".join(item.get("plain_text", "") for item in items) if items else ""


def _rich_text(prop: Dict[str, Any]) -> str:
    items = prop.get("rich_text", [])
    return "".join(item.get("plain_text", "") for item in items) if items else ""


def _phone(prop: Dict[str, Any]) -> str:
    return prop.get("phone_number", "") or ""


def _status_text(prop: Dict[str, Any]) -> str:
    status = prop.get("status")
    return status.get("name", "") if status else ""


def _select_text(prop: Dict[str, Any]) -> str:
    sel = prop.get("select")
    return sel.get("name", "") if sel else ""


def _date_value(prop: Dict[str, Any]) -> str:
    date_obj = prop.get("date")
    return date_obj.get("start", "") if date_obj else ""


def _to_phoenix_dt(date_str: str) -> datetime:
    from dateutil import parser as dtparser
    dt = dtparser.parse(date_str)
    if dt.tzinfo is None:
        dt = PHOENIX_TZ.localize(dt)
    return dt.astimezone(PHOENIX_TZ)


def _parse_date_only(date_str: str):
    if len(date_str) == 10:
        try:
            return date.fromisoformat(date_str)
        except ValueError:
            pass
    return None
