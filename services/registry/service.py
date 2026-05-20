from __future__ import annotations

import hashlib
import json
import os
from dataclasses import asdict, dataclass
from collections import Counter
from datetime import datetime, timezone
from typing import Any, Iterable, Optional

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from db.models import (
    RegistryConsentEvent,
    RegistryContactMethod,
    RegistryExternalRecord,
    RegistryHousehold,
    RegistryPerson,
    RegistryRecommendation,
    RegistrySourceSnapshot,
)
from services.lead_hygiene import normalize_email, normalize_name, normalize_phone
from services import lead_hygiene_jobs


SOURCE_COVERAGE_SOURCES = ("close", "ghl", "notion", "lead_hygiene")


@dataclass
class ImportCounters:
    job_id: str
    rows_seen: int = 0
    households_created: int = 0
    people_created: int = 0
    contact_methods_created: int = 0
    external_records_created: int = 0
    snapshots_created: int = 0
    recommendations_created: int = 0
    consent_events_created: int = 0


def _hash_payload(payload: Any) -> str:
    data = json.dumps(payload, sort_keys=True, default=str, separators=(",", ":"))
    return hashlib.sha256(data.encode("utf-8")).hexdigest()


def _risk_level(row: dict[str, Any]) -> str:
    bucket = (row.get("recommended_bucket") or "").lower()
    flags = {str(v).lower() for v in row.get("risk_flags") or []}
    if bucket in {"do-not-contact", "not-interested", "invalid"} or "hard_stop" in flags:
        return "high"
    if bucket in {"duplicate", "needs-review", "missing-phone"} or flags:
        return "medium"
    return "low"


def _split_name(display_name: str) -> tuple[Optional[str], Optional[str]]:
    parts = [p for p in display_name.split() if p]
    if not parts:
        return None, None
    if len(parts) == 1:
        return parts[0], None
    return parts[0], " ".join(parts[1:])


def _names_agree(left: str, right: str) -> bool:
    left_name = normalize_name(left)
    right_name = normalize_name(right)
    if not left_name or not right_name:
        return False
    if left_name == right_name:
        return True
    left_last = left_name.split()[-1] if len(left_name.split()) > 1 else None
    right_last = right_name.split()[-1] if len(right_name.split()) > 1 else None
    return bool(left_last and right_last and left_last.lower() == right_last.lower())


async def _scalar_count(session: AsyncSession, model) -> int:
    return int(await session.scalar(select(func.count()).select_from(model)) or 0)


async def summary(session: AsyncSession) -> dict[str, Any]:
    latest_snapshot = await session.scalar(
        select(RegistrySourceSnapshot).order_by(RegistrySourceSnapshot.created_at.desc()).limit(1)
    )
    return {
        "counts": {
            "households": await _scalar_count(session, RegistryHousehold),
            "people": await _scalar_count(session, RegistryPerson),
            "contact_methods": await _scalar_count(session, RegistryContactMethod),
            "external_records": await _scalar_count(session, RegistryExternalRecord),
            "recommendations": await _scalar_count(session, RegistryRecommendation),
            "consent_events": await _scalar_count(session, RegistryConsentEvent),
        },
        "last_import": {
            "source_ref": latest_snapshot.source_ref if latest_snapshot else None,
            "created_at": latest_snapshot.created_at if latest_snapshot else None,
            "record_count": latest_snapshot.record_count if latest_snapshot else None,
        },
        "review_only": True,
    }


def _mask_phone(value: Optional[str]) -> Optional[str]:
    if not value:
        return None
    digits = "".join(ch for ch in str(value) if ch.isdigit())
    if len(digits) < 4:
        return "masked"
    return f"***-***-{digits[-4:]}"


def _mask_email(value: Optional[str]) -> Optional[str]:
    if not value or "@" not in value:
        return None if not value else "masked"
    local, domain = value.split("@", 1)
    if not local:
        return f"*@{domain}"
    return f"{local[:1]}***@{domain}"


