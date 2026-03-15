#!/usr/bin/env python3
"""Verify the Book Appointment custom activity exists in Close.com.

The activity was already created — this script confirms it's accessible
and prints the field IDs for reference.

Usage:
    CLOSE_API_KEY=xxx python3 scripts/setup_close_activity.py
"""

import os
import sys

import httpx

BASE_URL = "https://api.close.com/api/v1"

# Known IDs (created 2026-03-15)
ACTIVITY_TYPE_ID = "actitype_6awVkZoRuXH1FWUd1F97CH"
CF_DATETIME = "cf_iiDP2BjqqEApsTl1uGQqbzw2cWm5Le8r3wTuUC8uc5Z"
CF_NOTES = "cf_WEM8v7zGSnCDPIEQuxNmdct5l5i19kCRoPCX5BexLqa"
CF_TIMEZONE = "cf_mqWOudG1Apd6FdrzP2qZqC1qUgx0pvGLKg4ZZgFsmn7"


def main():
    api_key = os.environ.get("CLOSE_API_KEY")
    if not api_key:
        print("ERROR: Set CLOSE_API_KEY environment variable")
        sys.exit(1)

    print(f"Verifying activity type: {ACTIVITY_TYPE_ID}")

    resp = httpx.get(
        f"{BASE_URL}/custom_activity/{ACTIVITY_TYPE_ID}/",
        auth=(api_key, ""),
        timeout=30.0,
    )

    if resp.status_code == 200:
        data = resp.json()
        print(f"  Name: {data.get('name')}")
        print(f"  ID:   {data.get('id')}")
        print(f"  Org:  {data.get('organization_id')}")
        print()
        print("Custom field IDs:")
        print(f"  appointment_datetime: {CF_DATETIME}")
        print(f"  notes:               {CF_NOTES}")
        print(f"  timezone:            {CF_TIMEZONE}")
        print()
        print("Activity type verified successfully.")
    elif resp.status_code == 404:
        print("ERROR: Activity type not found. It may have been deleted.")
        sys.exit(1)
    else:
        print(f"ERROR: Close API returned {resp.status_code}: {resp.text[:300]}")
        sys.exit(1)


if __name__ == "__main__":
    main()
