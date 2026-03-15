# Appointment Booking System — Setup Guide

One-action appointment booking: create a "Book Appointment" activity on a Close lead → FalconConnect automatically sends confirmation SMS, schedules reminders, and creates a Google Calendar event linked back to the lead.

---

## Architecture

```
Agent creates "Book Appointment" activity on Close lead
        ↓
Close fires webhook → POST https://falconnect.org/webhooks/close
        ↓
FalconConnect processes it:
  1. Sends confirmation SMS immediately via Close SMS API
  2. Schedules 24hr + 1hr reminder SMS via Close SMS API
  3. Creates Google Calendar event (5-min popup reminder)
  4. Adds dummy email to Close contact → Close calendar sync links meeting to lead
```

Rebooking: if the appointment datetime changes on the same lead, old SMS and GCal events are automatically cancelled and new ones created.

---

## Prerequisites

- Close.com account with SMS (Twilio) enabled
- Google Cloud project with Calendar API enabled
- FalconConnect deployed on Render

---

## Step 1: Close.com Custom Activity (Already Done)

The "Book Appointment" custom activity already exists:

| Item | Value |
|---|---|
| Activity Type ID | `actitype_6awVkZoRuXH1FWUd1F97CH` |
| DateTime Field | `cf_iiDP2BjqqEApsTl1uGQqbzw2cWm5Le8r3wTuUC8uc5Z` |
| Notes Field | `cf_WEM8v7zGSnCDPIEQuxNmdct5l5i19kCRoPCX5BexLqa` |
| Timezone Field | `cf_mqWOudG1Apd6FdrzP2qZqC1qUgx0pvGLKg4ZZgFsmn7` |

To verify it still exists:
```bash
CLOSE_API_KEY=xxx python3 scripts/setup_close_activity.py
```

---

## Step 2: Google Cloud Console Setup