def _source_display_label(source: Optional[str]) -> str:
    labels = {
        "close": "Close",
        "ghl": "GHL",
        "notion": "Notion",
        "lead_hygiene": "Lead Hygiene",
        "report": "Lead Hygiene",
    }
    return labels.get(str(source or "").lower(), str(source or "Unknown").replace("_", " ").title())


def _household_sources(household: RegistryHousehold) -> list[str]:
    sources = {record.source for record in household.external_records if record.source and record.source != "report"}
    if household.derived_from:
        sources.add(household.derived_from)
    if household.recommendations:
        sources.add("lead_hygiene")
    return sorted(sources)


def _bucket_counts(household: RegistryHousehold) -> dict[str, int]:
    return dict(Counter(rec.recommendation_type or "other" for rec in household.recommendations))


def _has_hard_stop(household: RegistryHousehold) -> bool:
    for rec in household.recommendations:
        evidence = rec.evidence if isinstance(rec.evidence, dict) else {}
        flags = {str(flag).lower() for flag in evidence.get("risk_flags") or []}
        if rec.recommendation_type in {"do-not-contact", "not-interested", "invalid"} or "hard_stop" in flags:
            return True
    for event in household.consent_events:
        text = f"{event.event_type or ''} {event.evidence or ''}".lower()
        if "hard_stop" in text or "do not contact" in text:
            return True
    return False


def _rollup_household(household: RegistryHousehold, *, mask_contact: bool = True) -> dict[str, Any]:
    contact_counts = Counter(contact.kind for contact in household.contact_methods)
    sources = _household_sources(household)
    buckets = _bucket_counts(household)
    latest_seen_candidates = [
        household.last_seen_at,
        *(record.last_seen_at for record in household.external_records),
        *(rec.updated_at or rec.created_at for rec in household.recommendations),
        *(event.observed_at or event.created_at for event in household.consent_events),
    ]
    latest_seen_at = max((item for item in latest_seen_candidates if item), default=None)
    latest_source = sources[-1] if sources else household.derived_from
    hard_stop_count = 1 if _has_hard_stop(household) else 0
    return {
        "id": household.id,
        "display_name": household.display_name,
        "status": household.status,
        "risk_level": household.risk_level,
        "confidence": household.confidence,
        "primary_phone": _mask_phone(household.primary_phone) if mask_contact else household.primary_phone,
        "primary_email": _mask_email(household.primary_email) if mask_contact else household.primary_email,
        "derived_from": household.derived_from,
        "updated_at": household.updated_at,
        "people_count": len(household.people),
        "contact_method_count": len(household.contact_methods),
        "phone_count": int(contact_counts.get("phone") or 0),
        "email_count": int(contact_counts.get("email") or 0),
        "address_count": int(contact_counts.get("address") or 0),
        "sources": sources,
        "source_count": len(sources),
        "recommendation_count": len(household.recommendations),
        "high_risk_recommendation_count": sum(1 for rec in household.recommendations if rec.risk_level == "high"),
        "dnc_event_count": sum(1 for event in household.consent_events if "dnc" in (event.event_type or "").lower()),
        "hard_stop_count": hard_stop_count,
        "bucket_counts": buckets,
        "latest_seen_at": latest_seen_at,
        "latest_source_label": _source_display_label(latest_source) if latest_source else None,
    }


def household_row(household: RegistryHousehold) -> dict[str, Any]:
    return _rollup_household(household, mask_contact=True)


