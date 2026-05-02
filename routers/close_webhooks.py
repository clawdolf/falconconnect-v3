"""Close.com webhook handler — processes Book Appointment custom activities.

Receives Close webhook events, validates HMAC-SHA256 signature, and for
matching appointment activities:
1. Sends confirmation SMS + schedules 24hr/1hr reminders via Close SMS API
2. Creates a Google Calendar event with a dummy attendee email
3. PATCHes the dummy email onto the Close contact for calendar-to-lead linking
4. Handles rebooking (cancel old SMS + GCal, create new)

Close webhook payload structure (from their docs):
{
  "event": {
    "action": "created",
    "object_type": "activity.custom_activity",
    "data": { ... activity fields ... },
    "lead_id": "lead_xxx",
    ...
  },
  "subscription_id": "whsub_xxx"
}

Signature verification:
- Headers: close-sig-hash, close-sig-timestamp
- HMAC-SHA256 of (timestamp + payload) using hex-decoded signature_key
"""

import hashlib
import hmac
import json
import logging
import traceback
from datetime import datetime
from typing import Optional
from zoneinfo import ZoneInfo

import httpx
from fastapi import APIRouter, HTTPException, Request, status
from sqlalchemy import select

from config import get_settings
from db.database import _get_session_factory
from db.models import AppointmentCalendarEmail, AppointmentReminder
from services.close_sms import (
    CF_APPOINTMENT_DATETIME,
    CF_APPOINTMENT_NOTES,
    CF_APPOINTMENT_TIMEZONE,
    cancel_scheduled_sms,
    schedule_appointment_sms,
)
from services.google_calendar import (
    GCalError,
    create_appointment_event,
    delete_event,
)
from services.telegram_alerts import send_telegram_alert
from utils.rate_limit import limiter

# Custom field ID for Appointment Status (choices: Booked, Confirmed, Rescheduled, Cancelled, No Show)
CF_APPOINTMENT_STATUS = "cf_fpLqCQ4At7nrMwzAbHZDGQzgBvvq9WuenxG2PLK1i7u"

logger = logging.getLogger("falconconnect.close_webhooks")

router = APIRouter()

CLOSE_API_BASE = "https://api.close.com/api/v1"

# Custom field ID for Appointment Length (choices: "15 min", "30 min", "60 min")
CF_APPOINTMENT_LENGTH = "cf_BdxJMNDwJW0w9LeDm5mC3m6K7lPdu4XBtgaYEdiB433"

# Custom field ID for Notify toggle (choices: "Yes", "No"; blank/missing = default Yes)
# Run scripts/fetch_appointment_field_ids.py to discover the ID after adding the field in Close.
CF_APPOINTMENT_NOTIFY = "cf_fcR87MwVB1JJaHqYrCozh8DhzSHS29u75yOB9Hf5bF5"

# Map appointment length choice to minutes
DURATION_MAP: dict[str | None, int] = {
    "15 min": 15,
    "30 min": 30,
    "60 min": 60,
}
DEFAULT_DURATION_MINUTES = 60

# Timezones where early-morning UTC times likely indicate AM/PM confusion
AM_PM_CONFUSION_TIMEZONES = {"AZ", "MT", "PT"}
AM_PM_CONFUSION_UTC_HOUR_MAX = 6  # 00:00-06:00 UTC


# ---------------------------------------------------------------------------
# Webhook signature verification (Close-specific)
# ---------------------------------------------------------------------------

