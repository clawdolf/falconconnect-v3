"""
License Verification Constants & Utilities

Maps all 50 US states + DC to their insurance license verification systems.

Most states participate in NAIC's SOLAR (State Online Lookup and Registration) system,
which provides a unified, deep-linkable verification URL using the producer's NPN.

Some states operate independent portals (CA DOI, NY DFS, etc.) that require
manual entry of license/NPN on the state's own website.

A few states use Sircon (now Vertafore) for their public lookup portal.

URL Pattern for NAIC SOLAR states:
  https://sbs.naic.org/solar-external-lookup/lookup/licensee/summary/{NPN}?jurisdiction={STATE}&entityType=IND&licenseType=PRO

This deep-links directly to the producer's license detail page — no manual entry needed.
"""

from typing import Optional


# =============================================================================
# NAIC SOLAR States
# =============================================================================
# These states participate in NAIC's SOLAR system and support direct deep-linking
# via NPN. The URL opens the producer's license summary directly.
#
# This covers the vast majority of states.

SOLAR_STATES = {
    "AL", "AK", "AZ", "AR", "CO", "CT", "DE", "DC", "GA",
    "HI", "ID", "IL", "IN", "IA", "KS", "KY", "LA", "MD",
    "MA", "MI", "MN", "MS", "MO", "NE", "NV", "NH", "NJ",
    "NM", "NC", "ND", "OH", "OK", "OR", "RI", "SC", "SD",
    "TN", "UT", "VT", "VA", "WA", "WV", "WI", "WY",
    # NOTE: MT removed — NAIC SOLAR has no data for MT producers. Use STATE_PORTALS instead.
}

# =============================================================================
# Florida — Independent DFS Portal (licenseesearch.fldfs.com)
# =============================================================================
# FL does NOT reliably deep-link via NAIC SOLAR. The FL Department of Financial
# Services uses its own portal where the direct profile URL contains an internal
# database ID (not the NPN or FL license number).
#
# Direct URL pattern: https://licenseesearch.fldfs.com/Licensee/{internal_id}
#
# To get a direct URL for a new FL agent:
#   from fl_license_lookup import lookup_fl_direct_url
#   url = lookup_fl_direct_url(fl_license_number="G258860")
#   # Store result in agent's license record as verify_url for state "FL"
#
# The lookup does a one-time POST search and extracts the permalink.
# Run once when seeding a new FL-licensed agent; cache the result in the DB.
FL_DFS_SEARCH_URL = "https://licenseesearch.fldfs.com/"
FL_DFS_PROFILE_BASE = "https://licenseesearch.fldfs.com/Licensee/"

# =============================================================================
# States with Independent / Manual Verification Portals
# =============================================================================
# These states do NOT use NAIC SOLAR or require their own portal for public lookup.
# Some use Sircon (Vertafore), some have custom DOI portals.

STATE_PORTALS = {
    # California: CDI license lookup
    "CA": "https://interactive.web.insurance.ca.gov/apex_extprd/f?p=102:SearchResults",
    
    # New York: DFS insurance license search  
    "NY": "https://myportal.dfs.ny.gov/industry/individual/licensee-search",
    
    # Texas: Sircon / TDI lookup (requires manual entry)
    "TX": "https://www.sircon.com/ComplianceExpress/Inquiry/consumerInquiry.do?nonSscrb=Y",
    
    # Pennsylvania: Sircon lookup (requires manual entry of license number)
    "PA": "https://www.sircon.com/ComplianceExpress/Inquiry/consumerInquiry.do?nonSscrb=Y",
    
    # Maine: Bureau of Insurance ALMS system (direct link with token if available)
    "ME": "https://www.pfr.maine.gov/ALMSOnline/ALMSQuery/SearchIndividual.aspx",
    
    # Montana: CSI (Commissioner of Securities and Insurance) — NAIC SOLAR has no MT data
    # Directs consumers to the state's own insurance producer lookup
    "MT": "https://csimt.gov/insurance/",
}

# States where the user needs to manually enter a license number on the portal
# FL is excluded here — it has a direct link once fl_internal_id is resolved.
# If fl_internal_id is missing, FL falls back to the search portal (functionally manual).
MANUAL_ENTRY_STATES = {"TX", "PA", "CA", "NY", "ME", "MT"}

# States using FL-style independent portals that require a one-time automated lookup
# to resolve a direct permalink (stored as fl_internal_id or equivalent in the DB).
LOOKUP_REQUIRED_STATES = {"FL"}

# All US states + DC for validation
ALL_STATES = SOLAR_STATES | set(STATE_PORTALS.keys()) | LOOKUP_REQUIRED_STATES