async def list_households(
    session: AsyncSession,
    limit: int,
    offset: int,
    *,
    q: Optional[str] = None,
    risk: Optional[str] = None,
    source: Optional[str] = None,
    bucket: Optional[str] = None,
    has_dnc: Optional[bool] = None,
    has_conflict: Optional[bool] = None,
    sort: str = "latest",
) -> list[dict[str, Any]]:
    result = await session.execute(
        select(RegistryHousehold)
        .options(
            selectinload(RegistryHousehold.people),
            selectinload(RegistryHousehold.contact_methods),
            selectinload(RegistryHousehold.external_records),
            selectinload(RegistryHousehold.recommendations),
            selectinload(RegistryHousehold.consent_events),
        )
    )
    rows = [_rollup_household(household) for household in result.scalars().all()]

    if q:
        needle = q.strip().lower()
        rows = [
            row for row in rows
            if needle in (row["display_name"] or "").lower()
            or any(needle in str(item).lower() for item in row["sources"])
        ]
    if risk:
        risks = {item.strip().lower() for item in risk.split(",") if item.strip()}
        rows = [row for row in rows if str(row["risk_level"]).lower() in risks]
    if source:
        sources = {item.strip().lower() for item in source.split(",") if item.strip()}
        rows = [row for row in rows if sources.intersection({item.lower() for item in row["sources"]})]
    if bucket:
        buckets = {item.strip().lower() for item in bucket.split(",") if item.strip()}
        rows = [
            row for row in rows
            if buckets.intersection({item.lower() for item in row["bucket_counts"]})
        ]
    if has_dnc is not None:
        rows = [row for row in rows if (row["dnc_event_count"] > 0) is has_dnc]
    if has_conflict is not None:
        rows = [row for row in rows if (row["high_risk_recommendation_count"] > 0 or row["hard_stop_count"] > 0) is has_conflict]

    if sort == "risk":
        rank = {"high": 0, "medium": 1, "low": 2, "unknown": 3}
        rows.sort(key=lambda row: (rank.get(str(row["risk_level"]).lower(), 9), -(row["recommendation_count"] or 0)))
    elif sort == "recommendations":
        rows.sort(key=lambda row: row["recommendation_count"], reverse=True)
    elif sort == "name":
        rows.sort(key=lambda row: row["display_name"].lower())
    else:
        rows.sort(key=lambda row: row["latest_seen_at"] or row["updated_at"] or datetime.min.replace(tzinfo=timezone.utc), reverse=True)

    return rows[offset:offset + limit]


async def household_detail(session: AsyncSession, household_id: int) -> Optional[RegistryHousehold]:
    return await session.scalar(
        select(RegistryHousehold)
        .where(RegistryHousehold.id == household_id)
        .options(
            selectinload(RegistryHousehold.people),
            selectinload(RegistryHousehold.contact_methods),
            selectinload(RegistryHousehold.external_records),
            selectinload(RegistryHousehold.recommendations),
            selectinload(RegistryHousehold.consent_events),
        )
    )


def _bucket_label(bucket: str) -> str:
    labels = {
        "do-not-contact": "Do not contact",
        "not-interested": "Not interested",
        "invalid": "Invalid",
        "needs-review": "Needs review",
        "duplicate": "Duplicate",
        "missing-phone": "Missing phone",
        "re-engage-ready": "Re-engage ready",
        "already-automated": "Already automated",
        "recently-contacted": "Recently contacted",
        "existing-client": "Existing client",
    }
    return labels.get(bucket, bucket.replace("_", " ").replace("-", " ").title() if bucket else "Other")


def _safe_node_id(column: str, value: str) -> str:
    cleaned = "".join(ch if ch.isalnum() else "_" for ch in value.lower()).strip("_")
    return f"{column}:{cleaned or 'unknown'}"


def _as_naive_utc(value: Optional[datetime]) -> Optional[datetime]:
    if value is None:
        return None
    if value.tzinfo is None:
        return value
    return value.astimezone(timezone.utc).replace(tzinfo=None)


def _source_coverage(households: list[RegistryHousehold]) -> list[dict[str, Any]]:
    total = len(households)
    coverage: list[dict[str, Any]] = []
    for source in SOURCE_COVERAGE_SOURCES:
        matched = sum(1 for household in households if source in _household_sources(household))
        # Current ingestion does not create orphan source rows. Missing means
        # households in this Registry slice that lack this source, not live
        # upstream rows that failed to import.
        missing = total - matched
        coverage.append(
            {
                "source": source,
                "label": _source_display_label(source),
                "total": total,
                "matched": matched,
                "missing": missing,
                "match_pct": round((matched / total) * 100, 1) if total else 0.0,
            }
        )
    return coverage