def _verify_close_signature(
    raw_body: bytes,
    sig_hash: Optional[str],
    sig_timestamp: Optional[str],
    signature_key: str,
) -> bool:
    """Verify Close.com webhook HMAC-SHA256 signature.

    Close sends:
      - close-sig-hash: hex HMAC-SHA256 digest
      - close-sig-timestamp: unix timestamp string

    The signed data is: timestamp + payload (concatenated as strings).
    The key is the subscription's signature_key (hex-encoded).

    Reference: https://developer.close.com/topics/webhooks/#webhook-signatures
    """
    if not sig_hash or not sig_timestamp or not signature_key:
        return False

    try:
        data = sig_timestamp + raw_body.decode("utf-8")
        expected = hmac.new(
            bytearray.fromhex(signature_key),
            data.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
        return hmac.compare_digest(expected, sig_hash)
    except (ValueError, UnicodeDecodeError) as exc:
        logger.warning("Signature verification error: %s", exc)
        return False


# ---------------------------------------------------------------------------
# Close API helpers
# ---------------------------------------------------------------------------

async def _get_lead_details(lead_id: str) -> Optional[dict]:
    """Fetch lead details from Close API (name, contacts)."""
    settings = get_settings()
    api_key = settings.close_api_key
    if not api_key:
        return None

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.get(
                f"{CLOSE_API_BASE}/lead/{lead_id}/",
                auth=(api_key, ""),
            )
            resp.raise_for_status()
            return resp.json()
    except Exception as exc:
        logger.error("Failed to fetch lead %s: %s", lead_id, exc)
        return None


async def _get_contact_details(contact_id: str) -> Optional[dict]:
    """Fetch contact details from Close API."""
    settings = get_settings()
    api_key = settings.close_api_key
    if not api_key:
        return None

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.get(
                f"{CLOSE_API_BASE}/contact/{contact_id}/",
                auth=(api_key, ""),
            )
            resp.raise_for_status()
            return resp.json()
    except Exception as exc:
        logger.error("Failed to fetch contact %s: %s", contact_id, exc)
        return None


async def _patch_contact_add_calendar_email(
    contact_id: str,
    dummy_email: str,
    existing_emails: list[dict],
) -> bool:
    """Add the dummy calendar email to a Close contact's email list.

    Merges with existing emails — never overwrites. Uses type "Calendar"
    for the dummy email entry. Skips if already present.
    """
    settings = get_settings()
    api_key = settings.close_api_key
    if not api_key:
        return False

    # Check if dummy email is already on the contact
    for entry in existing_emails:
        if entry.get("email", "").lower() == dummy_email.lower():
            logger.info(
                "Dummy email %s already on contact %s — skipping PATCH",
                dummy_email,
                contact_id,
            )
            return True

    # Append to existing emails
    updated_emails = list(existing_emails) + [
        {"email": dummy_email, "type": "Calendar"}
    ]

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.put(
                f"{CLOSE_API_BASE}/contact/{contact_id}/",
                json={"emails": updated_emails},
                auth=(api_key, ""),
            )
            resp.raise_for_status()
            logger.info(
                "Added calendar email %s to contact %s",
                dummy_email,
                contact_id,
            )
            return True
    except Exception as exc:
        logger.error(
            "Failed to add calendar email to contact %s: %s",
            contact_id,
            exc,
        )
        return False


def _extract_first_name(contact_name: str) -> str:
    """Extract first name from a contact's full name."""
    if not contact_name:
        return "there"
    return contact_name.strip().split()[0]


def _extract_phone(contact: dict) -> Optional[str]:
    """Extract phone from a Close contact, preferring mobile type.

    Falls back to first phone if none is labeled mobile.
    """
    phones = contact.get("phones", [])
    if not phones:
        return None
    mobile = next((p for p in phones if p.get("type") == "mobile"), None)
    return (mobile or phones[0]).get("phone")


# ---------------------------------------------------------------------------
# Core appointment processing
# ---------------------------------------------------------------------------

async def _process_appointment(
    activity_data: dict,
    lead_id: str,
    is_update: bool = False,
) -> dict:
    """Process a Book Appointment activity — send SMS, create GCal, link email.

    Handles both new bookings and rebookings (updated activities).

    Args:
        activity_data: The "data" dict from the Close webhook event — contains
                       the custom activity instance fields.
        lead_id: The Close lead ID (from event.lead_id).
    """
    settings = get_settings()

    # --- Hard draft block: NEVER process draft webhooks ---
    # Close auto-saves drafts constantly while the form is open. These fire
    # both 'created' and 'updated' webhooks with status="draft". Any webhook
    # with draft status must be dropped — SMS only fires on the published booking.
    activity_status = activity_data.get("status", "published")
    if activity_status == "draft":
        logger.info("Skipping draft webhook for lead %s (is_update=%s)", lead_id, is_update)
        return {"status": "skipped", "reason": "draft"}

    # --- Appointment status gate: only fire SMS on active statuses ---
    # Even after publish, check the appointment-specific status field.
    # SMS only fires for: Booked, Confirmed, Rescheduled.
    # Cancelled / blank / other statuses are dropped here.
    appointment_status = activity_data.get(f"custom.{CF_APPOINTMENT_STATUS}", "").strip()
    ACTIVE_APPOINTMENT_STATUSES = {"Booked", "Confirmed", "Rescheduled"}
    if appointment_status and appointment_status not in ACTIVE_APPOINTMENT_STATUSES:
        logger.info(
            "Skipping webhook — appointment status '%s' not in active set for lead %s",
            appointment_status, lead_id,
        )
        return {"status": "skipped", "reason": f"inactive_status: {appointment_status}"}
    if not appointment_status:
        # Published activity with no appointment status set — skip to be safe
        logger.info("Skipping webhook — no appointment status set on published activity for lead %s", lead_id)
        return {"status": "skipped", "reason": "no_appointment_status"}

    # --- Idempotency guard: skip true duplicates, allow rebookings through ---
    # If we've already processed this activity_id, check if the incoming datetime
    # matches what's stored. Same datetime = true duplicate, skip. Different datetime
    # = rebooking from a corrected draft, let it through.
    activity_id = activity_data.get("id")
    if activity_id:
        async with _get_session_factory()() as session:
            existing_result = await session.execute(
                select(AppointmentReminder).where(
                    AppointmentReminder.activity_id == activity_id,
                    AppointmentReminder.status == "active",
                )
            )
            existing_reminder = existing_result.scalar_one_or_none()
            if existing_reminder and not is_update:
                # Check if incoming datetime differs from stored — indicates
                # the draft was corrected before publishing
                appointment_dt_str_for_check = activity_data.get(f"custom.{CF_APPOINTMENT_DATETIME}")
                if appointment_dt_str_for_check:
                    try:
                        from datetime import timezone as _idt_tz
                        _incoming = datetime.fromisoformat(appointment_dt_str_for_check.replace("Z", "+00:00") if "Z" in appointment_dt_str_for_check else appointment_dt_str_for_check)
                        _stored = existing_reminder.appointment_datetime
                        if _stored:
                            _s = _stored.astimezone(_idt_tz.utc) if _stored.tzinfo else _stored.replace(tzinfo=_idt_tz.utc)
                            _i = _incoming.astimezone(_idt_tz.utc) if _incoming.tzinfo else _incoming.replace(tzinfo=_idt_tz.utc)
                            if abs((_i - _s).total_seconds()) >= 60:
                                logger.info(
                                    "Activity %s already processed but datetime changed (%s → %s) — "
                                    "treating as rebooking for lead %s",
                                    activity_id, _s.isoformat(), _i.isoformat(), lead_id,
                                )
                                # Fall through to process as rebooking
                            else:
                                logger.info(
                                    "True duplicate — activity %s already processed with same datetime for lead %s",
                                    activity_id, lead_id,
                                )
                                return {"status": "skipped", "reason": "duplicate_webhook", "activity_id": activity_id}
                    except (ValueError, AttributeError):
                        # Can't parse datetime — skip to be safe
                        logger.warning("Could not parse datetime for idempotency check — skipping as duplicate")
                        return {"status": "skipped", "reason": "duplicate_webhook", "activity_id": activity_id}
                else:
                    # No datetime in payload — skip as duplicate
                    return {"status": "skipped", "reason": "duplicate_webhook", "activity_id": activity_id}

    # Close sends custom fields as flat "custom.cf_XXX" keys at the data level,
    # NOT as a nested "custom" dict. Extract them directly.
    appointment_dt_str = activity_data.get(f"custom.{CF_APPOINTMENT_DATETIME}")
    logger.info("RAW appointment_dt_str for lead %s: %s | tz_choice: %s", lead_id, appointment_dt_str, activity_data.get(f"custom.{CF_APPOINTMENT_TIMEZONE}"))
    if not appointment_dt_str:
        logger.warning("No appointment_datetime in activity for lead %s", lead_id)
        return {"status": "skipped", "reason": "no appointment_datetime"}

    # Get timezone choice early — needed to correctly interpret the naive datetime
    tz_choice = activity_data.get(f"custom.{CF_APPOINTMENT_TIMEZONE}")

    # Parse the datetime — use tz_choice to interpret naive datetimes correctly.
    # Close stores local times without UTC offset. Use the selected timezone so
    # 5pm ET stays 5pm ET, not 5pm AZ.
    try:
        # Close sends naive local times (no UTC offset). Parse as-is; if naive,
        # localize using tz_choice so 5pm ET stays 5pm ET not 5pm UTC/AZ.
        appointment_dt = datetime.fromisoformat(appointment_dt_str.replace("Z", "+00:00") if "Z" in appointment_dt_str else appointment_dt_str)
        if appointment_dt.tzinfo is None:
            from services.close_sms import _resolve_timezone
            tz_name, _ = _resolve_timezone(tz_choice)
            appointment_dt = appointment_dt.replace(tzinfo=ZoneInfo(tz_name))
        # else: datetime already has tz info (e.g. came with +00:00), respect it
    except (ValueError, AttributeError) as exc:
        logger.error(
            "Invalid appointment datetime '%s': %s", appointment_dt_str, exc
        )
        return {"status": "error", "reason": f"invalid datetime: {appointment_dt_str}"}

    # Close converts entered time to UTC using account timezone (AZ / UTC-7).
    # tz_choice is the user INTENDED timezone (e.g. ET for an Eastern client).
    # Re-localize: convert UTC -> AZ to recover the entered time, then attach tz_choice.
    if appointment_dt.tzinfo is not None and tz_choice and tz_choice.strip():
        from services.close_sms import _resolve_timezone
        import pytz as _pytz
        _az_tz = _pytz.timezone("America/Phoenix")
        _az_local = appointment_dt.astimezone(_az_tz)
        _naive_entered = _az_local.replace(tzinfo=None)  # the time Seb typed, e.g. 17:00
        _tz_name, _ = _resolve_timezone(tz_choice)
        appointment_dt = _naive_entered.replace(tzinfo=ZoneInfo(_tz_name))

    notes = activity_data.get(f"custom.{CF_APPOINTMENT_NOTES}", "")
    length_choice = activity_data.get(f"custom.{CF_APPOINTMENT_LENGTH}")
    duration_minutes = DURATION_MAP.get(length_choice, DEFAULT_DURATION_MINUTES)

    # --- AM/PM confusion warning (Task 3) ---
    # If time is between 00:00-06:00 UTC and timezone is AZ/MT/PT,
    # the time is very late at night / early morning local — likely AM/PM mix-up
    utc_hour = appointment_dt.hour
    tz_abbrev = (tz_choice or "").strip().split("(")[0].strip().split()[0].upper() if tz_choice else ""
    if utc_hour < AM_PM_CONFUSION_UTC_HOUR_MAX and tz_abbrev in AM_PM_CONFUSION_TIMEZONES:
        logger.warning(
            "Appointment time may be AM/PM confusion — %s in %s (lead %s)",
            appointment_dt.isoformat(),
            tz_choice,
            lead_id,
        )

    # Resolve contact_id — try activity data first, then look up from lead
    contact_id = activity_data.get("contact_id")
    # Always fetch lead data for address (needed for SMS template)
    lead_data = None
    if lead_id:
        lead_data = await _get_lead_details(lead_id)
    if not contact_id and lead_data:
        contacts = lead_data.get("contacts", [])
        if contacts:
            contact_id = contacts[0].get("id")

    if not contact_id:
        logger.error("No contact_id found for lead %s", lead_id)
        return {"status": "error", "reason": "no contact_id"}

    # Fetch contact details
    contact = await _get_contact_details(contact_id)
    if not contact:
        return {"status": "error", "reason": f"contact {contact_id} not found"}

    contact_name = contact.get("name", "")
    first_name = _extract_first_name(contact_name)
    phone = _extract_phone(contact)

    # Extract street address from lead data for SMS template
    address = ""
    if lead_data:
        addresses = lead_data.get("addresses", [])
        if addresses:
            addr = addresses[0]
            line1 = addr.get("address_line_1", "").strip()
            line2 = addr.get("address_line_2", "").strip()
            parts = [p for p in [line1, line2] if p]
            address = ", ".join(parts)

    if not phone:
        logger.warning(
            "No phone number on contact %s (lead %s) — skipping SMS, continuing with GCal",
            contact_id, lead_id
        )

    # --- Pre-rebooking idempotency: skip if incoming datetime matches stored ---
    # Close fires multiple events per edit. Duplicate fires have same appointment_dt
    # after re-localization. Real changes differ. Check BEFORE any destructive ops.
    if is_update and activity_id:
        from datetime import timezone as _idt_tz
        async with _get_session_factory()() as _idt_s:
            _r = await _idt_s.execute(
                select(AppointmentReminder.appointment_datetime).where(
                    AppointmentReminder.activity_id == activity_id,
                    AppointmentReminder.status == "active",
                )
            )
            _stored_dt = _r.scalar_one_or_none()
        if _stored_dt is not None:
            _s = _stored_dt.astimezone(_idt_tz.utc) if _stored_dt.tzinfo else _stored_dt.replace(tzinfo=_idt_tz.utc)
            _i = appointment_dt.astimezone(_idt_tz.utc) if appointment_dt.tzinfo else appointment_dt.replace(tzinfo=_idt_tz.utc)
            if abs((_i - _s).total_seconds()) < 60:
                logger.info("Idempotency guard: activity %s datetime unchanged (%.0fs diff) -- skipping duplicate for lead %s", activity_id, abs((_i - _s).total_seconds()), lead_id)
                return {"status": "skipped", "reason": "datetime_unchanged", "activity_id": activity_id}

    # --- Check for rebooking — cancel old reminders/events if they exist ---
    # Use activity_id when available (reschedule of same activity) to avoid
    # duplicate GCal entries when Close fires multiple webhook events for one booking.
    # Fall back to lead_id search for new bookings that replace old activities.
    async with _get_session_factory()() as session:
        if is_update and activity_id:
            result = await session.execute(
                select(AppointmentReminder).where(
                    AppointmentReminder.activity_id == activity_id,
                    AppointmentReminder.status == "active",
                )
            )
        else:
            result = await session.execute(
                select(AppointmentReminder).where(
                    AppointmentReminder.lead_id == lead_id,
                    AppointmentReminder.status == "active",
                )
            )
        existing_reminders = result.scalars().all()

        for reminder in existing_reminders:
            logger.info(
                "Rebooking detected for lead %s — cancelling old reminders",
                lead_id,
            )
            # Cancel scheduled SMS (confirmation already sent — can't unsend)
            for sms_id in [reminder.sms_id_24hr, reminder.sms_id_1hr]:
                if sms_id:
                    await cancel_scheduled_sms(sms_id)

            # Delete old GCal event
            if reminder.gcal_event_id:
                await delete_event(reminder.gcal_event_id)

            # Mark old reminder as rebooked
            reminder.status = "rebooked"

        if existing_reminders:
            await session.commit()

    # --- Notify toggle: blank/"Yes" => send SMS; "No" => skip SMS, keep calendar ---
    notify_choice = activity_data.get(f"custom.{CF_APPOINTMENT_NOTIFY}", "").strip()
    should_notify = notify_choice != "No"

    # --- Step 1: Send SMS (confirmation + schedule reminders) ---
    sms_results: dict = {"confirmation": None, "reminder_24hr": None, "reminder_1hr": None}
    if phone and should_notify:
        sms_results = await schedule_appointment_sms(
            lead_id=lead_id,
            contact_id=contact_id,
            phone=phone,
            first_name=first_name,
            appointment_dt=appointment_dt,
            tz_choice=tz_choice,
            address=address,
        ) or sms_results  # fallback if schedule_appointment_sms returns None
    elif phone:
        logger.info(
            "notify=No on appointment for lead %s — skipping SMS, calendar still synced",
            lead_id,
        )

    # --- Step 2: Set up dummy email + GCal event ---
    dummy_email = f"lead-{lead_id}@{settings.calendar_email_domain}"

    # Add dummy email to contact (merge, don't overwrite)
    existing_emails = contact.get("emails", [])
    await _patch_contact_add_calendar_email(contact_id, dummy_email, existing_emails)

    # Create Google Calendar event (duration from appointment length field)
    gcal_event_id = None
    try:
        gcal_event_id = await create_appointment_event(
            summary=f"{contact_name or lead_id}",
            description=(
                f"Open in Close: https://app.close.com/leads/{lead_id}/\n"
                f"Contact: {contact_name}\n"
                f"Phone: {phone or 'N/A'}\n"
                f"Duration: {duration_minutes} min\n"
                f"{f'Notes: {notes}' if notes else ''}"
            ),
            start_dt=appointment_dt,
            duration_minutes=duration_minutes,
            attendee_email=dummy_email,
            tz_choice=tz_choice,
        )
    except GCalError as exc:
        logger.error(
            "GCal event creation FAILED for lead %s: %s\n%s",
            lead_id,
            exc,
            traceback.format_exc(),
        )
        # Send Telegram alert — this is a critical failure
        await send_telegram_alert(
            f"<b>GCal FAILED</b>\n"
            f"Lead: {lead_id}\n"
            f"Contact: {contact_name}\n"
            f"Appointment: {appointment_dt.isoformat()}\n"
            f"Error: {exc}\n\n"
            f"The appointment was NOT added to Google Calendar. "
            f"SMS was sent but calendar is empty.",
        )
        return {
            "status": "error",
            "reason": "gcal_failed",
            "detail": str(exc),
            "lead_id": lead_id,
        }

    # --- Step 3: Save to database ---
    # Upsert on activity_id — same activity rescheduled = update existing row.
    # Inserting a new row with the same activity_id would hit the unique constraint.
    async with _get_session_factory()() as session:
        # Check for existing reminder with this activity_id (any status)
        existing_reminder = None
        if activity_id:
            result = await session.execute(
                select(AppointmentReminder).where(
                    AppointmentReminder.activity_id == activity_id
                )
            )
            existing_reminder = result.scalar_one_or_none()

        if existing_reminder:
            # Update in place — rebooking of the same activity
            existing_reminder.appointment_datetime = appointment_dt
            existing_reminder.sms_id_confirmation = sms_results.get("confirmation")
            existing_reminder.sms_id_24hr = sms_results.get("reminder_24hr")
            existing_reminder.sms_id_1hr = sms_results.get("reminder_1hr")
            existing_reminder.gcal_event_id = gcal_event_id
            existing_reminder.status = "active"
            logger.info(
                "Updated existing AppointmentReminder for activity %s (lead %s)",
                activity_id, lead_id,
            )
        else:
            reminder = AppointmentReminder(
                lead_id=lead_id,
                contact_id=contact_id,
                activity_id=activity_id,
                appointment_datetime=appointment_dt,
                sms_id_confirmation=sms_results.get("confirmation"),
                sms_id_24hr=sms_results.get("reminder_24hr"),
                sms_id_1hr=sms_results.get("reminder_1hr"),
                gcal_event_id=gcal_event_id,
                status="active",
            )
            session.add(reminder)

        # Upsert calendar email mapping
        result = await session.execute(
            select(AppointmentCalendarEmail).where(
                AppointmentCalendarEmail.lead_id == lead_id,
            )
        )
        existing_cal_email = result.scalar_one_or_none()
        if existing_cal_email:
            existing_cal_email.gcal_event_id = gcal_event_id
        else:
            cal_email = AppointmentCalendarEmail(
                lead_id=lead_id,
                contact_id=contact_id,
                dummy_email=dummy_email,
                gcal_event_id=gcal_event_id,
            )
            session.add(cal_email)

        try:
            await session.commit()
        except Exception as db_exc:
            # DB write failed — roll back all external side effects.
            # GCal event + scheduled SMS were already created; without a DB record
            # they can never be found or cleaned up on future deletes/rebookings.
            logger.error(
                "DB commit failed for appointment (lead %s, activity %s): %s — "
                "rolling back GCal event %s and %d SMS",
                lead_id, activity_id, db_exc, gcal_event_id,
                sum(1 for v in sms_results.values() if v),
            )
            if gcal_event_id:
                try:
                    await delete_event(gcal_event_id)
                    logger.info("GCal rollback: deleted orphaned event %s", gcal_event_id)
                except Exception as gcal_del_exc:
                    logger.error("GCal rollback failed for %s: %s", gcal_event_id, gcal_del_exc)
            for sms_id in [v for v in sms_results.values() if v]:
                try:
                    await cancel_scheduled_sms(sms_id)
                    logger.info("SMS rollback: cancelled orphaned SMS %s", sms_id)
                except Exception as sms_del_exc:
                    logger.error("SMS rollback failed for %s: %s", sms_id, sms_del_exc)
            raise

    logger.info(
        "Appointment processed: lead=%s contact=%s dt=%s gcal=%s sms=%s",
        lead_id,
        contact_id,
        appointment_dt.isoformat(),
        gcal_event_id,
        sms_results,
    )

    return {
        "status": "ok",
        "lead_id": lead_id,
        "contact_id": contact_id,
        "appointment_datetime": appointment_dt.isoformat(),
        "sms": sms_results,
        "gcal_event_id": gcal_event_id,
        "dummy_email": dummy_email,
    }


# ---------------------------------------------------------------------------
# Appointment deletion handler
# ---------------------------------------------------------------------------

async def _handle_appointment_deleted(lead_id: str) -> dict:
    """Handle a deleted/voided appointment activity.

    Cancels pending SMS reminders, deletes GCal event, and marks
    appointment records as cancelled.
    """
    cancelled_sms = 0
    deleted_gcal = 0

    async with _get_session_factory()() as session:
        result = await session.execute(
            select(AppointmentReminder).where(
                AppointmentReminder.lead_id == lead_id,
                AppointmentReminder.status == "active",
            )
        )
        active_reminders = result.scalars().all()

        if not active_reminders:
            logger.info(
                "No active appointment reminders found for deleted lead %s",
                lead_id,
            )
            return {"status": "skipped", "reason": "no active reminders to cancel"}

        for reminder in active_reminders:
            # Cancel scheduled SMS reminders
            for sms_id in [
                reminder.sms_id_24hr,
                reminder.sms_id_1hr,
            ]:
                if sms_id:
                    success = await cancel_scheduled_sms(sms_id)
                    if success:
                        cancelled_sms += 1

            # Delete GCal event
            if reminder.gcal_event_id:
                success = await delete_event(reminder.gcal_event_id)
                if success:
                    deleted_gcal += 1

            # Mark as cancelled
            reminder.status = "cancelled"

        await session.commit()

    logger.info(
        "Appointment deleted for lead %s: cancelled %d SMS, deleted %d GCal events",
        lead_id,
        cancelled_sms,
        deleted_gcal,
    )

    return {
        "status": "ok",
        "action": "deleted",
        "lead_id": lead_id,
        "cancelled_sms": cancelled_sms,
        "deleted_gcal_events": deleted_gcal,
    }


# ---------------------------------------------------------------------------
# Webhook endpoint
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Cadence lead.updated handler
# ---------------------------------------------------------------------------

# Cadence stage field ID
CF_CADENCE_STAGE = "cf_vuP2rYRL0LA3OK0nCyZm9b19ki8ddokdTAapVnJ2Elb"

# Map cadence_stage value → (template_key, update_stage_to)
CADENCE_TRIGGER_MAP = {
    "3. r1-done": ("r1_done", ""),        # leave stage as-is
    "5. r2-done": ("r2_done", ""),        # leave stage as-is
    "7. r3-done": ("r3_done", "nurture"), # advance to nurture after SMS
}


async def _handle_lead_updated(event: dict) -> dict:
    """Handle lead.updated events for cadence_stage changes.

    When cadence_stage changes to r1-done/r2-done/r3-done, schedule
    the appropriate cadence SMS for next morning 8:30am in lead's local tz.
    For r3-done, also sets stage to 'nurture' after SMS is scheduled.
    """
    lead_id = event.get("lead_id", "") or event.get("data", {}).get("lead_id", "")
    changed_fields = event.get("changed_fields", [])
    event_data = event.get("data", {})

    cadence_field_key = f"custom.{CF_CADENCE_STAGE}"

    if cadence_field_key not in changed_fields:
        logger.debug(
            "lead.updated for lead %s — cadence_stage field not in changed_fields, skipping",
            lead_id,
        )
        return {"status": "skipped", "reason": "cadence_stage not changed"}

    # Get new value — Close sends custom fields as "custom.cf_xxx" in the data dict
    new_stage = event_data.get(cadence_field_key, "")
    if not new_stage:
        logger.debug("lead.updated: no new cadence_stage value for lead %s", lead_id)
        return {"status": "skipped", "reason": "no new cadence_stage value"}

    trigger = CADENCE_TRIGGER_MAP.get(new_stage)
    if not trigger:
        logger.debug(
            "lead.updated: cadence_stage '%s' is not a trigger value for lead %s",
            new_stage, lead_id,
        )
        return {"status": "skipped", "reason": "cadence_stage '{new_stage}' not a trigger"}

    template_key, next_stage = trigger

    logger.info(
        "Cadence trigger: lead=%s stage='%s' → template=%s next_stage='%s'",
        lead_id, new_stage, template_key, next_stage or "(none)",
    )

    # Import here to avoid circular imports
    from routers.cadence_sms import send_cadence_sms

    result = await send_cadence_sms(
        lead_id=lead_id,
        template_key=template_key,
        next_stage=next_stage,
        date_scheduled_utc=None,  # auto-calc next morning 8:30am
    )

    if result.get("status") == "ok":
        logger.info(
            "Cadence SMS scheduled: lead=%s template=%s sms_id=%s scheduled_utc=%s",
            lead_id, template_key, result.get("sms_id"), result.get("scheduled_utc"),
        )
    else:
        logger.error(
            "Cadence SMS failed: lead=%s template=%s reason=%s",
            lead_id, template_key, result.get("reason"),
        )

    return result

@router.post("/close")
@limiter.limit("120/minute")
async def close_webhook(request: Request):
    """Receive and process Close.com webhook events.

    Verifies HMAC-SHA256 signature (close-sig-hash / close-sig-timestamp),
    then filters for Book Appointment custom activity events and dispatches
    to the appointment processor.

    Webhook URL: https://falconnect.org/webhooks/close
    """
    settings = get_settings()

    # Read raw body for signature verification
    raw_body = await request.body()

    # Verify webhook signature
    # Close uses: close-sig-hash and close-sig-timestamp headers
    # HMAC-SHA256 of (timestamp + payload) with hex-decoded signature_key
    sig_hash = request.headers.get("close-sig-hash")
    sig_timestamp = request.headers.get("close-sig-timestamp")

    if settings.close_webhook_secret:
        # Defensive check: Close webhook secrets are 64-char hex strings.
        # Truncation (e.g. from Render dashboard paste) causes silent signature failures.
        if len(settings.close_webhook_secret) != 64:
            logger.error(
                "CLOSE_WEBHOOK_SECRET has wrong length (%d chars, expected 64). "
                "Likely truncated when pasted into Render env vars. "
                "All webhooks will fail signature verification until this is fixed.",
                len(settings.close_webhook_secret),
            )
        if not _verify_close_signature(
            raw_body, sig_hash, sig_timestamp, settings.close_webhook_secret
        ):
            logger.error(
                "Close webhook signature verification FAILED — "
                "sig_hash=%s sig_timestamp=%s secret_len=%d body_len=%d. "
                "This webhook was DROPPED. If this keeps happening, "
                "recreate the Close webhook subscription with a matching signature_key.",
                sig_hash[:10] if sig_hash else "MISSING",
                sig_timestamp or "MISSING",
                len(settings.close_webhook_secret),
                len(raw_body),
            )
            # Alert on signature failures — this was the root cause of silent GCal drops
            await send_telegram_alert(
                "<b>Webhook signature verification FAILED</b>\n"
                f"sig_hash present: {bool(sig_hash)}\n"
                f"sig_timestamp present: {bool(sig_timestamp)}\n"
                f"Payload size: {len(raw_body)} bytes\n\n"
                "The appointment webhook was DROPPED. "
                "Check CLOSE_WEBHOOK_SECRET matches the Close subscription's signature_key."
            )
            return {"status": "skipped", "reason": "signature_verification_failed"}
    else:
        logger.warning(
            "CLOSE_WEBHOOK_SECRET not set — skipping signature verification"
        )

    # Parse the payload
    try:
        payload = json.loads(raw_body)
    except json.JSONDecodeError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid JSON body",
        )

    # Close webhook structure: {"event": {...}, "subscription_id": "..."}
    event = payload.get("event", {})
    action = event.get("action", "")
    object_type = event.get("object_type", "")
    event_data = event.get("data", {})
    lead_id = event.get("lead_id", "")

    logger.info(
        "Close webhook: action=%s object_type=%s lead_id=%s",
        action,
        object_type,
        lead_id,
    )

    # Route lead.updated events to cadence handler
    if object_type == "lead" and action == "updated":
        return await _handle_lead_updated(event)

    # Only process custom activity events
    if object_type != "activity.custom_activity":
        logger.debug(
            "Ignoring webhook — object_type %s (not activity.custom_activity)",
            object_type,
        )
        return {"status": "skipped", "reason": f"object_type: {object_type}"}

    if action not in ("created", "updated", "deleted"):
        logger.debug("Ignoring webhook — action %s (not created/updated/deleted)", action)
        return {"status": "skipped", "reason": f"action: {action}"}

    # Check this is our Book Appointment activity type
    activity_type_id = event_data.get("custom_activity_type_id", "")
    expected_activity_type = settings.close_appointment_activity_type_id

    if activity_type_id != expected_activity_type:
        logger.debug(
            "Ignoring webhook — activity type %s != expected %s",
            activity_type_id,
            expected_activity_type,
        )
        return {"status": "skipped", "reason": "not an appointment activity"}

    # lead_id might also be in the data object
    if not lead_id:
        lead_id = event_data.get("lead_id", "")
    if not lead_id:
        logger.error("No lead_id in webhook event")
        return {"status": "error", "reason": "no lead_id"}

    # --- Handle DELETE ---
    if action == "deleted":
        result = await _handle_appointment_deleted(lead_id)
        return result

    # --- Handle UPDATE ---
    if action == "updated":
        changed_fields = event.get("changed_fields", [])
        datetime_field_key = f"custom.{CF_APPOINTMENT_DATETIME}"
        tz_field_key = f"custom.{CF_APPOINTMENT_TIMEZONE}"
        length_field_key = f"custom.{CF_APPOINTMENT_LENGTH}"
        status_field_key = f"custom.{CF_APPOINTMENT_STATUS}"

        # --- Status change: Cancelled → delete GCal event + cancel SMS ---
        if status_field_key in changed_fields:
            new_status = event_data.get(status_field_key, "")
            logger.info(
                "Appointment status changed to '%s' for lead %s",
                new_status,
                lead_id,
            )

            if new_status == "Cancelled":
                result = await _handle_appointment_deleted(lead_id)
                return result

            if new_status == "Rescheduled":
                # Just log — actual reschedule fires when datetime changes
                logger.info(
                    "Appointment marked 'Rescheduled' for lead %s — "
                    "awaiting datetime change to trigger rebooking",
                    lead_id,
                )
                return {
                    "status": "ok",
                    "action": "status_change",
                    "new_status": "Rescheduled",
                    "lead_id": lead_id,
                    "note": "Awaiting datetime change to trigger actual rebooking",
                }

        # If appointment datetime, timezone, or length changed → reschedule
        if any(f in changed_fields for f in (datetime_field_key, tz_field_key, length_field_key)):
            logger.info(
                "Reschedule detected for lead %s — changed_fields: %s",
                lead_id,
                changed_fields,
            )
            # _process_appointment already handles rebooking (cancels old, creates new)
            result = await _process_appointment(event_data, lead_id, is_update=True)
            return result

        # --- Draft-to-published transition: process regardless of changed_fields ---
        # When Close transitions a draft to published, changed_fields often only
        # contains ["status", "date_updated"] — the datetime is NOT listed even
        # though it's the correct final value. Process it anyway.
        # The appointment status gate above already verified the status is active.
        activity_webhook_status = event_data.get("status", "published")
        if activity_webhook_status in ("Booked", "published"):
            logger.info(
                "Draft-to-published transition detected for lead %s — "
                "processing appointment with webhook data (changed_fields: %s)",
                lead_id,
                changed_fields,
            )
            result = await _process_appointment(event_data, lead_id, is_update=True)
            return result

        # Other field updates on an existing appointment — skip
        logger.debug(
            "Ignoring update for lead %s — changed_fields %s don't affect scheduling",
            lead_id,
            changed_fields,
        )
        return {"status": "skipped", "reason": "non-scheduling field update"}

    # --- Handle CREATE ---
    result = await _process_appointment(event_data, lead_id)
    return result
