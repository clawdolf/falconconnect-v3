"""Read-only data adapters for the lead hygiene audit.

This module wraps the live Close and GHL REST APIs (read-only) and loads
historical Notion data from a CSV export. The adapter NEVER writes to any
upstream system — the only mutations are to local files (CSV/JSON reports)
and the in-memory data structures returned to the classifier.

Two modes are supported:
  * fixture mode — reads bundled JSON/CSV under data/fixtures/lead_hygiene/.
                   No network access. Used for tests + safe CLI dry runs.
  * live mode    — reads from Close + GHL using existing FC credentials.
                   Only GET requests are issued.
"""

from __future__ import annotations

import csv
import json
import logging
import os
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

import httpx

from services.lead_hygiene import (
    ClassificationContext,
    ReportRow,
    build_record_index,
    build_report_row,
    classify_lead,
    match_records,
    normalize_email,
    normalize_phone,
    write_report,
)

logger = logging.getLogger("falconconnect.lead_hygiene")


def _resolve_close_api_key() -> str:
    """Return the Close API key from FC settings, falling back to env.

    Precedence: pydantic-settings (config.Settings) → CLOSE_API_KEY env var.
    The settings object already merges Render env-var panel + the optional
    /etc/secrets/.env file, so consulting it first guarantees the audit uses
    the same key as the rest of FC. Falls through cleanly if config can't
    import (e.g., when this module is run from a bare script context).
    """
    try:
        from config import get_settings  # type: ignore
        s = get_settings()
        key = getattr(s, "close_api_key", "") or ""
        if key:
            return key
    except Exception as exc:  # noqa: BLE001 — config is optional here
        logger.debug("config.get_settings unavailable for Close key: %s", exc)
    return os.environ.get("CLOSE_API_KEY", "") or ""


def _resolve_ghl_api_key() -> str:
    """Return the GHL API key from FC settings, falling back to env."""
    try:
        from config import get_settings  # type: ignore
        s = get_settings()
        key = getattr(s, "ghl_api_key", "") or ""
        if key:
            return key
    except Exception as exc:  # noqa: BLE001
        logger.debug("config.get_settings unavailable for GHL key: %s", exc)
    return os.environ.get("GHL_API_KEY", "") or ""


CADENCE_STAGE_FIELD_ID = "cf_vuP2rYRL0LA3OK0nCyZm9b19ki8ddokdTAapVnJ2Elb"

CLOSE_BASE = "https://api.close.com/api/v1"
GHL_BASE = "https://services.leadconnectorhq.com"
GHL_API_VERSION = "2021-07-28"

DEFAULT_FIXTURE_DIR = Path(__file__).resolve().parent.parent / "data" / "fixtures" / "lead_hygiene"


# ──────────────────────────────────────────────────────────────────────
# Fixture loading
# ──────────────────────────────────────────────────────────────────────


def _load_close_fixture(path: Path) -> List[Dict[str, Any]]:
    return json.loads(path.read_text())


def _load_ghl_fixture(path: Path) -> List[Dict[str, Any]]:
    return json.loads(path.read_text())


def _load_notion_csv(path: Path) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    if not path.exists():
        return out
    with path.open(newline="") as fh:
        reader = csv.DictReader(fh)
        for row in reader:
            out.append(row)
    return out


# ──────────────────────────────────────────────────────────────────────
# Shape adapters — convert raw API/CSV records to the canonical shape
# expected by build_record_index / match_records.
# ──────────────────────────────────────────────────────────────────────


def _close_to_record(lead: Dict[str, Any]) -> Dict[str, Any]:
    contacts = lead.get("contacts", []) or []
    phones: List[str] = []
    emails: List[str] = []
    for c in contacts:
        for p in (c.get("phones") or []):
            phones.append(p.get("phone") if isinstance(p, dict) else p)
        for e in (c.get("emails") or []):
            emails.append(e.get("email") if isinstance(e, dict) else e)
    cadence = ""
    custom = lead.get("custom") or {}
    if isinstance(custom, dict):
        # Live API uses "custom.cf_xxx" keys at top level OR a nested dict.
        cadence = custom.get(CADENCE_STAGE_FIELD_ID) or custom.get("Cadence Stage") or ""
    cadence = cadence or lead.get(f"custom.{CADENCE_STAGE_FIELD_ID}", "") or ""
    return {
        "source": "close",
        "source_id": lead.get("id", ""),
        "name": lead.get("display_name") or lead.get("name") or "",
        "phones": phones,
        "emails": emails,
        "close_status": lead.get("status_label"),
        "cadence_stage": cadence,
        "activities": lead.get("activities", []) or [],
    }