async def sankey(
    session: AsyncSession,
    *,
    from_date: Optional[datetime] = None,
    to_date: Optional[datetime] = None,
    sources: Optional[list[str]] = None,
    level: str = "household",
    top_n: int = 8,
    include_unknown_risk: bool = True,
) -> dict[str, Any]:
    result = await session.execute(
        select(RegistryHousehold)
        .options(
            selectinload(RegistryHousehold.people),
            selectinload(RegistryHousehold.contact_methods),
            selectinload(RegistryHousehold.external_records),
            selectinload(RegistryHousehold.recommendations),
            selectinload(RegistryHousehold.consent_events),
        )
    )
    households = list(result.scalars().all())
    source_filter = {item.strip().lower() for item in (sources or []) if item and item.strip()}

    filtered: list[RegistryHousehold] = []
    from_cmp = _as_naive_utc(from_date)
    to_cmp = _as_naive_utc(to_date)
    for household in households:
        seen_at = _as_naive_utc(household.last_seen_at or household.updated_at or household.created_at)
        if from_cmp and seen_at and seen_at < from_cmp:
            continue
        if to_cmp and seen_at and seen_at > to_cmp:
            continue
        household_sources = _household_sources(household)
        if source_filter and not source_filter.intersection({item.lower() for item in household_sources}):
            continue
        if not include_unknown_risk and (household.risk_level or "unknown") == "unknown":
            continue
        filtered.append(household)

    node_counts: Counter[tuple[str, str]] = Counter()
    link_counts: Counter[tuple[tuple[str, str], tuple[str, str]]] = Counter()
    bucket_totals: Counter[str] = Counter()
    for household in filtered:
        household_sources = _household_sources(household) or ["unknown"]
        risk = household.risk_level or "unknown"
        buckets = _bucket_counts(household) or {"other": 1}
        for bucket, count in buckets.items():
            bucket_totals[bucket] += count
        primary_buckets = [bucket for bucket, _ in Counter(buckets).most_common(max(1, top_n))]
        hard_stop = _has_hard_stop(household)
        status = "locked" if hard_stop else "proposed"

        # Source overlap is real, so source -> risk links are counted once per
        # household/source pair. Downstream risk/bucket/state counts must stay
        # household-level or multi-source households inflate every later column.
        node_counts[("risk", risk)] += 1
        node_counts[("state", status)] += 1
        for source in household_sources:
            if source_filter and source.lower() not in source_filter:
                continue
            node_counts[("source", source)] += 1
            link_counts[(("source", source), ("risk", risk))] += 1
        for bucket in primary_buckets:
            node_counts[("bucket", bucket)] += 1
            link_counts[(("risk", risk), ("bucket", bucket))] += 1
            link_counts[(("bucket", bucket), ("state", status))] += 1

    top_buckets = {bucket for bucket, _ in bucket_totals.most_common(max(1, top_n))}
    if top_buckets:
        remapped_link_counts: Counter[tuple[tuple[str, str], tuple[str, str]]] = Counter()
        remapped_node_counts: Counter[tuple[str, str]] = Counter()
        for (column, value), count in node_counts.items():
            mapped = "other" if column == "bucket" and value not in top_buckets else value
            remapped_node_counts[(column, mapped)] += count
        for (left, right), count in link_counts.items():
            left = (left[0], "other") if left[0] == "bucket" and left[1] not in top_buckets else left
            right = (right[0], "other") if right[0] == "bucket" and right[1] not in top_buckets else right
            remapped_link_counts[(left, right)] += count
        node_counts = remapped_node_counts
        link_counts = remapped_link_counts

    labels = {
        "source": _source_display_label,
        "risk": lambda value: value.title(),
        "bucket": _bucket_label,
        "state": lambda value: "Locked / review-only" if value == "locked" else "Proposed",
    }
    nodes = [
        {
            "id": _safe_node_id(column, value),
            "label": labels[column](value),
            "column": column,
            "count": count,
        }
        for (column, value), count in sorted(node_counts.items(), key=lambda item: (item[0][0], item[0][1]))
    ]
    links = [
        {
            "source": _safe_node_id(left[0], left[1]),
            "target": _safe_node_id(right[0], right[1]),
            "value": count,
        }
        for (left, right), count in sorted(link_counts.items(), key=lambda item: (item[0][0], item[0][1]))
    ]
    return {
        "generated_at": datetime.now(timezone.utc),
        "level": level,
        "filters": {
            "from": from_date,
            "to": to_date,
            "sources": sorted(source_filter),
            "include_unknown_risk": include_unknown_risk,
            "top_n": top_n,
        },
        "nodes": nodes,
        "links": links,
        "totals": {
            "households": len(filtered),
            "people": sum(len(household.people) for household in filtered),
            "contact_methods": sum(len(household.contact_methods) for household in filtered),
            "recommendations": sum(len(household.recommendations) for household in filtered),
            "links": len(links),
        },
        "source_coverage": _source_coverage(filtered),
        "coverage_universe": len(filtered),
        "truncated": len(bucket_totals) > top_n,
    }


