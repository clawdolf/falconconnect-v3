"""
Florida License Lookup Utility
===============================
Florida uses an independent DFS portal (licenseesearch.fldfs.com) that does NOT
support direct deep-linking by NPN or FL license number. Instead:

  1. GET the search page (picks up session cookie from load balancer)
  2. POST the search form with FL license # or NPN
  3. Parse the result HTML for the agent's profile link: /Licensee/{internal_id}
  4. Return that direct URL

The resulting URL (https://licenseesearch.fldfs.com/Licensee/{id}) is a stable
permalink to the agent's full license record — shareable without any manual search.

Usage (one-time per agent when seeding):
    url = lookup_fl_direct_url(fl_license_number="G258860")
    # => "https://licenseesearch.fldfs.com/Licensee/2700806"

Store the result in the agent's DB record (e.g., licenses.verify_url for FL).
Re-run only if an agent's FL license changes.
"""

import urllib.request
import urllib.parse
import http.cookiejar
import re
from typing import Optional


FL_SEARCH_URL = "https://licenseesearch.fldfs.com/"
FL_PROFILE_BASE = "https://licenseesearch.fldfs.com/Licensee/"

# Matches /Licensee/{internal_id} in result HTML
_LICENSEE_HREF_RE = re.compile(
    r'href=["\'](?:https://licenseesearch\.fldfs\.com)?(/Licensee/(\d+))["\']',
    re.IGNORECASE,
)

_USER_AGENT = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"


def _build_form_data(
    fl_license_number: str = None,
    npn: str = None,
    first_name: str = None,
    last_name: str = None,
) -> bytes:
    """Build the POST body for the FL DFS licensee search form.

    Key gotcha: LicenseStatusFilter is a numeric radio value (1/2/3), NOT
    the string "Valid". Sending "Valid" causes a 500 server error.
    """
    data = {
        # Paging / sort state
        "LicenseeSearchInfo.PagingInfo.SortBy": "Name",
        "LicenseeSearchInfo.PagingInfo.SortDesc": "False",
        "LicenseeSearchInfo.PagingInfo.CurrentPage": "1",
        # Radio: 1=Valid, 2=Invalid, 3=Both — MUST be numeric
        "LicenseStatusFilter": "1",
        # Tab state flags
        "TabLLValue": "",
        "TabCEValue": "",
        "TabAppValue": "",
        # Filter toggles (match browser defaults)
        "OnlyLicWithNoQuApptFilter": "false",
        "CEHrsNotMetFilter": "false",
        "FirmNameBeginContainFilter": "True",
        "EmailAddressBeginContainFilter": "True",
        "AppointingEntityNameSearchInfo.AppEntityActiveOnlyFilter": "false",
        "AppointingEntityNameSearchInfo.AppEntityNameBeginContainFilter": "True",
        "AppointingEntityNameSearchInfo.PagingInfo.CurrentPage": "1",
    }

    if fl_license_number:
        data["FLLicenseNoFilter"] = fl_license_number.strip().upper()
    if npn:
        data["NPNNoFilter"] = npn.strip()
    if first_name:
        data["IndividualFNameFilter"] = first_name.strip()
    if last_name:
        data["IndividualLNameFilter"] = last_name.strip()

    return urllib.parse.urlencode(data).encode("utf-8")


def lookup_fl_direct_url(
    fl_license_number: str = None,
    npn: str = None,
    first_name: str = None,
    last_name: str = None,
    timeout: int = 15,
) -> Optional[str]:
    """
    Look up a Florida agent's direct verification URL from licenseesearch.fldfs.com.

    Provide at least one of: fl_license_number, npn, or (first_name + last_name).
    FL license number is most reliable (unique per agent).

    Steps:
      1. GET the search page to pick up the load-balancer session cookie
      2. POST the search form
      3. Parse /Licensee/{id} links from the response

    Returns:
        Direct URL string (e.g. "https://licenseesearch.fldfs.com/Licensee/2700806")
        or None if not found or lookup failed.
    """
    if not any([fl_license_number, npn, first_name, last_name]):
        raise ValueError("Provide at least fl_license_number, npn, or a name.")

    # Step 1: GET to acquire session cookie
    jar = http.cookiejar.CookieJar()
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
    try:
        opener.open(
            urllib.request.Request(FL_SEARCH_URL, headers={"User-Agent": _USER_AGENT}),
            timeout=timeout,
        )
    except Exception as e:
        print(f"[fl_license_lookup] Session cookie GET failed: {e}")
        return None

    # Step 2: POST the search
    form_data = _build_form_data(
        fl_license_number=fl_license_number,
        npn=npn,
        first_name=first_name,
        last_name=last_name,
    )
    req = urllib.request.Request(
        FL_SEARCH_URL,
        data=form_data,
        headers={
            "Content-Type": "application/x-www-form-urlencoded",
            "User-Agent": _USER_AGENT,
            "Referer": FL_SEARCH_URL,
        },
    )
    try:
        resp = opener.open(req, timeout=timeout)
        html = resp.read().decode("utf-8", errors="replace")
    except Exception as e:
        print(f"[fl_license_lookup] Search POST failed: {e}")
        return None

    # Step 3: Extract direct URL
    matches = _LICENSEE_HREF_RE.findall(html)
    if not matches:
        return None

    # matches = [(path, id), ...]  — take first result
    path, internal_id = matches[0]
    return f"{FL_PROFILE_BASE}{internal_id}"


def lookup_fl_direct_url_safe(
    fl_license_number: str = None,
    npn: str = None,
    first_name: str = None,
    last_name: str = None,
) -> Optional[str]:
    """
    Exception-safe wrapper for use inside API handlers.
    Returns None on any failure rather than raising.
    """
    try:
        return lookup_fl_direct_url(
            fl_license_number=fl_license_number,
            npn=npn,
            first_name=first_name,
            last_name=last_name,
        )
    except Exception as e:
        print(f"[fl_license_lookup] Safe lookup error: {e}")
        return None


# ---------------------------------------------------------------------------
# CLI: python fl_license_lookup.py --fl G258860
#      python fl_license_lookup.py --npn 12345678
#      python fl_license_lookup.py --last Taillieu
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Look up FL DFS direct verification URL")
    parser.add_argument("--fl",    help="FL license number (e.g. G258860)")
    parser.add_argument("--npn",   help="National Producer Number")
    parser.add_argument("--first", help="First name")
    parser.add_argument("--last",  help="Last name")
    args = parser.parse_args()

    url = lookup_fl_direct_url(
        fl_license_number=args.fl,
        npn=args.npn,
        first_name=args.first,
        last_name=args.last,
    )

    if url:
        print(f"Direct URL: {url}")
    else:
        print("Not found or lookup failed.")
