#!/usr/bin/env python3
"""Standalone cadence SMS sender — runs outside FC (for Close workflows or cron).

Usage:
  python3 scripts/close_sms_send.py --lead-id lead_xxx --sms-template sms1 --cadence-stage-next r2-to-call

What it does:
  1. Fetches lead from Close (contact phone, name, state)
  2. Picks the correct local_phone based on lead's state
  3. Renders SMS template with lead name and state
  4. Sends SMS via Close API (status=outbox)
  5. Updates cadence_stage to the specified next value
  6. Logs result to stdout

Requires:
  CLOSE_API_KEY env var (or source from ~/.openclaw/credentials/close-api.env)
"""

import argparse
import json
import os
import sys
from typing import Optional

# Load credentials from env file if not already set
_cred_path = os.path.expanduser("~/.openclaw/credentials/close-api.env")
if os.path.isfile(_cred_path) and not os.environ.get("CLOSE_API_KEY"):
    with open(_cred_path) as f:
        for line in f:
            line = line.strip()
            if line and "=" in line and not line.startswith("#"):
                key, val = line.split("=", 1)
                os.environ[key.strip()] = val.strip()

CLOSE_API_KEY = os.environ.get("CLOSE_API_KEY", "")
if not CLOSE_API_KEY:
    print("ERROR: CLOSE_API_KEY not set. Export it or place in ~/.openclaw/credentials/close-api.env")
    sys.exit(1)

CLOSE_API_BASE = "https://api.close.com/api/v1"

# Close custom field ID for Cadence Stage
CF_CADENCE_STAGE = "cf_vuP2rYRL0LA3OK0nCyZm9b19ki8ddokdTAapVnJ2Elb"

# SMS templates — Variant A (Aggressive Blitz)
SMS_TEMPLATES = {
    "sms1": (
        "Hey {first_name}, tried reaching you yesterday"
        " — easier to connect by text? Just takes a couple"
        " minutes to see what coverage looks like for you."
    ),
    "sms2": (
        "Most homeowners in {state} don't realize their mortgage"
        " has zero protection if something happens. Took 2 min"
        " to fix that for a family last week."
    ),
    "sms3": (
        "Hey {first_name}, still happy to walk you through what"
        " mortgage protection would look like for your home."
        " Quick call, no pressure. -Seb"
    ),
    "sms4": (
        "Last one from me"
        " — if the timing's ever right, I'm here. -Seb"
    ),
}

# State → Twilio number mapping (Seb's ported numbers in Close)
STATE_PHONE_MAP = {
    "AZ": "+14809999040",
    "MT": "+14066463344",
    "NC": "+19808909888",
    "ME": "+12078881046",
    "KS": "+19133793347",
    "OR": "+19719993141",
    "TX": "+18322429026",
    "PA": "+12156077444",
    "FL": "+17862548006",
    "CA": "+13502473286",
}

TOLL_FREE = "+18446813690"


def _auth():
    """Return (api_key, '') for requests basic auth."""
    return (CLOSE_API_KEY, "")


def _resolve_from_number(state: str) -> str:
    """Pick outbound number based on lead's state. Falls back to toll-free."""
    if not state:
        return TOLL_FREE
    return STATE_PHONE_MAP.get(state.upper().strip(), TOLL_FREE)