1. Go to [Google Cloud Console](https://console.cloud.google.com/)
2. Create a new project (or use existing): "Falcon Financial"
3. Enable the **Google Calendar API**:
   - APIs & Services → Library → search "Google Calendar API" → Enable
4. Create a **Service Account**:
   - APIs & Services → Credentials → Create Credentials → Service Account
   - Name: "FalconConnect Calendar"
   - Role: none needed (it accesses the calendar via sharing, not org-wide)
   - Click Done
5. Create a key for the service account:
   - Click the service account → Keys tab → Add Key → Create new key → JSON
   - Download the JSON file — you'll need its contents for the env var
6. **Share your Google Calendar with the service account**:
   - Open Google Calendar (calendar.google.com)
   - Settings → Settings for "seb@falconfinancial.org" calendar
   - Share with specific people → Add the service account email
     (it looks like `falconconnect-calendar@project-name.iam.gserviceaccount.com`)
   - Permission: **Make changes to events**
7. Test the connection:
   ```bash
   GOOGLE_SERVICE_ACCOUNT_JSON=$(cat /path/to/service-account.json) python3 scripts/test_gcal.py
   ```

---

## Step 3: Close.com Webhook Setup

1. Go to Close.com → Settings → Webhooks (or Developer → Webhooks)
2. Create a new webhook:
   - **URL:** `https://falconnect.org/webhooks/close`
   - **Events:** Select `activity.custom` (or all activity events)
   - **Signing Secret:** Generate one and save it — you'll set it as `CLOSE_WEBHOOK_SECRET`
3. Note the signing secret for the next step

---

## Step 4: Environment Variables (Render)

Add these to the Render service environment panel:

| Variable | Value | Notes |
|---|---|---|
| `CLOSE_API_KEY` | Your Close.com API key | Should already be set |
| `CLOSE_APPOINTMENT_ACTIVITY_TYPE_ID` | `actitype_6awVkZoRuXH1FWUd1F97CH` | Already defaulted in code |
| `CLOSE_SMS_FROM_NUMBER` | `+14809999040` | Seb's Twilio number in Close |
| `CLOSE_WEBHOOK_SECRET` | (from Step 3) | Webhook signing secret |
| `GOOGLE_SERVICE_ACCOUNT_JSON` | (entire JSON key contents) | Paste the full JSON string |
| `GOOGLE_CALENDAR_ID` | `primary` | Or a specific calendar ID |

To set `GOOGLE_SERVICE_ACCOUNT_JSON` on Render:
- Copy the entire contents of the downloaded JSON key file
- Paste it as the value (Render handles multiline/JSON values)

---

## Step 5: Deploy and Test

After setting all env vars, trigger a deploy (push any commit or manual deploy).

### Quick smoke test

Create a "Book Appointment" activity on any test lead in Close:
1. Open a lead in Close
2. Click "Log Activity" → select "Book Appointment"
3. Set `appointment_datetime` to tomorrow at 2:00 PM
4. Set `timezone` to AZ
5. Optionally add notes
6. Save

Within seconds you should see:
- Confirmation SMS sent to the contact's phone
- 24hr and 1hr reminder SMS scheduled in Close (visible in activity timeline)
- Google Calendar event created with the contact as an attendee
- The meeting linked to the Close lead (via calendar sync)

### Verify in the database

```sql
SELECT * FROM appointment_reminders ORDER BY created_at DESC LIMIT 5;
SELECT * FROM appointment_calendar_emails ORDER BY created_at DESC LIMIT 5;
```

---

## Step 6: Apple Calendar (One-Time Manual Setup)

Google Calendar events automatically appear in Apple Calendar if you subscribe:

1. On your Mac/iPhone, open Calendar settings
2. Add Account → Google → sign in with seb@falconfinancial.org
3. Or: subscribe to the Google Calendar via iCal URL

The 5-minute popup reminder set on Google Calendar events will fire natively in Apple Calendar.

---

## SMS Message Templates

**Confirmation** (sent immediately):
> Hi {first_name}, this is Seb from Falcon Financial. Just confirming our appointment on {day} at {time}. Looking forward to speaking with you! Reply STOP to opt out.

**24hr Reminder** (scheduled):
> Hi {first_name}, just a reminder — we have an appointment tomorrow at {time}. Talk soon! - Seb, Falcon Financial. Reply STOP to opt out.

**1hr Reminder** (scheduled):
> Hi {first_name}, our appointment is in about an hour at {time}. Talk soon! - Seb. Reply STOP to opt out.

Times are formatted in the prospect's timezone based on the Timezone field on the activity (ET, CT, MT, PT, AZ). Falls back to AZ if not set.

---

## Rebooking

If the appointment datetime changes on the same lead (updated activity):
1. Old scheduled SMS are cancelled (24hr and 1hr reminders)
2. Old Google Calendar event is deleted
3. New confirmation SMS sent
4. New reminders scheduled
5. New Google Calendar event created

The confirmation SMS that was already sent cannot be unsent — that's expected.

---

## Troubleshooting

**No SMS sent:**
- Check `CLOSE_API_KEY` and `CLOSE_SMS_FROM_NUMBER` are set
- Verify the contact has a phone number
- Check Close SMS settings (Twilio must be connected)

**No Google Calendar event:**
- Run `scripts/test_gcal.py` to verify the service account connection
- Ensure the calendar is shared with the service account email
- Check `GOOGLE_SERVICE_ACCOUNT_JSON` is valid JSON

**Webhook not firing:**
- Verify the webhook URL in Close settings: `https://falconnect.org/webhooks/close`
- Check the webhook is subscribed to activity events
- Check Render logs for incoming requests

**Calendar event not linking to Close lead:**
- The dummy email (`lead-{id}@appointments.falconfinancial.org`) must be on the contact
- Close's calendar sync can take a few minutes to pick up the link
- Verify the email was added: check the contact's email list in Close