def _ghl_to_record(contact: Dict[str, Any]) -> Dict[str, Any]:
    phones = [contact.get("phone")] if contact.get("phone") else []
    for p in contact.get("additionalPhones") or []:
        if isinstance(p, dict) and p.get("phoneNumber"):
            phones.append(p["phoneNumber"])
        elif isinstance(p, str):
            phones.append(p)
    emails = []
    if contact.get("email"):
        emails.append(contact["email"])
    return {
        "source": "ghl",
        "source_id": contact.get("id", ""),
        "name": " ".join([
            contact.get("firstName", "") or "",
            contact.get("lastName", "") or "",
        ]).strip() or contact.get("contactName") or "",
        "phones": phones,
        "emails": emails,
        "tags": contact.get("tags", []) or [],
    }


def _notion_row_to_record(row: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "source": "notion",
        "source_id": row.get("Notion Page ID") or row.get("page_id") or "",
        "name": row.get("Name", ""),
        "phones": [row.get("Mobile Phone", "")] if row.get("Mobile Phone") else [],
        "emails": [row.get("Email", "")] if row.get("Email") else [],
        "notion_status": row.get("Lead Status"),
        "notion_opportunity_stage": row.get("Opportunity Stage"),
        "notion_body": row.get("Aggregate Comments", ""),
        "follow_up_date": row.get("Follow Up Date"),
    }


# ──────────────────────────────────────────────────────────────────────
# Live (read-only) fetchers
# ──────────────────────────────────────────────────────────────────────


def _close_auth_header(api_key: str) -> Dict[str, str]:
    import base64
    encoded = base64.b64encode(f"{api_key}:".encode()).decode()
    return {"Authorization": f"Basic {encoded}"}


def _build_close_lead_params(
    *,
    limit: int,
    skip: int,
    status_label: Optional[str] = None,
    extra_query: Optional[str] = None,
) -> Dict[str, Any]:
    """Build query params for GET /api/v1/lead/.

    Close silently ignores `status_label=` and `status=` on the /lead/ list
    endpoint (verified 2026-05-18 — both return the full unfiltered list).
    The working pattern is the search-syntax query, e.g.
    `query=status:"Voicemail"`.

    Caller-supplied `extra_query` is combined with the status clause via
    ` AND `. Caller query is wrapped in parentheses to keep precedence
    explicit. Double-quotes inside the status label are escaped.
    """
    params: Dict[str, Any] = {"_limit": limit, "_skip": skip}
    parts: List[str] = []
    extra = (extra_query or "").strip()
    if extra:
        parts.append(f"({extra})")
    label = (status_label or "").strip()
    if label:
        escaped = label.replace("\\", "\\\\").replace('"', '\\"')
        parts.append(f'status:"{escaped}"')
    if parts:
        params["query"] = " AND ".join(parts)
    return params


