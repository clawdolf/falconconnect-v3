#!/usr/bin/env python3
"""Build the GHL Day 0 RVM workflow via API (or document manual steps).

GHL Workflow API limitations:
- GHL's v2 Workflow API (2021-07-28) does NOT support programmatic workflow
  creation or step editing. The API only supports:
    GET /workflows/ — list workflows
    GET /workflows/{id} — get workflow details
- Creating workflows, adding steps (RVM, SMS, wait, tag, webhook) must be
  done through the GHL web UI.

This script:
1. Documents all steps that need to be manually configured in GHL
2. Creates a reference config that Seb can follow step-by-step
3. Verifies any existing workflows via the API to check if one was already built
4. Outputs the full Day 0 workflow spec for manual UI setup

Usage:
  python3 scripts/build_ghl_rvm_workflow.py

  # Check existing workflows:
  python3 scripts/build_ghl_rvm_workflow.py --check-existing

Requires:
  GHL_API_KEY and GHL_LOCATION_ID env vars (or hardcoded below)
"""

import argparse
import json
import os
import subprocess
import sys

# GHL credentials
GHL_LOCATION_ID = os.environ.get("GHL_LOCATION_ID", "klcOunQEpXg6QAM2E4VN")
GHL_API_KEY = os.environ.get("GHL_API_KEY", "pit-ec51ce5c-7de9-4f0f-8c86-8670d8108192")

GHL_BASE = "https://services.leadconnectorhq.com"
GHL_API_VERSION = "2021-07-28"

# FC webhook URL for rvm-complete callback
FC_WEBHOOK_URL = "https://falconnect.org/api/ghl/rvm-complete"

# Day 0 SMS text (from Variant A spec)
DAY0_SMS = (
    "Hey {{contact.first_name}}, this is Seb from Falcon Financial."
    " Left you a quick voicemail about your mortgage protection."
    " Happy to answer questions — reply anytime."
)

# Day 0 VM script (for Seb to record)
DAY0_VM_SCRIPT = (
    "Hey [Name], this is Seb with Falcon Financial. You sent back a card "
    "about protecting your mortgage — just wanted to follow up and make "
    "sure you got the information you needed. Give me a call back when "
    "you get a chance. Talk soon."
)


def ghl_curl(endpoint: str, method: str = "GET", data: dict = None) -> dict:
    """Make a GHL API call via curl subprocess (Cloudflare blocks Python urllib).

    Returns parsed JSON response or error dict.
    """
    url = f"{GHL_BASE}{endpoint}"
    cmd = [
        "curl", "-s", "-X", method,
        url,
        "-H", f"Authorization: Bearer {GHL_API_KEY}",
        "-H", f"Version: {GHL_API_VERSION}",
        "-H", "Content-Type: application/json",
        "-H", "Accept: application/json",
    ]

    if data:
        cmd.extend(["-d", json.dumps(data)])

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        if result.returncode != 0:
            return {"error": f"curl failed: {result.stderr}"}
        return json.loads(result.stdout)
    except json.JSONDecodeError:
        return {"error": f"Invalid JSON: {result.stdout[:500]}"}
    except subprocess.TimeoutExpired:
        return {"error": "curl timed out"}
    except Exception as exc:
        return {"error": str(exc)}


def check_existing_workflows():
    """List existing GHL workflows to check if Day 0 already exists."""
    print("Checking existing GHL workflows...")
    resp = ghl_curl(f"/workflows/?locationId={GHL_LOCATION_ID}")

    if "error" in resp:
        print(f"  ERROR: {resp['error']}")
        return []

    workflows = resp.get("workflows", [])
    if not workflows:
        print("  No workflows found.")
        return []

    print(f"  Found {len(workflows)} workflow(s):")
    for wf in workflows:
        name = wf.get("name", "Unnamed")
        wf_id = wf.get("id", "?")
        status = wf.get("status", "?")
        print(f"    [{status}] {name} (id: {wf_id})")

    # Check if our workflow already exists
    for wf in workflows:
        if "blitz" in wf.get("name", "").lower() or "falcon" in wf.get("name", "").lower():
            print(f"\n  ** Possible match: '{wf['name']}' (id: {wf['id']})")

    return workflows