# Full state name → abbreviation mapping
STATE_NAME_TO_ABBR = {
    "Alabama": "AL", "Alaska": "AK", "Arizona": "AZ", "Arkansas": "AR",
    "California": "CA", "Colorado": "CO", "Connecticut": "CT", "Delaware": "DE",
    "District of Columbia": "DC", "Florida": "FL", "Georgia": "GA", "Hawaii": "HI",
    "Idaho": "ID", "Illinois": "IL", "Indiana": "IN", "Iowa": "IA",
    "Kansas": "KS", "Kentucky": "KY", "Louisiana": "LA", "Maine": "ME",
    "Maryland": "MD", "Massachusetts": "MA", "Michigan": "MI", "Minnesota": "MN",
    "Mississippi": "MS", "Missouri": "MO", "Montana": "MT", "Nebraska": "NE",
    "Nevada": "NV", "New Hampshire": "NH", "New Jersey": "NJ", "New Mexico": "NM",
    "New York": "NY", "North Carolina": "NC", "North Dakota": "ND", "Ohio": "OH",
    "Oklahoma": "OK", "Oregon": "OR", "Pennsylvania": "PA", "Rhode Island": "RI",
    "South Carolina": "SC", "South Dakota": "SD", "Tennessee": "TN", "Texas": "TX",
    "Utah": "UT", "Vermont": "VT", "Virginia": "VA", "Washington": "WA",
    "West Virginia": "WV", "Wisconsin": "WI", "Wyoming": "WY",
}

STATE_ABBR_TO_NAME = {v: k for k, v in STATE_NAME_TO_ABBR.items()}


def get_verify_url(state_abbr: str, npn: str, license_number: str = None,
                   direct_token: str = None, fl_internal_id: str = None) -> Optional[str]:
    """
    Generate the verification URL for a given state and producer.

    Args:
        state_abbr:      Two-letter state abbreviation (e.g., "AZ")
        npn:             National Producer Number
        license_number:  State-specific license number (display only for most states)
        direct_token:    Maine DetailToken for direct deep-link
        fl_internal_id:  FL DFS internal ID (from fl_license_lookup.lookup_fl_direct_url).
                         Required to generate a direct FL link; falls back to search portal.

    Returns:
        URL string or None if no verification URL is available.
    """
    state_abbr = state_abbr.upper()

    # --- Florida: independent DFS portal ---
    # Direct link requires internal ID fetched via fl_license_lookup.py.
    # Run once per agent at seed time; cache fl_internal_id in the DB.
    if state_abbr == "FL":
        if fl_internal_id:
            return f"{FL_DFS_PROFILE_BASE}{fl_internal_id}"
        # Fallback: send user to search portal (manual entry required)
        return FL_DFS_SEARCH_URL

    # --- Maine: direct link with token ---
    if state_abbr == "ME" and direct_token:
        return f"https://www.pfr.maine.gov/ALMSOnline/ALMSQuery/ShowDetail.aspx?DetailToken={direct_token}"

    # --- NAIC SOLAR states: deep-link via NPN ---
    if state_abbr in SOLAR_STATES:
        return (
            f"https://sbs.naic.org/solar-external-lookup/"
            f"lookup/licensee/summary/{npn}"
            f"?jurisdiction={state_abbr}&entityType=IND&licenseType=PRO"
        )

    # --- States with independent portals ---
    if state_abbr in STATE_PORTALS:
        return STATE_PORTALS[state_abbr]

    return None


def needs_manual_verification(state_abbr: str) -> bool:
    """
    Whether the verification portal requires the user to manually enter
    a license number or NPN (vs. direct deep-link).
    """
    return state_abbr.upper() in MANUAL_ENTRY_STATES


def get_state_verify_info(state_abbr: str) -> dict:
    """
    Get full verification info for a state.
    Useful for the frontend to decide how to render the verify button.
    """
    state_abbr = state_abbr.upper()
    uses_solar = state_abbr in SOLAR_STATES
    is_manual = needs_manual_verification(state_abbr)
    is_fl_dfs = state_abbr == "FL"
    portal_url = STATE_PORTALS.get(state_abbr)

    if is_fl_dfs:
        system = "FL DFS"
    elif uses_solar:
        system = "NAIC SOLAR"
    elif state_abbr in {"TX", "PA"}:
        system = "Sircon"
    elif portal_url:
        system = "State Portal"
    else:
        system = "Unknown"

    return {
        "state": state_abbr,
        "state_name": STATE_ABBR_TO_NAME.get(state_abbr, state_abbr),
        "uses_solar": uses_solar,
        "is_fl_dfs": is_fl_dfs,
        # FL: direct link once fl_internal_id is resolved; falls back to search portal
        "portal_url": FL_DFS_SEARCH_URL if is_fl_dfs else portal_url,
        "needs_manual": is_manual,
        # FL needs a one-time automated lookup (fl_license_lookup.py) at seed time
        "needs_lookup": state_abbr in LOOKUP_REQUIRED_STATES,
        "system": system,
    }


def resolve_fl_verify_url(fl_license_number: str = None, npn: str = None) -> Optional[str]:
    """
    Convenience wrapper: run the FL DFS lookup and return the direct URL.
    Import fl_license_lookup lazily to keep constants_licenses free of network deps
    when just importing constants.

    Call this once when adding a new FL-licensed agent.
    Store the returned URL (or the extracted internal ID) in the agent's license record.
    """
    try:
        from fl_license_lookup import lookup_fl_direct_url_safe
        return lookup_fl_direct_url_safe(
            fl_license_number=fl_license_number,
            npn=npn,
        )
    except ImportError:
        # fl_license_lookup not available — return search portal fallback
        return FL_DFS_SEARCH_URL