async def _fetch_close_leads_live(
    api_key: str,
    limit: int,
    status_label: Optional[str] = None,
    extra_query: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """GET leads from Close (paginated). NO writes, NO PUT/POST/DELETE.

    `status_label` and `extra_query` are merged into a single Close-search
    `query=` parameter by `_build_close_lead_params` — see that helper for
    why `status_label=` on /lead/ is unreliable.
    """
    leads: List[Dict[str, Any]] = []
    skip = 0
    page_size = min(100, limit)
    async with httpx.AsyncClient(timeout=30, headers=_close_auth_header(api_key)) as client:
        while len(leads) < limit:
            params = _build_close_lead_params(
                limit=page_size,
                skip=skip,
                status_label=status_label,
                extra_query=extra_query,
            )
            resp = await client.get(f"{CLOSE_BASE}/lead/", params=params)
            resp.raise_for_status()
            batch = resp.json().get("data", [])
            if not batch:
                break
            for lead in batch:
                # Fetch activities per-lead for the activity scan.
                activities = await _fetch_close_activities_live(client, lead["id"])
                lead["activities"] = activities
                leads.append(lead)
                if len(leads) >= limit:
                    break
            skip += len(batch)
            if len(batch) < page_size:
                break
    return leads


async def _fetch_close_activities_live(
    client: httpx.AsyncClient,
    lead_id: str,
) -> List[Dict[str, Any]]:
    """Fetch all activities for a lead.

    All Close-side text fields are surfaced individually (text, note,
    body_text, task_text, subject) so the classifier can detect hard-stop
    evidence in TaskCompleted, Email, and Note bodies — not just the
    first-wins collapsed value. Close type names normalised so downstream
    pattern matching is predictable.
    """
    activities: List[Dict[str, Any]] = []
    resp = await client.get(
        f"{CLOSE_BASE}/activity/",
        params={"lead_id": lead_id, "_limit": 100, "_order_by": "-date_created"},
    )
    resp.raise_for_status()
    for a in resp.json().get("data", []):
        raw_type = a.get("_type") or a.get("type") or ""
        normalised_type = raw_type.lower().replace("activity", "").strip("_")
        activities.append({
            "type": normalised_type or raw_type.lower(),
            "direction": (a.get("direction") or "").lower(),
            "duration": a.get("duration"),
            # Surface every text-bearing field; _extract_activity_body
            # concatenates them at scan time.
            "text": a.get("text"),
            "note": a.get("note"),
            "body": a.get("body"),
            "body_text": a.get("body_text"),
            "task_text": a.get("task_text"),
            "subject": a.get("subject"),
            "activity_type_name": (
                a.get("custom_activity_type_name")
                or a.get("activity_type_name")
                or ""
            ),
            "date_created": a.get("date_created"),
        })
    return activities


async def _fetch_ghl_contact_live(
    api_key: str,
    contact_id: str,
) -> Optional[Dict[str, Any]]:
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Version": GHL_API_VERSION,
        "Accept": "application/json",
    }
    async with httpx.AsyncClient(timeout=30, headers=headers) as client:
        resp = await client.get(f"{GHL_BASE}/contacts/{contact_id}")
        if resp.status_code == 404:
            return None
        resp.raise_for_status()
        return resp.json().get("contact", resp.json())


# ──────────────────────────────────────────────────────────────────────
# Orchestration
# ──────────────────────────────────────────────────────────────────────


def _detect_duplicate_phones(records: List[Dict[str, Any]]) -> set:
    counts: Counter = Counter()
    for r in records:
        for p in r.get("phones", []) or []:
            normalised = normalize_phone(p)
            if normalised:
                counts[normalised] += 1
    return {p for p, n in counts.items() if n > 1}


def run_audit_from_fixtures(
    fixture_dir: Path = DEFAULT_FIXTURE_DIR,
    out_dir: Optional[Path] = None,
    now: Optional[datetime] = None,
    recent_window_days: int = 30,
    limit: Optional[int] = None,
) -> Dict[str, Any]:
    """Run the full audit against bundled fixtures. Writes report files."""
    fixture_dir = Path(fixture_dir)
    out_dir = Path(out_dir) if out_dir else Path.cwd() / "out" / "lead_hygiene"
    now = now or datetime.now(timezone.utc)

    close_raw = _load_close_fixture(fixture_dir / "close_leads.json")
    ghl_raw = _load_ghl_fixture(fixture_dir / "ghl_contacts.json")
    notion_raw = _load_notion_csv(fixture_dir / "notion_export.csv")

    if limit is not None:
        close_raw = close_raw[:limit]

    return _run_audit(
        close_raw=close_raw,
        ghl_raw=ghl_raw,
        notion_raw=notion_raw,
        out_dir=out_dir,
        now=now,
        recent_window_days=recent_window_days,
    )


