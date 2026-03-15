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
from datetime import datetime
from typing import Optional

import httpx
import pytz
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
    create_appointment_event,
    delete_event,
    update_appointment_event,
)

logger = logging.getLogger("falconconnect.close_webhooks")

router = APIRouter()

CLOSE_API_BASE = "https://api.close.com/api/v1"

# Custom field ID for Appointment Length (choices: "15 min", "30 min", "60 min")
CF_APPOINTMENT_LENGTH = "cf_BdxJMNDwJW0w9LeDm5mC3m6K7lPdu4XBtgaYEdiB433"

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
    """Extract the first phone number from a Close contact."""
    phones = contact.get("phones", [])
    if phones:
        return phones[0].get("phone")
    return None


# ---------------------------------------------------------------------------
# Core appointment processing
# ---------------------------------------------------------------------------

async def _process_appointment(
    activity_data: dict,
    lead_id: str,
) -> dict:
    """Process a Book Appointment activity — send SMS, create GCal, link email.

    Handles both new bookings and rebookings (updated activities).

    Args:
        activity_data: The "data" dict from the Close webhook event — contains
                       the custom activity instance fields.
        lead_id: The Close lead ID (from event.lead_id).
    """
    settings = get_settings()

    # Close sends custom fields as flat "custom.cf_XXX" keys at the data level,
    # NOT as a nested "custom" dict. Extract them directly.
    appointment_dt_str = activity_data.get(f"custom.{CF_APPOINTMENT_DATETIME}")
    if not appointment_dt_str:
        logger.warning("No appointment_datetime in activity for lead %s", lead_id)
        return {"status": "skipped", "reason": "no appointment_datetime"}

    # Parse the datetime
    try:
        appointment_dt = datetime.fromisoformat(
            appointment_dt_str.replace("Z", "+00:00")
        )
        if appointment_dt.tzinfo is None:
            appointment_dt = pytz.utc.localize(appointment_dt)
    except (ValueError, AttributeError) as exc:
        logger.error(
            "Invalid appointment datetime '%s': %s", appointment_dt_str, exc
        )
        return {"status": "error", "reason": f"invalid datetime: {appointment_dt_str}"}

    # Get timezone choice, notes, and appointment length from custom fields
    tz_choice = activity_data.get(f"custom.{CF_APPOINTMENT_TIMEZONE}")
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
    if not contact_id and lead_id:
        lead_data = await _get_lead_details(lead_id)
        if lead_data:
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

    if not phone:
        logger.warning(
            "No phone number on contact %s (lead %s) — skipping SMS, continuing with GCal",
            contact_id, lead_id
        )

    # --- Check for rebooking — cancel old reminders/events if they exist ---
    async with _get_session_factory()() as session:
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

    # --- Step 1: Send SMS (confirmation + schedule reminders) ---
    sms_results: dict = {"confirmation": None, "reminder_24hr": None, "reminder_1hr": None}
    if phone:
        sms_results = await schedule_appointment_sms(
            lead_id=lead_id,
            contact_id=contact_id,
            phone=phone,
            first_name=first_name,
            appointment_dt=appointment_dt,
            tz_choice=tz_choice,
        ) or sms_results  # fallback if schedule_appointment_sms returns None

    # --- Step 2: Set up dummy email + GCal event ---
    dummy_email = f"lead-{lead_id}@appointments.falconfinancial.org"

    # Add dummy email to contact (merge, don't overwrite)
    existing_emails = contact.get("emails", [])
    await _patch_contact_add_calendar_email(contact_id, dummy_email, existing_emails)

    # Create Google Calendar event (duration from appointment length field)
    gcal_event_id = await create_appointment_event(
        summary=f"Call with {contact_name or lead_id}",
        description=(
            f"Close Lead: {lead_id}\n"
            f"Contact: {contact_name}\n"
            f"Phone: {phone}\n"
            f"Duration: {duration_minutes} min\n"
            f"{f'Notes: {notes}' if notes else ''}"
        ),
        start_dt=appointment_dt,
        duration_minutes=duration_minutes,
        attendee_email=dummy_email,
    )

    # --- Step 3: Save to database ---
    async with _get_session_factory()() as session:
        # Save appointment reminder record
        reminder = AppointmentReminder(
            lead_id=lead_id,
            contact_id=contact_id,
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

        await session.commit()

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

@router.post("/close")
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
        if not _verify_close_signature(
            raw_body, sig_hash, sig_timestamp, settings.close_webhook_secret
        ):
            logger.warning("Close webhook signature verification failed — returning 200 to prevent retries")
            # Return 200 so Close doesn't retry, but don't process the event
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

    # --- Handle UPDATE with datetime change (reschedule) ---
    if action == "updated":
        changed_fields = event.get("changed_fields", [])
        datetime_field_key = f"custom.{CF_APPOINTMENT_DATETIME}"
        tz_field_key = f"custom.{CF_APPOINTMENT_TIMEZONE}"
        length_field_key = f"custom.{CF_APPOINTMENT_LENGTH}"

        # If appointment datetime, timezone, or length changed → reschedule
        if any(f in changed_fields for f in (datetime_field_key, tz_field_key, length_field_key)):
            logger.info(
                "Reschedule detected for lead %s — changed_fields: %s",
                lead_id,
                changed_fields,
            )
            # _process_appointment already handles rebooking (cancels old, creates new)
            result = await _process_appointment(event_data, lead_id)
            return result

    # --- Handle CREATE or non-datetime UPDATE ---
    result = await _process_appointment(event_data, lead_id)
    return result
