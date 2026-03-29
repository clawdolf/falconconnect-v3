#!/usr/bin/env python3
"""Register Close.com lead status webhook — run once.

Creates a webhook subscription that fires on lead.updated events,
sending payloads to the FC kill-switch endpoint.

Usage:
  python3 scripts/register_close_webhook.py

Requires:
  CLOSE_API_KEY env var (or reads from ~/.openclaw/credentials/close-api.env)
"""

import os
import sys

import httpx

# Load credentials from env file if not already set
_cred_path = os.path.expanduser("~/.openclaw/credentials/close-api.env")
if os.path.isfile(_cred_path) and not os.environ.get("CLOSE_API_KEY"):
    with open(_cred_path) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, val = line.split("=", 1)
                os.environ[key.strip()] = val.strip()

API_KEY = os.environ.get("CLOSE_API_KEY", "")
if not API_KEY:
    print("ERROR: CLOSE_API_KEY not set")
    sys.exit(1)

ENDPOINT = "https://falconconnect.org/api/close/lead-status"

resp = httpx.post(
    "https://api.close.com/api/v1/webhook/",
    auth=(API_KEY, ""),
    json={
        "url": ENDPOINT,
        "events": [
            {"object_type": "lead", "action": "updated"},
        ],
    },
)
print(f"Status: {resp.status_code}")
print(f"Response: {resp.json()}")

if resp.status_code in (200, 201):
    data = resp.json()
    print(f"\nWebhook registered successfully!")
    print(f"  Subscription ID: {data.get('id', 'unknown')}")
    print(f"  Signature Key: {data.get('signature_key', 'NOT RETURNED')}")
    print(f"\n  IMPORTANT: Save the signature_key as CLOSE_WEBHOOK_SECRET in Render env vars")
    print(f"  if you haven't already configured one.")
else:
    print(f"\nWebhook registration FAILED — check API key and endpoint.")