async def run_audit_from_live(
    out_dir: Path,
    limit: int = 200,
    status_label: Optional[str] = None,
    recent_window_days: int = 30,
    notion_csv: Optional[Path] = None,
    now: Optional[datetime] = None,
    extra_query: Optional[str] = None,
) -> Dict[str, Any]:
    """Run the audit pulling read-only data from Close + GHL.

    NEVER issues a PUT/POST/DELETE. If credentials are missing, raises.

    `status_label` is merged into a Close-search `query=status:"…"` filter
    (Close ignores `status_label=` on /lead/). `extra_query` lets the caller
    add any Close search syntax (e.g. lead_age, created date) which is
    AND-combined with the status clause.
    """
    now = now or datetime.now(timezone.utc)

    close_api_key = _resolve_close_api_key()
    if not close_api_key:
        raise RuntimeError(
            "Close API key not found in FC settings (config.close_api_key) "
            "or CLOSE_API_KEY env var — refusing to run live audit."
        )

    close_raw = await _fetch_close_leads_live(
        close_api_key, limit, status_label, extra_query=extra_query,
    )

    # GHL contacts are fetched per-lead when a Close lead carries a GHL ID
    # custom field. The live GHL list endpoint is heavy; per-contact GET is
    # cheaper for an MVP audit and read-only.
    ghl_api_key = _resolve_ghl_api_key()
    ghl_raw: List[Dict[str, Any]] = []
    if ghl_api_key:
        for lead in close_raw:
            custom = lead.get("custom") or {}
            ghl_id = None
            if isinstance(custom, dict):
                ghl_id = (
                    custom.get("GHL ID")
                    or custom.get("cf_XWisbKrkWGeMvGYTMGMZVoWjYvFlcXmOkgILiXyDcMM")
                )
            if not ghl_id:
                continue
            contact = await _fetch_ghl_contact_live(ghl_api_key, ghl_id)
            if contact:
                ghl_raw.append(contact)
    else:
        logger.warning("GHL_API_KEY not set — skipping GHL enrichment in audit.")

    notion_raw: List[Dict[str, Any]] = []
    if notion_csv and Path(notion_csv).exists():
        notion_raw = _load_notion_csv(Path(notion_csv))

    return _run_audit(
        close_raw=close_raw,
        ghl_raw=ghl_raw,
        notion_raw=notion_raw,
        out_dir=Path(out_dir),
        now=now,
        recent_window_days=recent_window_days,
    )


def _run_audit(
    *,
    close_raw: List[Dict[str, Any]],
    ghl_raw: List[Dict[str, Any]],
    notion_raw: List[Dict[str, Any]],
    out_dir: Path,
    now: datetime,
    recent_window_days: int,
) -> Dict[str, Any]:
    close_records = [_close_to_record(l) for l in close_raw]
    ghl_records = [_ghl_to_record(c) for c in ghl_raw]
    notion_records = [_notion_row_to_record(r) for r in notion_raw]

    index = build_record_index(close_records, ghl_records, notion_records)
    duplicate_phones = _detect_duplicate_phones(close_records)

    rows: List[ReportRow] = []
    for cr in close_records:
        match = match_records(cr, index)

        # Find linked records by ID
        ghl_link: Optional[Dict[str, Any]] = None
        if match.ghl_id:
            ghl_link = next((g for g in ghl_records if g.get("source_id") == match.ghl_id), None)
        notion_link: Optional[Dict[str, Any]] = None
        if match.notion_id:
            notion_link = next((n for n in notion_records if n.get("source_id") == match.notion_id), None)

        phones = [p for p in (cr.get("phones") or []) if normalize_phone(p)]
        normed_phones = [normalize_phone(p) for p in phones]
        is_dup = any(p in duplicate_phones for p in normed_phones)

        ctx = ClassificationContext(
            close_lead_id=cr.get("source_id", ""),
            ghl_contact_id=match.ghl_id,
            notion_page_id=match.notion_id,
            lead_name=cr.get("name", ""),
            phones=normed_phones,
            emails=[normalize_email(e) for e in (cr.get("emails") or []) if normalize_email(e)],
            close_status=cr.get("close_status"),
            cadence_stage=cr.get("cadence_stage"),
            ghl_tags=(ghl_link or {}).get("tags", []) or [],
            notion_status=(notion_link or {}).get("notion_status"),
            notion_opportunity_stage=(notion_link or {}).get("notion_opportunity_stage"),
            close_activities=cr.get("activities", []) or [],
            notion_body=(notion_link or {}).get("notion_body", "") or "",
            ambiguous_match=match.ambiguous,
            duplicate_phone=is_dup,
            now=now,
            recent_window_days=recent_window_days,
        )
        classification = classify_lead(ctx)
        row = build_report_row(
            close_record={**cr, "source_id": cr.get("source_id", "")},
            match=match,
            classification=classification,
            notion_record=notion_link,
            ghl_record=ghl_link,
        )
        rows.append(row)

    return write_report(rows, out_dir)