async def list_people(session: AsyncSession, limit: int, offset: int) -> list[RegistryPerson]:
    result = await session.execute(
        select(RegistryPerson).order_by(RegistryPerson.updated_at.desc()).offset(offset).limit(limit)
    )
    return list(result.scalars().all())


async def person_detail(session: AsyncSession, person_id: int) -> Optional[RegistryPerson]:
    return await session.scalar(
        select(RegistryPerson)
        .where(RegistryPerson.id == person_id)
        .options(
            selectinload(RegistryPerson.household),
            selectinload(RegistryPerson.contact_methods),
        )
    )


async def external_records_for_person(session: AsyncSession, person_id: int) -> list[RegistryExternalRecord]:
    result = await session.execute(select(RegistryExternalRecord).where(RegistryExternalRecord.person_id == person_id))
    return list(result.scalars().all())


async def recommendations_for_person(session: AsyncSession, person_id: int) -> list[RegistryRecommendation]:
    result = await session.execute(select(RegistryRecommendation).where(RegistryRecommendation.person_id == person_id))
    return list(result.scalars().all())


async def consent_events_for_person(session: AsyncSession, person_id: int) -> list[RegistryConsentEvent]:
    result = await session.execute(select(RegistryConsentEvent).where(RegistryConsentEvent.person_id == person_id))
    return list(result.scalars().all())


async def search(session: AsyncSession, q: str, limit: int = 25) -> dict[str, list[Any]]:
    q = (q or "").strip()
    if not q:
        return {"households": [], "people": [], "contact_methods": [], "external_records": []}

    phone = normalize_phone(q)
    email = normalize_email(q)
    name = normalize_name(q)

    contact_filters = []
    if phone:
        contact_filters.append(RegistryContactMethod.normalized_value == phone)
    if email:
        contact_filters.append(RegistryContactMethod.normalized_value == email)
    contact_filters.append(RegistryContactMethod.normalized_value.ilike(f"%{q.lower()}%"))

    contact_result = await session.execute(
        select(RegistryContactMethod).where(or_(*contact_filters)).limit(limit)
    )
    contacts = list(contact_result.scalars().all())

    household_result = await session.execute(
        select(RegistryHousehold)
        .options(
            selectinload(RegistryHousehold.people),
            selectinload(RegistryHousehold.contact_methods),
            selectinload(RegistryHousehold.external_records),
            selectinload(RegistryHousehold.recommendations),
            selectinload(RegistryHousehold.consent_events),
        )
        .where(
            or_(
                RegistryHousehold.display_name.ilike(f"%{name or q}%"),
                RegistryHousehold.primary_phone == phone if phone else False,
                RegistryHousehold.primary_email == email if email else False,
            )
        )
        .limit(limit)
    )
    people_result = await session.execute(
        select(RegistryPerson).where(RegistryPerson.display_name.ilike(f"%{name or q}%")).limit(limit)
    )
    external_result = await session.execute(
        select(RegistryExternalRecord).where(RegistryExternalRecord.external_id.ilike(f"%{q}%")).limit(limit)
    )
    return {
        "households": list(household_result.scalars().all()),
        "people": list(people_result.scalars().all()),
        "contact_methods": contacts,
        "external_records": list(external_result.scalars().all()),
    }


