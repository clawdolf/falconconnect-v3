"""Compliance checking and sync logic for GHL Dashboard."""

import asyncio
import logging

from datetime import datetime, timedelta, timezone
from typing import Any

logger = logging.getLogger(__name__)


def check_contact_compliance(contact: dict) -> dict:
    """Check a single contact against compliance rules.

    Returns dict with:
    - contact_id: GHL contact ID
    - name: Contact name
    - has_phone: bool
    - has_email: bool
    - has_tag: bool
    - dnd_status: bool (is contact Do Not Disturb?)
    - last_activity_days: int (days since last activity, or 999 if never)
    - compliance_score: int (0-6, number of rules passed)
    - issues: list of failed rule names
    """
    contact_id = contact.get("id", "unknown")
    name = contact.get("name", "N/A")
    email = contact.get("email", "")
    phone = contact.get("phone", "")
    tags = contact.get("tags", [])
    dnd_status = contact.get("dnd", False)

    # Parse last activity timestamp if present
    last_activity_at = contact.get("lastActivity")
    if last_activity_at:
        try:
            last_activity_dt = datetime.fromisoformat(last_activity_at.replace("Z", "+00:00"))
            now = datetime.now(timezone.utc)
            last_activity_days = (now - last_activity_dt).days
        except Exception:
            last_activity_days = 999
    else:
        last_activity_days = 999

    # Apply 6 compliance rules
    issues = []
    passed = 0

    # Rule 1: has phone
    if phone and str(phone).strip():
        passed += 1
    else:
        issues.append("missing_phone")

    # Rule 2: has email
    if email and str(email).strip():
        passed += 1
    else:
        issues.append("missing_email")

    # Rule 3: has at least one tag
    if tags and len(tags) > 0:
        passed += 1
    else:
        issues.append("no_tags")

    # Rule 4: not in DND
    if not dnd_status:
        passed += 1
    else:
        issues.append("is_dnd")

    # Rule 5: activity within 90 days
    if last_activity_days <= 90:
        passed += 1
    else:
        issues.append("inactive_90d")

    # Rule 6: has first name (non-empty name)
    if name and str(name).strip() and name != "N/A":
        passed += 1
    else:
        issues.append("no_first_name")

    return {
        "contact_id": contact_id,
        "name": name,
        "has_phone": bool(phone),
        "has_email": bool(email),
        "has_tag": bool(tags),
        "dnd_status": dnd_status,
        "last_activity_days": last_activity_days,
        "compliance_score": passed,
        "is_compliant": passed == 6,
        "issues": issues,
    }


def run_compliance_check(contacts: list[dict]) -> dict:
    """Run compliance check across all contacts.

    Returns dict with:
    - total: total contacts checked
    - compliant: count of fully compliant contacts
    - compliance_rate: percentage
    - issues: list of issue distributions
    - results: full check results
    """
    if not contacts:
        return {
            "total": 0,
            "compliant": 0,
            "compliance_rate": 0,
            "issues": [],
            "results": [],
        }

    results = [check_contact_compliance(c) for c in contacts]
    compliant_count = sum(1 for r in results if r["is_compliant"])

    # Aggregate issues
    issue_counts = {}
    for result in results:
        for issue in result["issues"]:
            issue_counts[issue] = issue_counts.get(issue, 0) + 1

    issues_list = [
        {"type": issue, "count": count, "percentage": round(100 * count / len(results), 1)}
        for issue, count in sorted(issue_counts.items(), key=lambda x: x[1], reverse=True)
    ]

    return {
        "total": len(contacts),
        "compliant": compliant_count,
        "compliance_rate": round(100 * compliant_count / len(results), 1) if results else 0,
        "issues": issues_list,
        "results": results,
    }


async def full_sync() -> None:
    """Periodic GHL dashboard sync job (run every 4 hours by APScheduler).

    Stub implementation — no-op for now.
    TODO: Fetch GHL contacts via client, run compliance check, upsert results to DB.
    """
    import logging
    logger = logging.getLogger(__name__)
    logger.info("[GHL Sync] full_sync cron job triggered")
