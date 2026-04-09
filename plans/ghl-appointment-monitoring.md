# GHL Appointment Monitoring Webhook

**Status:** Spec — not started
**Created:** 2026-04-09
**Priority:** Medium — after policy review + FreeCallerRegistry

## Purpose

When VA books an appointment in GHL before Seb reaches the lead in Close, auto-sync to Close + GCal + send confirmation SMS.

## Endpoint

`POST /api/ghl/appointment-booked`

## Trigger

GHL workflow fires webhook on `AppointmentCreate` or tag change (e.g., `va-booked`)

## Flow

1. Receive GHL webhook (contact ID, appointment datetime, notes)
2. Look up Close lead via `LeadXref` (GHL contact ID → Close lead ID)
3. Create `Book Appointment` custom activity in Close with status `Booked`
4. Create GCal event
5. Send confirmation SMS
6. Log to `sync_log`

## Data Mapping

- GHL contact ID → Close lead (via LeadXref or CF_GHL_ID lookup)
- GHL start time → Close `custom.{CF_APPOINTMENT_DATETIME}`
- Timezone → derive from lead state or GHL calendar timezone
- Notes → Close `custom.{CF_APPOINTMENT_NOTES}`
- Status → `Booked`

## Edge Cases

- **Lead not in Close yet** → create lead first (reuse `ghl_cadence.py` logic), then book
- **Lead already has active appointment** → rebook (cancel old GCal + SMS, create new)
- **Duplicate webhook** → activity_id idempotency guard already handles this
- **Timezone mismatch** → GHL sends UTC, Close stores local. Need to convert + set tz field

## Dependencies

- Reuses: `LeadXref` lookup, `_create_close_lead()`, `create_appointment_event()`, `schedule_appointment_sms()`, `_log_sync()`
- New: GHL webhook auth (X-GHL-Webhook-Secret), appointment payload parser

## GHL Webhook Setup

- In GHL: create workflow trigger on calendar booking OR tag-based trigger (`va-booked`)
- Webhook URL: `https://falconnect.org/api/ghl/appointment-booked`
- Auth header: `X-GHL-Webhook-Secret`
