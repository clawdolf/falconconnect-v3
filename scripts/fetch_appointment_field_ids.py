#!/usr/bin/env python3
"""List every custom activity type in Close and all their fields.

Use to discover cf_... IDs (and actitype_... IDs) after adding new
fields/activities in the Close UI.

Usage:
    CLOSE_API_KEY=xxx python3 scripts/fetch_appointment_field_ids.py
"""

import os
import sys

import httpx

BASE_URL = "https://api.close.com/api/v1"


def main():
    api_key = os.environ.get("CLOSE_API_KEY")
    if not api_key:
        print("ERROR: Set CLOSE_API_KEY environment variable")
        sys.exit(1)

    types_resp = httpx.get(
        f"{BASE_URL}/custom_activity/",
        params={"_limit": 100},
        auth=(api_key, ""),
        timeout=30.0,
    )
    if types_resp.status_code != 200:
        print(f"ERROR: GET /custom_activity/ returned {types_resp.status_code}: {types_resp.text[:500]}")
        sys.exit(1)

    activity_types = types_resp.json().get("data", [])
    if not activity_types:
        print("No custom activity types found.")
        sys.exit(1)

    fields_resp = httpx.get(
        f"{BASE_URL}/custom_field/activity/",
        params={"_limit": 200},
        auth=(api_key, ""),
        timeout=30.0,
    )
    if fields_resp.status_code != 200:
        print(f"ERROR: GET /custom_field/activity/ returned {fields_resp.status_code}: {fields_resp.text[:500]}")
        sys.exit(1)

    all_fields = fields_resp.json().get("data", [])

    fields_by_type: dict[str, list[dict]] = {}
    for field in all_fields:
        ata_id = field.get("custom_activity_type_id") or "(unknown)"
        fields_by_type.setdefault(ata_id, []).append(field)

    for at in activity_types:
        at_id = at.get("id", "?")
        at_name = at.get("name", "?")
        print(f"=== {at_name}  ->  {at_id} ===")
        for field in fields_by_type.get(at_id, []):
            name = field.get("name", "?")
            field_id = field.get("id", "?")
            ftype = field.get("type", "?")
            choices = field.get("choices") or []
            print(f"  {name!r}  ->  {field_id}")
            print(f"      type: {ftype}")
            if choices:
                print(f"      choices: {choices}")
        if not fields_by_type.get(at_id):
            print("  (no custom fields)")
        print()


if __name__ == "__main__":
    main()
