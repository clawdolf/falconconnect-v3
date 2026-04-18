"""Close.com API client — creates Leads from the ad landing-page flow.

Policy (as of 2026-04 audit):

- A Close Lead is created with status `New Lead` on first submission.
- An Opportunity is **not** created. Opportunities are created later in
  Close once a lead is actually qualified — creating one on form submit
  with status `Options Presented` polluted pipeline metrics.
- `state` is written to the native Close Contact `addresses` field, not a
  custom field.
- `is_homeowner` is no longer collected by the form and is therefore not
  written.
- SMS consent is captured as a single combined choice (`yes`/`no`) with a
  timestamp and the submitter's IP, for TCPA/A2P audit.
- Ad click IDs (`fbclid`, `gclid`, `ttclid`) and the full landing-page URL
  are captured for attribution and are stored as custom fields.
- Dedup: before creating, we search Close for an existing Lead by the
  submitter's phone or email. If found, we post a Note to that Lead with
  the new submission context (attribution + consent) and skip the create.
  This avoids duplicate lead records when someone fills out a second form
  from a different campaign.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Optional

import httpx

from config import get_settings

logger = logging.getLogger("falconconnect.close")

# ---------------------------------------------------------------------------
# Close.com Custom Field IDs (stable — created once, never change)
# ---------------------------------------------------------------------------

# Attribution (created 2026-03-14)
CF_UTM_SOURCE = "cf_Gjgzr7FkkeBhOE2Mlt8QGwNpT7mEY3YAIByFow8yMVz"
CF_UTM_MEDIUM = "cf_BdVfTFVsMY9Uk45ZpLM4fUfskc7g4b7IKOiZCuDdZ8I"
CF_UTM_CAMPAIGN = "cf_7nVp5tmtpfcM6VZnge0WqB67pt5s2hcIXs1RbTuxtzD"
CF_UTM_CONTENT = "cf_5NFr6MwVguhV9vKa9d4rMxRy7ybWLxbaaSHMl1Wux8L"
CF_AD_PLATFORM = "cf_kjMHO5vxvfqDEN0i9xmkRIBM5h74YhfTnW900ckdGqq"
CF_LEAD_FORM_VARIANT = "cf_TLZpT49XI24ub6XkvteT34yCb9Gzgcozq8UEuRnZ5MO"

# Lead metadata
CF_LEAD_SOURCE = "cf_7ad3Cfpj2UDg5dEjJ6LDe9P5FZP8GcCyhaGSWZphACl"
CF_LEAD_TYPE = "cf_5ZUUaAXocXSvGYmx0ySscbuoiZ0RqMgOixu6Bgg0v7Q"
CF_AGE = "cf_ybSEF2RZgNHTRRa2vTJFQ7F1rIODCaXTXiL4zFtXx9S"

# TCPA / A2P SMS consent audit trail (created 2026-04-18)
CF_SMS_CONSENT = "cf_UbIlORO7yiutEn5nxNYfBAXDYUrSUiGkGZSaSu6fBJd"
CF_CONSENT_TIMESTAMP = "cf_5bIMibMKPU7RtKFORqYDp3dU5CZxOmgTW2vv5wbw9wH"
CF_CONSENT_IP = "cf_imAJ77eXuOqPfQarFkGj5TETLHu26mRB49EqCnI4SR2"

# Ad click IDs — per-click attribution back to Meta/Google/TikTok ads
CF_FBCLID = "cf_WgATCoIlMN9V2Ruh6qS2kLYj9TVhkiAlRjnEwsTipRj"
CF_GCLID = "cf_UoruAy03WGIl7mlolXyYiHyGIzXowMx44sr9QtXxK0n"
CF_TTCLID = "cf_NsAN00NZi55fkZjeuXBtjKBKFWcxzSjyVJfIOFY52gl"

# Full URL of the landing page at submission time
CF_LANDING_PAGE_URL = "cf_ZZ8iNf7RDaCjysZPk0XkTEHFUOoBexLGQAu3XzK1ZSM"

# Lead Status IDs
STATUS_NEW_LEAD = "stat_FncoFJQfuuXdXbNx0HbwsKVR7EA95OhoQmqEPNMXl7T"

BASE_URL = "https://api.close.com/api/v1"


# ---------------------------------------------------------------------------
# Classification helpers
# ---------------------------------------------------------------------------


def _determine_lead_source(utm_source: Optional[str], ad_platform: Optional[str]) -> str:
    """Map utm_source / ad_platform to a human-readable lead source label."""
    src = (utm_source or ad_platform or "").lower()
    if "facebook" in src or "meta" in src or "fb" in src or "ig" in src:
        return "Facebook Ad"
    if "google" in src:
        return "Google Ad"
    if "tiktok" in src:
        return "TikTok Ad"
    return "Website Ad"


def _determine_lead_type(coverage_interest: Optional[str]) -> str:
    """Map coverage_interest to a lead type label."""
    if not coverage_interest:
        return "Mortgage Protection"
    interest = coverage_interest.lower()
    if "iul" in interest:
        return "IUL"
    if "mortgage" in interest or "mp" in interest:
        return "Mortgage Protection"
    if "term" in interest:
        return "Term Life"
    if "final" in interest or "expense" in interest:
        return "Final Expense"
    return coverage_interest


# ---------------------------------------------------------------------------
# Dedup search
# ---------------------------------------------------------------------------


async def _find_existing_lead(
    client: httpx.AsyncClient,
    api_key: str,
    phone: Optional[str],
    email: Optional[str],
) -> Optional[dict[str, Any]]:
    """Search Close for an existing Lead matching this phone or email.

    Close's search normalises phone numbers so we don't need to format.
    Returns the first matching lead dict or None.
    """
    parts: list[str] = []
    if phone:
        escaped = phone.replace('"', '\\"')
        parts.append(f'phone:"{escaped}"')
    if email:
        escaped = email.replace('"', '\\"')
        parts.append(f'email:"{escaped}"')
    if not parts:
        return None

    query = " OR ".join(parts)
    try:
        resp = await client.get(
            f"{BASE_URL}/lead/",
            params={"query": query, "_limit": 1, "_fields": "id,display_name,status_label,custom"},
            auth=(api_key, ""),
        )
        resp.raise_for_status()
        data = resp.json().get("data", [])
        return data[0] if data else None
    except Exception as exc:
        logger.warning("Close dedup search failed (non-fatal): %s", exc)
        return None


async def _post_duplicate_note(
    client: httpx.AsyncClient,
    api_key: str,
    lead_id: str,
    submission_context: str,
) -> None:
    """Post a Note activity to the existing lead summarising the new submission."""
    try:
        resp = await client.post(
            f"{BASE_URL}/activity/note/",
            json={"lead_id": lead_id, "note": submission_context},
            auth=(api_key, ""),
        )
        resp.raise_for_status()
    except Exception as exc:
        logger.warning("Close note-on-duplicate failed (non-fatal): %s", exc)


def _build_duplicate_note(
    first_name: str,
    last_name: str,
    phone: Optional[str],
    email: Optional[str],
    lead_source: str,
    lead_type: str,
    utm_campaign: Optional[str],
    lead_form_variant: Optional[str],
    landing_page_url: Optional[str],
    fbclid: Optional[str],
    gclid: Optional[str],
    ttclid: Optional[str],
    sms_consent: bool,
    consent_timestamp: str,
    consent_ip: Optional[str],
) -> str:
    lines = [
        "Repeat form submission — duplicate detected, no new lead created.",
        f"Submitted at: {consent_timestamp}",
        f"Name on submit: {first_name} {last_name}",
        f"Phone: {phone or '-'}",
        f"Email: {email or '-'}",
        f"Source: {lead_source}",
        f"Lead type: {lead_type}",
        f"Campaign: {utm_campaign or '-'}",
        f"Form variant: {lead_form_variant or '-'}",
        f"Landing page: {landing_page_url or '-'}",
        f"fbclid: {fbclid or '-'}",
        f"gclid: {gclid or '-'}",
        f"ttclid: {ttclid or '-'}",
        f"SMS consent: {'yes' if sms_consent else 'no'}  (IP {consent_ip or '-'})",
    ]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Create / dedup orchestration
# ---------------------------------------------------------------------------


async def create_lead(
    *,
    first_name: str,
    last_name: str,
    email: Optional[str] = None,
    phone: Optional[str] = None,
    state: Optional[str] = None,
    age: Optional[int] = None,
    coverage_interest: Optional[str] = None,
    utm_source: Optional[str] = None,
    utm_medium: Optional[str] = None,
    utm_campaign: Optional[str] = None,
    utm_content: Optional[str] = None,
    ad_platform: Optional[str] = None,
    lead_form_variant: Optional[str] = None,
    sms_consent: bool = False,
    consent_ip: Optional[str] = None,
    fbclid: Optional[str] = None,
    gclid: Optional[str] = None,
    ttclid: Optional[str] = None,
    landing_page_url: Optional[str] = None,
) -> dict[str, Any]:
    """Create a Close Lead (or append to an existing one) for an ad-form submission.

    Returns: {"lead_id": str, "contact_id": Optional[str], "duplicate": bool}
    Raises: httpx.HTTPStatusError on non-dedup Close API failures.
    """
    settings = get_settings()
    api_key = settings.close_api_key
    if not api_key:
        raise RuntimeError("CLOSE_API_KEY not configured")

    lead_source = _determine_lead_source(utm_source, ad_platform)
    lead_type = _determine_lead_type(coverage_interest)
    consent_timestamp = datetime.now(timezone.utc).isoformat(timespec="seconds")

    async with httpx.AsyncClient(timeout=30.0) as client:
        # --- Dedup: look up existing lead by phone/email ---
        existing = await _find_existing_lead(client, api_key, phone, email)
        if existing:
            logger.info(
                "Close dedup hit for %s %s (phone=%s email=%s) → existing lead %s",
                first_name, last_name, phone, email, existing["id"],
            )
            note = _build_duplicate_note(
                first_name, last_name, phone, email, lead_source, lead_type,
                utm_campaign, lead_form_variant, landing_page_url,
                fbclid, gclid, ttclid, sms_consent, consent_timestamp, consent_ip,
            )
            await _post_duplicate_note(client, api_key, existing["id"], note)
            existing_contact_id = ""
            return {
                "lead_id": existing["id"],
                "contact_id": existing_contact_id,
                "duplicate": True,
            }

        # --- Fresh create ---
        contact: dict[str, Any] = {"name": f"{first_name} {last_name}"}
        if email:
            contact["emails"] = [{"email": email, "type": "office"}]
        if phone:
            contact["phones"] = [{"phone": phone, "type": "mobile"}]
        if state:
            contact["addresses"] = [{
                "label": "home",
                "state": state,
                "country": "US",
            }]

        custom: dict[str, Any] = {
            CF_LEAD_SOURCE: lead_source,
            CF_LEAD_TYPE: lead_type,
            CF_SMS_CONSENT: "yes" if sms_consent else "no",
            CF_CONSENT_TIMESTAMP: consent_timestamp,
        }
        if consent_ip:
            custom[CF_CONSENT_IP] = consent_ip
        if age is not None:
            custom[CF_AGE] = age
        if utm_source is not None:
            custom[CF_UTM_SOURCE] = utm_source
        if utm_medium is not None:
            custom[CF_UTM_MEDIUM] = utm_medium
        if utm_campaign is not None:
            custom[CF_UTM_CAMPAIGN] = utm_campaign
        if utm_content is not None:
            custom[CF_UTM_CONTENT] = utm_content
        if ad_platform is not None:
            custom[CF_AD_PLATFORM] = ad_platform
        if lead_form_variant is not None:
            custom[CF_LEAD_FORM_VARIANT] = lead_form_variant
        if fbclid is not None:
            custom[CF_FBCLID] = fbclid
        if gclid is not None:
            custom[CF_GCLID] = gclid
        if ttclid is not None:
            custom[CF_TTCLID] = ttclid
        if landing_page_url is not None:
            custom[CF_LANDING_PAGE_URL] = landing_page_url

        lead_name = f"{first_name} {last_name}"
        if coverage_interest:
            lead_name += f" — {lead_type}"

        description_parts: list[str] = []
        if coverage_interest:
            description_parts.append(f"Interest: {coverage_interest}")
        description = " | ".join(description_parts)

        lead_payload: dict[str, Any] = {
            "name": lead_name,
            "status_id": STATUS_NEW_LEAD,
            "contacts": [contact],
            "custom": custom,
        }
        if description:
            lead_payload["description"] = description

        logger.info("Creating Close lead for %s %s (source=%s)", first_name, last_name, lead_source)
        resp = await client.post(f"{BASE_URL}/lead/", json=lead_payload, auth=(api_key, ""))
        resp.raise_for_status()
        lead_data = resp.json()
        lead_id = lead_data["id"]
        contact_id = lead_data["contacts"][0]["id"] if lead_data.get("contacts") else ""
        logger.info("Close lead created: %s (contact: %s)", lead_id, contact_id)

    return {
        "lead_id": lead_id,
        "contact_id": contact_id,
        "duplicate": False,
    }
