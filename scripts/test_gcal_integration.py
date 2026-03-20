#!/usr/bin/env python3
"""GCal integration diagnostic test.

Loads credentials from render-falconconnect-envvars.json, creates a test event,
verifies it exists, deletes it, and reports pass/fail with exact errors.
"""

import json
import sys
import traceback
from datetime import datetime, timedelta, timezone


CREDS_PATH = "/Users/clawdolf/.openclaw/credentials/render-falconconnect-envvars.json"


def load_creds():
    """Load Google creds from render env vars JSON."""
    with open(CREDS_PATH) as f:
        env_vars = json.load(f)
    creds = {}
    for item in env_vars:
        creds[item["key"]] = item["value"]
    return creds


def test_gcal():
    """Full GCal integration test."""
    print("=" * 60)
    print("GCal Integration Diagnostic Test")
    print("=" * 60)
    
    # Step 1: Load credentials
    print("\n[1/6] Loading credentials...")
    creds = load_creds()
    
    client_id = creds.get("GOOGLE_CLIENT_ID", "")
    client_secret = creds.get("GOOGLE_CLIENT_SECRET", "")
    refresh_token = creds.get("GOOGLE_REFRESH_TOKEN", "")
    calendar_id = creds.get("GOOGLE_CALENDAR_ID", "primary")
    
    print(f"  GOOGLE_CLIENT_ID: {'SET' if client_id else 'MISSING'} ({client_id[:20]}...)")
    print(f"  GOOGLE_CLIENT_SECRET: {'SET' if client_secret else 'MISSING'} ({client_secret[:10]}...)")
    print(f"  GOOGLE_REFRESH_TOKEN: {'SET' if refresh_token else 'MISSING'} ({refresh_token[:20]}...)")
    print(f"  GOOGLE_CALENDAR_ID: {calendar_id}")
    
    if not all([client_id, client_secret, refresh_token]):
        print("\n  FAIL: Missing required credentials")
        return False
    
    # Step 2: Build credentials object
    print("\n[2/6] Building OAuth credentials...")
    try:
        from google.oauth2.credentials import Credentials
        credentials = Credentials(
            token=None,
            refresh_token=refresh_token,
            token_uri="https://oauth2.googleapis.com/token",
            client_id=client_id,
            client_secret=client_secret,
            scopes=["https://www.googleapis.com/auth/calendar"],
        )
        print(f"  Credentials object created OK")
        print(f"  Token: {credentials.token}")
        print(f"  Valid: {credentials.valid}")
        print(f"  Expired: {credentials.expired}")
    except Exception as exc:
        print(f"  FAIL: {exc}")
        traceback.print_exc()
        return False
    
    # Step 3: Build Calendar service
    print("\n[3/6] Building Calendar API service...")
    try:
        from googleapiclient.discovery import build
        service = build("calendar", "v3", credentials=credentials)
        print(f"  Service built OK")
    except Exception as exc:
        print(f"  FAIL: {exc}")
        traceback.print_exc()
        return False
    
    # Step 4: Test token refresh by listing calendars
    print("\n[4/6] Testing token refresh + calendar access...")
    try:
        calendar_list = service.calendarList().list().execute()
        calendars = calendar_list.get("items", [])
        print(f"  Token refresh: OK (token now set: {bool(credentials.token)})")
        print(f"  Calendars found: {len(calendars)}")
        for cal in calendars[:5]:
            print(f"    - {cal.get('summary', 'N/A')} (id: {cal.get('id', 'N/A')[:40]})")
        
        # Check if calendar_id is accessible
        if calendar_id == "primary":
            print(f"  Using 'primary' calendar — resolves to the default calendar")
        else:
            found = any(c.get("id") == calendar_id for c in calendars)
            print(f"  Calendar ID '{calendar_id}' found: {found}")
            if not found:
                print(f"  WARNING: Calendar ID not in list — may fail!")
    except Exception as exc:
        print(f"  FAIL: {exc}")
        traceback.print_exc()
        # Try to get more detail
        if hasattr(exc, 'content'):
            print(f"  Response content: {exc.content}")
        return False
    
    # Step 5: Create a test event
    print("\n[5/6] Creating test event...")
    test_start = datetime.now(timezone.utc) + timedelta(hours=24)
    test_end = test_start + timedelta(minutes=30)
    
    event_body = {
        "summary": "DOLF TEST EVENT — DELETE ME",
        "description": "Automated GCal integration test from FalconConnect diagnostics",
        "start": {
            "dateTime": test_start.isoformat(),
            "timeZone": "UTC",
        },
        "end": {
            "dateTime": test_end.isoformat(),
            "timeZone": "UTC",
        },
        "reminders": {
            "useDefault": False,
            "overrides": [
                {"method": "popup", "minutes": 5},
            ],
        },
    }
    
    try:
        result = service.events().insert(
            calendarId=calendar_id,
            body=event_body,
            sendUpdates="none",
        ).execute()
        event_id = result.get("id")
        event_link = result.get("htmlLink")
        print(f"  Event created OK!")
        print(f"  Event ID: {event_id}")
        print(f"  HTML Link: {event_link}")
        print(f"  Start: {result.get('start', {}).get('dateTime')}")
    except Exception as exc:
        print(f"  FAIL: {exc}")
        traceback.print_exc()
        if hasattr(exc, 'content'):
            print(f"  Response content: {exc.content}")
        if hasattr(exc, 'resp'):
            print(f"  Response status: {exc.resp.status}")
        return False
    
    # Step 6: Verify and delete
    print("\n[6/6] Verifying event exists, then deleting...")
    try:
        fetched = service.events().get(
            calendarId=calendar_id,
            eventId=event_id,
        ).execute()
        print(f"  Verification: Event exists (summary: {fetched.get('summary')})")
    except Exception as exc:
        print(f"  FAIL on verification: {exc}")
        traceback.print_exc()
        return False
    
    try:
        service.events().delete(
            calendarId=calendar_id,
            eventId=event_id,
            sendUpdates="none",
        ).execute()
        print(f"  Deletion: OK")
    except Exception as exc:
        print(f"  Deletion failed (non-critical): {exc}")
    
    print("\n" + "=" * 60)
    print("RESULT: ALL TESTS PASSED")
    print("=" * 60)
    print("\nGCal API is working correctly with these credentials.")
    print("If events aren't appearing in production, the issue is in")
    print("the server-side code path, not the credentials.")
    return True


if __name__ == "__main__":
    success = test_gcal()
    sys.exit(0 if success else 1)