def get_lead(lead_id: str) -> Optional[dict]:
    """Fetch lead from Close API (synchronous via urllib)."""
    import urllib.request
    import base64

    auth_str = base64.b64encode(f"{CLOSE_API_KEY}:".encode()).decode()
    req = urllib.request.Request(
        f"{CLOSE_API_BASE}/lead/{lead_id}/",
        headers={
            "Authorization": f"Basic {auth_str}",
            "Content-Type": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode())
    except Exception as exc:
        print(f"ERROR: Failed to fetch lead {lead_id}: {exc}")
        return None


def extract_lead_info(lead: dict) -> dict:
    """Extract contact info from Close lead."""
    contacts = lead.get("contacts", [])
    contact = contacts[0] if contacts else {}
    contact_id = contact.get("id", "")

    full_name = contact.get("name", lead.get("display_name", ""))
    first_name = full_name.strip().split()[0] if full_name else "there"

    phones = contact.get("phones", [])
    phone = phones[0].get("phone", "") if phones else ""

    addresses = lead.get("addresses", [])
    state = addresses[0].get("state", "") if addresses else ""

    return {
        "contact_id": contact_id,
        "first_name": first_name,
        "phone": phone,
        "state": state,
    }


def send_sms(lead_id: str, contact_id: str, from_number: str, to_number: str, text: str) -> Optional[str]:
    """Send SMS via Close API (synchronous). Returns SMS ID or None."""
    import urllib.request
    import base64

    auth_str = base64.b64encode(f"{CLOSE_API_KEY}:".encode()).decode()
    payload = json.dumps({
        "lead_id": lead_id,
        "contact_id": contact_id,
        "local_phone": from_number,
        "remote_phone": to_number,
        "text": text,
        "status": "outbox",
        "direction": "outbound",
    }).encode()

    req = urllib.request.Request(
        f"{CLOSE_API_BASE}/activity/sms/",
        data=payload,
        headers={
            "Authorization": f"Basic {auth_str}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode())
            sms_id = data.get("id", "")
            print(f"OK: SMS sent — id={sms_id} from={from_number} to={to_number}")
            return sms_id
    except Exception as exc:
        print(f"ERROR: SMS send failed: {exc}")
        return None


def update_cadence_stage(lead_id: str, stage: str) -> bool:
    """Update cadence_stage on Close lead (synchronous)."""
    import urllib.request
    import base64

    auth_str = base64.b64encode(f"{CLOSE_API_KEY}:".encode()).decode()
    payload = json.dumps({f"custom.{CF_CADENCE_STAGE}": stage}).encode()

    req = urllib.request.Request(
        f"{CLOSE_API_BASE}/lead/{lead_id}/",
        data=payload,
        headers={
            "Authorization": f"Basic {auth_str}",
            "Content-Type": "application/json",
        },
        method="PUT",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            print(f"OK: cadence_stage updated to '{stage}' on lead {lead_id}")
            return True
    except Exception as exc:
        print(f"ERROR: cadence_stage update failed: {exc}")
        return False


def main():
    parser = argparse.ArgumentParser(description="Send cadence SMS via Close API")
    parser.add_argument("--lead-id", required=True, help="Close lead ID (lead_xxx)")
    parser.add_argument(
        "--sms-template",
        required=True,
        choices=list(SMS_TEMPLATES.keys()),
        help="SMS template to use",
    )
    parser.add_argument(
        "--cadence-stage-next",
        required=True,
        help="Cadence stage to set after SMS (e.g., r2-to-call)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print what would be sent without actually sending",
    )
    args = parser.parse_args()

    # 1. Fetch lead
    print(f"Fetching lead {args.lead_id}...")
    lead = get_lead(args.lead_id)
    if not lead:
        sys.exit(1)

    info = extract_lead_info(lead)
    print(f"  Name: {info['first_name']}")
    print(f"  Phone: {info['phone']}")
    print(f"  State: {info['state']}")
    print(f"  Contact ID: {info['contact_id']}")

    if not info["phone"]:
        print("ERROR: No phone number on lead — aborting")
        sys.exit(1)

    if not info["contact_id"]:
        print("ERROR: No contact on lead — aborting")
        sys.exit(1)

    # 2. Resolve outbound number
    from_number = _resolve_from_number(info["state"])
    print(f"  From number: {from_number} (state={info['state'] or 'unknown'})")

    # 3. Render template
    template = SMS_TEMPLATES[args.sms_template]
    sms_text = template.format(first_name=info["first_name"], state=info["state"])
    print(f"  Template: {args.sms_template}")
    print(f"  Message: {sms_text}")
    print(f"  Characters: {len(sms_text)}")

    if args.dry_run:
        print("\n[DRY RUN] Would send SMS and update stage — no action taken.")
        return

    # 4. Send SMS
    print(f"\nSending SMS...")
    sms_id = send_sms(
        lead_id=args.lead_id,
        contact_id=info["contact_id"],
        from_number=from_number,
        to_number=info["phone"],
        text=sms_text,
    )

    if not sms_id:
        print("FAILED: SMS not sent — aborting stage update")
        sys.exit(1)

    # 5. Update cadence stage
    print(f"Updating cadence_stage to '{args.cadence_stage_next}'...")
    if not update_cadence_stage(args.lead_id, args.cadence_stage_next):
        print("WARNING: SMS sent but stage update failed — manual fix needed")
        sys.exit(1)

    print(f"\nDONE: SMS={sms_id} stage={args.cadence_stage_next}")


if __name__ == "__main__":
    main()