def print_workflow_spec():
    """Print the full Day 0 workflow specification for manual GHL UI setup."""
    print("""
================================================================================
  FALCON BLITZ DAY 0 — GHL Workflow Configuration
================================================================================

  Workflow Name: "Falcon Blitz Day 0"
  Status: INACTIVE (activate after inserting recording ID)

  TRIGGER:
    Type: Contact Tag
    Condition: Tag Added = "r0-pending"

  STEPS (in order):

  ┌─────────────────────────────────────────────────────────────────────────┐
  │ STEP 1: Wait                                                           │
  │   Duration: 0 minutes                                                  │
  │   (Immediate — no delay after trigger)                                 │
  └─────────────────────────────────────────────────────────────────────────┘

  ┌─────────────────────────────────────────────────────────────────────────┐
  │ STEP 2: Ringless Voicemail (RVM)                                       │
  │                                                                        │
  │   ** INSERT RECORDING ID HERE BEFORE ACTIVATING **                     │
  │                                                                        │
  │   Recording: [Seb records this — ~25 seconds]                          │
  │   Script for recording:                                                │
  │                                                                        │
  │   "Hey [Name], this is Seb with Falcon Financial. You sent back a      │
  │    card about protecting your mortgage — just wanted to follow up       │
  │    and make sure you got the information you needed. Give me a call     │
  │    back when you get a chance. Talk soon."                              │
  │                                                                        │
  │   From number: Use Seb's primary number or toll-free +18446813690      │
  │   To: {{contact.phone}}                                                │
  └─────────────────────────────────────────────────────────────────────────┘

  ┌─────────────────────────────────────────────────────────────────────────┐
  │ STEP 3: Wait                                                           │
  │   Duration: 45 seconds                                                 │
  │   (Brief delay so VM lands before SMS)                                 │
  └─────────────────────────────────────────────────────────────────────────┘

  ┌─────────────────────────────────────────────────────────────────────────┐
  │ STEP 4: Send SMS                                                       │
  │                                                                        │
  │   Message:                                                             │
  │   "Hey {{contact.first_name}}, this is Seb from Falcon Financial.      │
  │    Left you a quick voicemail about your mortgage protection.           │
  │    Happy to answer questions — reply anytime."                         │
  │                                                                        │
  │   From number: Same as RVM step                                        │
  │   To: {{contact.phone}}                                                │
  │   Characters: ~145                                                     │
  └─────────────────────────────────────────────────────────────────────────┘

  ┌─────────────────────────────────────────────────────────────────────────┐
  │ STEP 5: Remove Tag                                                     │
  │   Tag to remove: "r0-pending"                                          │
  └─────────────────────────────────────────────────────────────────────────┘

  ┌─────────────────────────────────────────────────────────────────────────┐
  │ STEP 6: Add Tag                                                        │
  │   Tag to add: "r0-complete"                                            │
  └─────────────────────────────────────────────────────────────────────────┘

  ┌─────────────────────────────────────────────────────────────────────────┐
  │ STEP 7: Webhook                                                        │
  │   Method: POST                                                         │
  │   URL: {fc_url}
  │   Headers:                                                             │
  │     X-GHL-Webhook-Secret: [your GHL_WEBHOOK_SECRET value]              │
  │     Content-Type: application/json                                     │
  │   Body: (GHL auto-sends contact data in webhook payload)               │
  │                                                                        │
  │   This triggers FC to create/update the lead in Close with             │
  │   cadence_stage = r1-to-call                                           │
  └─────────────────────────────────────────────────────────────────────────┘

  NOTES:
  - The RVM step (Step 2) needs Seb's recording ID inserted before activation
  - SMS in Step 4 requires A2P 10DLC approval for consistent delivery
  - The webhook in Step 7 calls FC which creates the Close lead automatically
  - Workflow should run during TCPA-compliant hours only (8am-9pm local time)
  - Add a "Contact Replied" stop trigger to halt workflow if prospect responds

================================================================================
""".format(fc_url=FC_WEBHOOK_URL))


def print_sms_preview():
    """Print the Day 0 SMS preview."""
    print("Day 0 SMS Preview:")
    print(f"  {DAY0_SMS}")
    print(f"  Characters: {len(DAY0_SMS)}")
    print()
    print("Day 0 VM Script (for Seb to record):")
    print(f"  {DAY0_VM_SCRIPT}")
    word_count = len(DAY0_VM_SCRIPT.split())
    print(f"  Words: {word_count} (~{word_count * 0.4:.0f} seconds at natural pace)")


def main():
    parser = argparse.ArgumentParser(
        description="GHL Day 0 RVM workflow builder / documentation tool"
    )
    parser.add_argument(
        "--check-existing",
        action="store_true",
        help="Check for existing workflows in GHL",
    )
    parser.add_argument(
        "--sms-preview",
        action="store_true",
        help="Preview Day 0 SMS and VM script",
    )
    args = parser.parse_args()

    print("=" * 72)
    print("  Falcon Blitz Day 0 — GHL RVM Workflow Builder")
    print("=" * 72)
    print()

    if args.check_existing:
        check_existing_workflows()
        print()

    if args.sms_preview:
        print_sms_preview()
        print()
        return

    # Main flow: print the spec and check existing
    print("GHL Workflow API Status:")
    print("  The GHL v2 API (2021-07-28) does NOT support programmatic")
    print("  workflow creation. Workflows must be built in the GHL web UI.")
    print("  This script documents the exact configuration for manual setup.")
    print()

    workflows = check_existing_workflows()
    print()

    print_workflow_spec()

    print_sms_preview()
    print()

    # Summary
    print("=" * 72)
    print("  NEXT STEPS")
    print("=" * 72)
    print()
    print("  1. Open GHL → Automation → Workflows → Create Workflow")
    print("  2. Follow the step-by-step spec above")
    print("  3. Seb records VM-0 (~25 seconds) and uploads to GHL")
    print("  4. Insert the recording ID into Step 2 (RVM)")
    print("  5. Set workflow status to ACTIVE")
    print("  6. Test with a single contact tagged 'r0-pending'")
    print("  7. Verify FC webhook fires and Close lead is created")
    print()
    print("  BLOCKED: A2P 10DLC approval needed for SMS delivery (Step 4)")
    print("  BLOCKED: Seb's VM recording needed for RVM (Step 2)")
    print()

    if workflows:
        existing_names = [w.get("name", "") for w in workflows]
        if any("blitz" in n.lower() or "falcon" in n.lower() for n in existing_names):
            print("  WARNING: A potentially matching workflow already exists in GHL.")
            print("  Check if it needs to be updated rather than creating a new one.")


if __name__ == "__main__":
    main()
