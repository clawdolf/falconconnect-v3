#!/usr/bin/env python3
"""Test Google Calendar service account connection.

Creates a test event, verifies it exists, then deletes it.

Usage:
    GOOGLE_SERVICE_ACCOUNT_JSON='{"type":"service_account",...}' python3 scripts/test_gcal.py

Or if the JSON is in a file:
    GOOGLE_SERVICE_ACCOUNT_JSON=$(cat /path/to/service-account.json) python3 scripts/test_gcal.py
"""

import json
import os
import sys
from datetime import datetime, timedelta, timezone

def main():
    sa_json = os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON")
    calendar_id = os.environ.get("GOOGLE_CALENDAR_ID", "primary")

    if not sa_json:
        print("ERROR: Set GOOGLE_SERVICE_ACCOUNT_JSON environment variable")
        print("       (contents of the service account JSON key file)")
        sys.exit(1)

    try:
        creds_info = json.loads(sa_json)
    except json.JSONDecodeError as e:
        print(f"ERROR: GOOGLE_SERVICE_ACCOUNT_JSON is not valid JSON: {e}")
        sys.exit(1)

    print(f"Service account email: {creds_info.get('client_email')}")
    print(f"Project ID: {creds_info.get('project_id')}")
    print(f"Calendar ID: {calendar_id}")
    print()

    # Build credentials and service
    try:
        from google.oauth2 import service_account
        from googleapiclient.discovery import build
    except ImportError:
        print("ERROR: Missing google-auth or google-api-python-client")
        print("       pip install google-auth google-api-python-client google-auth-httplib2")
        sys.exit(1)

    credentials = service_account.Credentials.from_service_account_info(
        creds_info,
        scopes=["https://www.googleapis.com/auth/calendar"],
    )

    service = build("calendar", "v3", credentials=credentials)

    # Test 1: List calendars to verify access
    print("1. Testing calendar access...")
    try:
        cal = service.calendars().get(calendarId=calendar_id).execute()
        print(f"   Calendar: {cal.get('summary', calendar_id)}")
        print(f"   Timezone: {cal.get('timeZone')}")
    except Exception as e:
        print(f"   FAILED: {e}")
        print()
        print("   Make sure you've shared the calendar with the service account email.")
        print(f"   Service account: {creds_info.get('client_email')}")
        print("   Required access: 'Make changes to events' (editor)")
        sys.exit(1)

    # Test 2: Create a test event
    print("2. Creating test event...")
    start = datetime.now(timezone.utc) + timedelta(hours=24)
    end = start + timedelta(minutes=30)

    event_body = {
        "summary": "[TEST] FalconConnect GCal Integration Test",
        "description": "This is a test event — safe to delete.",
        "start": {"dateTime": start.isoformat(), "timeZone": "UTC"},
        "end": {"dateTime": end.isoformat(), "timeZone": "UTC"},
    }

    try:
        created = service.events().insert(
            calendarId=calendar_id,
            body=event_body,
            sendUpdates="none",
        ).execute()
        event_id = created["id"]
        print(f"   Created event: {event_id}")
        print(f"   Link: {created.get('htmlLink')}")
    except Exception as e:
        print(f"   FAILED to create event: {e}")
        sys.exit(1)

    # Test 3: Delete the test event
    print("3. Deleting test event...")
    try:
        service.events().delete(
            calendarId=calendar_id,
            eventId=event_id,
            sendUpdates="none",
        ).execute()
        print(f"   Deleted event: {event_id}")
    except Exception as e:
        print(f"   FAILED to delete: {e}")
        print(f"   Please delete event {event_id} manually.")
        sys.exit(1)

    print()
    print("All tests passed. Google Calendar integration is working.")


if __name__ == "__main__":
    main()