async def recommendations(session: AsyncSession, limit: int, offset: int) -> list[RegistryRecommendation]:
    result = await session.execute(
        select(RegistryRecommendation)
        .order_by(RegistryRecommendation.created_at.desc())
        .offset(offset)
        .limit(limit)
    )
    return list(result.scalars().all())


async def consent_events(session: AsyncSession, limit: int, offset: int) -> list[RegistryConsentEvent]:
    result = await session.execute(
        select(RegistryConsentEvent)
        .order_by(RegistryConsentEvent.created_at.desc())
        .offset(offset)
        .limit(limit)
    )
    return list(result.scalars().all())


def connection_statuses() -> list[dict[str, Any]]:
    try:
        from config import get_settings
        settings = get_settings()
        close_key = getattr(settings, "close_api_key", "") or os.environ.get("CLOSE_API_KEY", "")
        ghl_key = getattr(settings, "ghl_api_key", "") or os.environ.get("GHL_API_KEY", "")
        notion_token = getattr(settings, "notion_token", "") or os.environ.get("NOTION_TOKEN", "")
    except Exception:  # noqa: BLE001
        close_key = os.environ.get("CLOSE_API_KEY", "")
        ghl_key = os.environ.get("GHL_API_KEY", "")
        notion_token = os.environ.get("NOTION_TOKEN", "")
    return [
        {"source": "close", "configured": bool(close_key), "mode": "read-only", "secret": "masked"},
        {"source": "ghl", "configured": bool(ghl_key), "mode": "read-only", "secret": "masked"},
        {"source": "notion", "configured": bool(notion_token), "mode": "csv/read-only", "secret": "masked"},
    ]


async def list_lead_hygiene_reports(session: AsyncSession, limit: int = 50) -> list[dict[str, Any]]:
    reports = []
    for run in await lead_hygiene_jobs.list_runs_async(session, limit=limit):
        reports.append(_lead_hygiene_report_item(run))
    return reports


def _lead_hygiene_report_item(run: dict[str, Any]) -> dict[str, Any]:
    job_id = str(run.get("job_id") or "")
    short_job_id = f"{job_id[:8]}..." if len(job_id) > 8 else job_id
    status = str(run.get("status") or "unknown")
    reports = run.get("reports") or {}
    has_json_report = bool(reports.get("json"))
    rows_seen = _summary_row_count(run.get("summary"))
    source_label = _source_label(run.get("params") or {})
    created_at = run.get("started_at")
    updated_at = run.get("finished_at") or created_at
    label = _report_label(status=status, rows_seen=rows_seen, created_at=created_at, short_job_id=short_job_id)
    return {
        "job_id": job_id,
        "short_job_id": short_job_id,
        "label": label,
        "display_name": label,
        "status": status,
        "created_at": created_at,
        "updated_at": updated_at,
        "rows_seen": rows_seen,
        "source_label": source_label,
        "has_json_report": has_json_report,
        "importable": status == "completed" and has_json_report,
    }


def _summary_row_count(summary: Any) -> Optional[int]:
    if not isinstance(summary, dict):
        return None
    for key in ("total", "total_rows", "rows_seen", "row_count"):
        value = summary.get(key)
        if isinstance(value, int):
            return value
    return None


def _source_label(params: dict[str, Any]) -> str:
    if params.get("fixture_mode"):
        return "Fixture"
    pieces = ["Close"]
    if params.get("include_ghl", True):
        pieces.append("GHL")
    if params.get("notion_csv_path"):
        pieces.append("Notion CSV")
    return " + ".join(pieces)


def _report_label(status: str, rows_seen: Optional[int], created_at: Any, short_job_id: str) -> str:
    status_label = status.replace("_", " ").title()
    row_label = f"{rows_seen:,} rows" if isinstance(rows_seen, int) else "rows unknown"
    date_label = str(created_at or "date unknown")
    return f"{status_label} - {row_label} - {date_label} - {short_job_id}"


