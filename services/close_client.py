"""Close.com API client — creates Leads with Contacts & Opportunities for ad landing pages.

Used by the public ad lead capture endpoint to push leads from Meta/Google ad
landing pages into Close.com with full UTM attribution.
"""

import logging
from typing import Any, Optional

import httpx

from config import get_settings

logger = logging.getLogger("falconconnect.close")

# ---------------------------------------------------------------------------
# Close.com Custom Field IDs (stable — created once, never change)
# ---------------------------------------------------------------------------

# UTM Attribution fields (created 2026-03-14)
CF_UTM_SOURCE = "cf_Gjgzr7FkkeBhOE2Mlt8QGwNpT7mEY3YAIByFow8yMVz"
CF_UTM_MEDIUM = "cf_BdVfTFVsMY9Uk45ZpLM4fUfskc7g4b7IKOiZCuDdZ8I"
CF_UTM_CAMPAIGN = "cf_7nVp5tmtpfcM6VZnge0WqB67pt5s2hcIXs1RbTuxtzD"
CF_UTM_CONTENT = "cf_5NFr6MwVguhV9vKa9d4rMxRy7ybWLxbaaSHMl1Wux8L"
CF_AD_PLATFORM = "cf_kjMHO5vxvfqDEN0i9xmkRIBM5h74YhfTnW900ckdGqq"
CF_LEAD_FORM_VARIANT = "cf_TLZpT49XI24ub6XkvteT34yCb9Gzgcozq8UEuRnZ5MO"

# Existing standard fields
CF_LEAD_SOURCE = "cf_q6RrzuQj49ewO4h9OTqzXKxOe1tovnhq1SivMgkW1wh"
CF_LEAD_TYPE = "cf_WrHtEGzfvu5NVYQ6kwRih1MjUKGKYdeWPPVlpcj7tWq"
CF_STATE = "cf_TuSvZiC8f3jN6KyaSNnRDyNzayCeoz2BzQfs8rJDrxp"
CF_AGE = "cf_ybSEF2RZgNHTRRa2vTJFQ7F1rIODCaXTXiL4zFtXx9S"
CF_ZIP_CODE = "cf_WQXb3aBm9i3Be4Hd4IwsONVD5Ler5YWBtvTOC6jRGkV"
CF_LEAD_AGE = "cf_WT1Jlj8IpKxVLFZnhqneIuAbocsWyV7dgn8WQJR0OFg"

# Pipeline / Status IDs
PIPELINE_INSURANCE = "pipe_2c85uCuww6T1Hps2npd2es"
STATUS_OPTIONS_PRESENTED = "stat_549mKG6g4gpHKT6leA5GMPsOdj7cwLmT7LO05pjAMwI"

BASE_URL = "https://api.close.com/api/v1"


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


async def create_lead(
    *,
    first_name: str,
    last_name: str,
    email: Optional[str] = None,
    phone: Optional[str] = None,
    state: Optional[str] = None,
    age: Optional[int] = None,
    is_homeowner: Optional[bool] = None,
    coverage_interest: Optional[str] = None,
    utm_source: Optional[str] = None,
    utm_medium: Optional[str] = None,
    utm_campaign: Optional[str] = None,
    utm_content: Optional[str] = None,
    ad_platform: Optional[str] = None,
    lead_form_variant: Optional[str] = None,
) -> dict[str, Any]:
    """Create a Lead in Close.com with Contact and Opportunity.

    Returns: {"lead_id": str, "contact_id": str, "opportunity_id": str | None}
    Raises: httpx.HTTPStatusError on API failures.
    """
    settings = get_settings()
    api_key = settings.close_api_key
    if not api_key:
        raise RuntimeError("CLOSE_API_KEY not configured")

    lead_source = _determine_lead_source(utm_source, ad_platform)
    lead_type = _determine_lead_type(coverage_interest)

    # Build contact info
    contact: dict[str, Any] = {
        "name": f"{first_name} {last_name}",
    }
    if email:
        contact["emails"] = [{"email": email, "type": "office"}]
    if phone:
        contact["phones"] = [{"phone": phone, "type": "mobile"}]

    # Build custom fields — only set non-None values
    custom: dict[str, Any] = {}

    # Standard fields
    custom[CF_LEAD_SOURCE] = lead_source
    custom[CF_LEAD_TYPE] = lead_type
    if state:
        custom[CF_STATE] = state
    if age is not None:
        custom[CF_AGE] = age
    # Lead Age = "New" for ad leads (just captured)
    custom[CF_LEAD_AGE] = "New"

    # UTM attribution
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

    # Build lead name
    lead_name = f"{first_name} {last_name}"
    if coverage_interest:
        lead_name += f" — {lead_type}"

    # Build description with homeowner info
    description_parts = []
    if is_homeowner is not None:
        description_parts.append(f"Homeowner: {'Yes' if is_homeowner else 'No'}")
    if coverage_interest:
        description_parts.append(f"Interest: {coverage_interest}")
    description = " | ".join(description_parts) if description_parts else ""

    # Create lead payload
    lead_payload: dict[str, Any] = {
        "name": lead_name,
        "contacts": [contact],
        "custom": custom,
    }
    if description:
        lead_payload["description"] = description

    async with httpx.AsyncClient(timeout=30.0) as client:
        # Step 1: Create the Lead (with embedded Contact)
        logger.info("Creating Close lead for %s %s (source=%s)", first_name, last_name, lead_source)

        resp = await client.post(
            f"{BASE_URL}/lead/",
            json=lead_payload,
            auth=(api_key, ""),
        )
        resp.raise_for_status()
        lead_data = resp.json()
        lead_id = lead_data["id"]
        contact_id = lead_data["contacts"][0]["id"] if lead_data.get("contacts") else ""

        logger.info("Close lead created: %s (contact: %s)", lead_id, contact_id)

        # Step 2: Create Opportunity on the lead
        opportunity_id = None
        try:
            opp_payload = {
                "lead_id": lead_id,
                "note": f"Ad lead: {lead_source} | {utm_campaign or 'unknown campaign'}",
                "status_id": STATUS_OPTIONS_PRESENTED,
            }
            opp_resp = await client.post(
                f"{BASE_URL}/opportunity/",
                json=opp_payload,
                auth=(api_key, ""),
            )
            opp_resp.raise_for_status()
            opportunity_id = opp_resp.json()["id"]
            logger.info("Close opportunity created: %s", opportunity_id)
        except Exception as exc:
            # Opportunity creation is non-fatal
            logger.warning("Failed to create Close opportunity (non-fatal): %s", exc)

    return {
        "lead_id": lead_id,
        "contact_id": contact_id,
        "opportunity_id": opportunity_id,
    }