async def import_lead_hygiene_report(session: AsyncSession, job_id: str) -> ImportCounters:
    payload = await lead_hygiene_jobs.load_report_payload_async(session, job_id)
    rows = payload.get("rows") or []
    counters = ImportCounters(job_id=job_id, rows_seen=len(rows))
    for idx, row in enumerate(rows):
        await _import_row(session, job_id, idx, row, counters)
    await session.flush()
    return counters


async def _find_household(session: AsyncSession, row: dict[str, Any], phone: str, email: str, name: str) -> Optional[RegistryHousehold]:
    for source, external_type, external_id in _external_ids(row):
        existing = await session.scalar(
            select(RegistryExternalRecord).where(
                RegistryExternalRecord.source == source,
                RegistryExternalRecord.external_type == external_type,
                RegistryExternalRecord.external_id == external_id,
            )
        )
        if existing and existing.household_id:
            return await session.get(RegistryHousehold, existing.household_id)

    if phone or email:
        result = await session.execute(
            select(RegistryContactMethod).where(
                RegistryContactMethod.normalized_value.in_([v for v in (phone, email) if v])
            )
        )
        for contact in result.scalars().all():
            household = await session.get(RegistryHousehold, contact.household_id)
            if household and _names_agree(name, household.display_name):
                return household

    return None


async def _import_row(
    session: AsyncSession,
    job_id: str,
    row_index: int,
    row: dict[str, Any],
    counters: ImportCounters,
) -> None:
    name = normalize_name(row.get("lead_name") or row.get("name") or "Unknown Lead") or "Unknown Lead"
    phone = normalize_phone(row.get("phone") or "")
    email = normalize_email(row.get("email") or "")
    risk = _risk_level(row)
    confidence = float(row.get("confidence") or 0.0)

    household = await _find_household(session, row, phone, email, name)
    if household is None:
        household = RegistryHousehold(
            display_name=name,
            risk_level=risk,
            confidence=confidence,
            primary_phone=phone or None,
            primary_email=email or None,
            derived_from="lead_hygiene",
        )
        session.add(household)
        await session.flush()
        counters.households_created += 1
    else:
        household.risk_level = risk if risk != "low" else household.risk_level
        household.confidence = max(float(household.confidence or 0.0), confidence)
        household.primary_phone = household.primary_phone or phone or None
        household.primary_email = household.primary_email or email or None

    person = await session.scalar(
        select(RegistryPerson).where(
            RegistryPerson.household_id == household.id,
            RegistryPerson.display_name == name,
        )
    )
    if person is None:
        first, last = _split_name(name)
        person = RegistryPerson(
            household_id=household.id,
            display_name=name,
            first_name=first,
            last_name=last,
            role="primary",
            dnc_status="inferred" if risk == "high" else "unknown",
            consent_status="review_required" if risk in {"high", "medium"} else "unknown",
        )
        session.add(person)
        await session.flush()
        counters.people_created += 1

    contact_by_value: dict[str, RegistryContactMethod] = {}
    for kind, raw, normalized in (("phone", row.get("phone") or phone, phone), ("email", row.get("email") or email, email)):
        if not normalized:
            continue
        contact = await session.scalar(
            select(RegistryContactMethod).where(
                RegistryContactMethod.household_id == household.id,
                RegistryContactMethod.kind == kind,
                RegistryContactMethod.normalized_value == normalized,
            )
        )
        if contact is None:
            contact = RegistryContactMethod(
                household_id=household.id,
                person_id=person.id,
                kind=kind,
                raw_value=str(raw or normalized),
                normalized_value=normalized,
                validity_status="valid" if kind == "email" or len(normalized) >= 10 else "unknown",
                consent_status=person.consent_status,
                is_primary=True,
            )
            session.add(contact)
            await session.flush()
            counters.contact_methods_created += 1
        contact_by_value[kind] = contact

    snapshot_hash = _hash_payload({"job_id": job_id, "row_index": row_index, "row": row})
    snapshot = await session.scalar(
        select(RegistrySourceSnapshot).where(RegistrySourceSnapshot.payload_hash == snapshot_hash)
    )
    if snapshot is None:
        snapshot = RegistrySourceSnapshot(
            source="lead_hygiene",
            source_type="report_row",
            source_ref=job_id,
            payload_hash=snapshot_hash,
            payload=row,
            record_count=1,
            notes="Imported from Lead Hygiene report.",
        )
        session.add(snapshot)
        await session.flush()
        counters.snapshots_created += 1

    first_external: Optional[RegistryExternalRecord] = None
    for source, external_type, external_id in _external_ids(row):
        record = await session.scalar(
            select(RegistryExternalRecord).where(
                RegistryExternalRecord.source == source,
                RegistryExternalRecord.external_type == external_type,
                RegistryExternalRecord.external_id == external_id,
            )
        )
        if record is None:
            record = RegistryExternalRecord(
                household_id=household.id,
                person_id=person.id,
                contact_method_id=(contact_by_value.get("phone") or contact_by_value.get("email") or None).id
                if contact_by_value
                else None,
                source=source,
                external_type=external_type,
                external_id=external_id,
                match_basis=_match_basis(row, phone, email),
                match_confidence=confidence,
                match_reason=row.get("reason"),
                payload_hash=snapshot_hash,
            )
            session.add(record)
            await session.flush()
            counters.external_records_created += 1
        first_external = first_external or record

    rec_type = row.get("recommended_bucket") or "review"
    recommendation = await session.scalar(
        select(RegistryRecommendation).where(
            RegistryRecommendation.household_id == household.id,
            RegistryRecommendation.source_snapshot_id == snapshot.id,
            RegistryRecommendation.recommendation_type == rec_type,
        )
    )
    if recommendation is None:
        recommendation = RegistryRecommendation(
            household_id=household.id,
            person_id=person.id,
            external_record_id=first_external.id if first_external else None,
            source_snapshot_id=snapshot.id,
            recommendation_type=rec_type,
            status="proposed",
            risk_level=risk,
            confidence=confidence,
            evidence={
                "risk_flags": row.get("risk_flags") or [],
                "reason": row.get("reason"),
                "recommended_close_update": row.get("recommended_close_update"),
                "recommended_ghl_tags": row.get("recommended_ghl_tags") or [],
            },
        )
        session.add(recommendation)
        await session.flush()
        counters.recommendations_created += 1

    evidence = row.get("reason") or ", ".join(row.get("risk_flags") or []) or rec_type
    event_type = "dnc_or_consent_review" if risk in {"high", "medium"} else "source_observed"
    existing_event = await session.scalar(
        select(RegistryConsentEvent).where(
            RegistryConsentEvent.household_id == household.id,
            RegistryConsentEvent.person_id == person.id,
            RegistryConsentEvent.event_type == event_type,
            RegistryConsentEvent.evidence == evidence,
        )
    )
    if existing_event is None:
        event = RegistryConsentEvent(
            household_id=household.id,
            person_id=person.id,
            contact_method_id=(contact_by_value.get("phone") or contact_by_value.get("email") or None).id
            if contact_by_value
            else None,
            external_record_id=first_external.id if first_external else None,
            event_type=event_type,
            source="lead_hygiene",
            evidence=evidence,
        )
        session.add(event)
        counters.consent_events_created += 1


def _external_ids(row: dict[str, Any]) -> Iterable[tuple[str, str, str]]:
    for source, external_type, key in (
        ("close", "lead", "close_lead_id"),
        ("ghl", "contact", "ghl_contact_id"),
        ("notion", "page", "notion_page_id"),
    ):
        value = str(row.get(key) or "").strip()
        if value:
            yield source, external_type, value
    row_hash = _hash_payload(row)
    yield "report", "report_item", row_hash


def _match_basis(row: dict[str, Any], phone: str, email: str) -> str:
    if row.get("close_lead_id"):
        return "close_lead_id"
    if row.get("ghl_contact_id"):
        return "ghl_contact_id"
    if phone:
        return "phone"
    if email:
        return "email"
    return "name"


def import_summary_dict(counters: ImportCounters) -> dict[str, Any]:
    return asdict(counters)
