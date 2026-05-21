from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from db.models import RegistryHousehold, RegistrySourceSnapshot
from services.registry.service import _mask_email, _mask_phone


PROPOSED_TAG = "reengage-staging"
MAX_BATCH_SIZE = 1000
CHANNEL_MODES = {"sms_only", "rvm_only", "sms_rvm", "export_only"}

SMS_OPENER = (
    "Hey {first_name}, it's Seb. You had looked into coverage a while back "
    "and I was cleaning up old requests. Did you ever get that handled?"
)
FOLLOW_UP_SMS = "No worries either way, I just didn't want to close it out if you still needed numbers."
RVM_SCRIPT = (
    "Hey {first_name}, this is Seb. You had requested info a while back about coverage. "
    "I'm cleaning up old files and wanted to check if you ever got that handled. "
    "Shoot me a text back when you get a chance."
)

DO_NOT_TOUCH_BUCKETS = {"do-not-contact", "not-interested", "client", "invalid"}
NEEDS_REVIEW_BUCKETS = {
    "needs-review",
    "duplicate",
    "missing-phone",
    "previous-outreach-detected",
    "recently-contacted",
    "already-automated",
}
HARD_STOP_FLAGS = {
    "hard_stop",
    "stop_language",
    "sms_opt_out",
    "dnc_language",
    "not_interested_status",
    "client_status",
    "invalid_status",
}
REVIEW_FLAGS = {"missing_phone", "duplicate_phone", "ambiguous_match"}
AUTOMATION_FLAGS = {"ghl_workflow_detected", "rvm_tag_detected"}


@dataclass
class ReengagementRow:
    household_id: int
    recommendation_id: Optional[int]
    source_snapshot_id: Optional[int]
    display_name: str
    first_name: Optional[str]
    last_name: Optional[str]
    phone: Optional[str]
    email: Optional[str]
    risk_level: str
    confidence: Optional[float]
    bucket: str
    pool: str
    sources: list[str]
    close_lead_id: Optional[str]
    ghl_contact_id: Optional[str]
    source_ref: Optional[str]
    latest_seen_at: Optional[datetime]
    last_outbound_touch: Optional[str]
    last_inbound_touch: Optional[str]
    last_appointment: Optional[str]
    never_responded: bool
    eligibility_reason: Optional[str]
    risk_flags: list[str]
    reason: Optional[str]
    excluded_reasons: list[str]
    locked_reason: Optional[str]

    def public(self, *, mask_contact: bool = True) -> dict[str, Any]:
        return {
            "household_id": self.household_id,
            "recommendation_id": self.recommendation_id,
            "source_snapshot_id": self.source_snapshot_id,
            "display_name": self.display_name,
            "first_name": self.first_name,
            "last_name": self.last_name,
            "masked_phone": _mask_phone(self.phone) if mask_contact else self.phone,
            "masked_email": _mask_email(self.email) if mask_contact else self.email,
            "risk_level": self.risk_level,
            "confidence": self.confidence,
            "bucket": self.bucket,
            "pool": self.pool,
            "sources": self.sources,
            "close_lead_id": self.close_lead_id,
            "ghl_contact_id": self.ghl_contact_id,
            "source_ref": self.source_ref,
            "latest_seen_at": self.latest_seen_at,
            "last_outbound_touch": self.last_outbound_touch,
            "last_inbound_touch": self.last_inbound_touch,
            "last_appointment": self.last_appointment,
            "never_responded": self.never_responded,
            "eligibility_reason": self.eligibility_reason,
            "risk_flags": self.risk_flags,
            "reason": self.reason,
            "excluded_reasons": self.excluded_reasons,
            "locked_reason": self.locked_reason,
            "proposed_tag": PROPOSED_TAG,
        }


def copy_preview() -> dict[str, str]:
    return {
        "sms_opener": SMS_OPENER,
        "follow_up_sms": FOLLOW_UP_SMS,
        "rvm_script": RVM_SCRIPT,
    }


async def summary(session: AsyncSession, *, recent_window_days: int = 30) -> dict[str, Any]:
    rows = await _all_rows(session, recent_window_days=recent_window_days)
    counts = Counter(row.pool for row in rows)
    latest = await session.scalar(
        select(RegistrySourceSnapshot).order_by(RegistrySourceSnapshot.created_at.desc()).limit(1)
    )
    return {
        "eligible": counts.get("eligible", 0),
        "needs_review": counts.get("needs_review", 0),
        "do_not_touch": counts.get("do_not_touch", 0),
        "excluded_recent_or_automated": counts.get("excluded", 0),
        "staged_batches": 0,
        "released_batches": 0,
        "persistence_enabled": False,
        "proposed_tag": PROPOSED_TAG,
        "latest_source_ref": latest.source_ref if latest else None,
        "latest_import_at": latest.created_at if latest else None,
    }


async def pool(
    session: AsyncSession,
    *,
    view: str,
    limit: int,
    offset: int,
    source: Optional[str] = None,
    risk: Optional[str] = None,
    bucket: Optional[str] = None,
    source_ref: Optional[str] = None,
    recent_window_days: int = 30,
    sort: str = "rank",
    mask_contact: bool = True,
) -> list[dict[str, Any]]:
    rows = _filter_rows(
        await _all_rows(session, recent_window_days=recent_window_days),
        view=view,
        source=source,
        risk=risk,
        bucket=bucket,
        source_ref=source_ref,
    )
    rows = _sort_rows(rows, sort=sort)
    return [row.public(mask_contact=mask_contact) for row in rows[offset:offset + limit]]


async def campaign_preview(
    session: AsyncSession,
    *,
    view: str = "eligible",
    source: Optional[str] = None,
    risk: Optional[str] = None,
    bucket: Optional[str] = None,
    source_ref: Optional[str] = None,
    recent_window_days: int = 30,
    batch_size: int = 50,
    channel_mode: str = "sms_rvm",
    sort: str = "rank",
) -> dict[str, Any]:
    if batch_size < 1 or batch_size > MAX_BATCH_SIZE:
        raise ValueError(f"batch_size must be between 1 and {MAX_BATCH_SIZE}.")
    if channel_mode not in CHANNEL_MODES:
        raise ValueError("channel_mode must be sms_only, rvm_only, sms_rvm, or export_only.")
    if view != "eligible":
        raise ValueError("campaign preview only supports the eligible pool.")

    all_rows = await _all_rows(session, recent_window_days=recent_window_days)
    eligible_rows = _filter_rows(
        all_rows,
        view="eligible",
        source=source,
        risk=risk,
        bucket=bucket,
        source_ref=source_ref,
    )
    selected = _sort_rows(eligible_rows, sort=sort)[:batch_size]
    excluded_counts = _excluded_counts(all_rows)
    return {
        "rows": [row.public(mask_contact=True) for row in selected],
        "total_eligible": len(eligible_rows),
        "selected_count": len(selected),
        "excluded_counts": excluded_counts,
        "channel_mode": channel_mode,
        "batch_size": batch_size,
        "proposed_tag": PROPOSED_TAG,
        "source_ref": source_ref or _latest_source_ref(selected),
        "copy_preview": copy_preview(),
        "confirmation_copy": (
            f"CSV export contains exactly {len(selected)} leads. "
            "FC will not send SMS, trigger RVM, retag GHL, write Close notes, create tasks, "
            "or update any external system."
        ),
    }


async def export_rows(
    session: AsyncSession,
    **kwargs: Any,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    preview = await campaign_preview(session, **kwargs)
    raw_rows = await _all_rows(session, recent_window_days=kwargs.get("recent_window_days", 30))
    by_key = {_row_key(row): row for row in raw_rows}
    channel_mode = preview["channel_mode"]
    export = []
    for public_row in preview["rows"]:
        row = by_key[_public_row_key(public_row)]
        first_name, last_name = _split_name(row.display_name, row.first_name, row.last_name)
        export.append(
            {
                "first_name": first_name or "",
                "last_name": last_name or "",
                "phone": row.phone or "",
                "email": row.email or "",
                "close_lead_id": row.close_lead_id or "",
                "ghl_contact_id": row.ghl_contact_id or "",
                "source": ",".join(row.sources),
                "proposed_tag": PROPOSED_TAG,
                "channel_mode": channel_mode,
                "batch_source_reference": row.source_ref or "",
                "last_outbound_touch": row.last_outbound_touch or "",
                "last_inbound_touch": row.last_inbound_touch or "",
                "last_appointment": row.last_appointment or "",
                "eligibility_reason": row.eligibility_reason or "",
                "never_responded": row.never_responded,
            }
        )
    return export, preview


async def _all_rows(session: AsyncSession, *, recent_window_days: int) -> list[ReengagementRow]:
    result = await session.execute(
        select(RegistryHousehold).options(
            selectinload(RegistryHousehold.contact_methods),
            selectinload(RegistryHousehold.external_records),
            selectinload(RegistryHousehold.recommendations),
            selectinload(RegistryHousehold.consent_events),
        )
    )
    households = list(result.scalars().all())
    snapshot_ids = {
        rec.source_snapshot_id
        for household in households
        for rec in household.recommendations
        if rec.source_snapshot_id
    }
    snapshots: dict[int, RegistrySourceSnapshot] = {}
    if snapshot_ids:
        snapshot_result = await session.execute(
            select(RegistrySourceSnapshot).where(RegistrySourceSnapshot.id.in_(snapshot_ids))
        )
        snapshots = {snapshot.id: snapshot for snapshot in snapshot_result.scalars().all()}

    rows: list[ReengagementRow] = []
    for household in households:
        if not household.recommendations:
            rows.append(_row_from_household(household, None, None, recent_window_days=recent_window_days))
            continue
        for rec in household.recommendations:
            rows.append(
                _row_from_household(
                    household,
                    rec,
                    snapshots.get(rec.source_snapshot_id),
                    recent_window_days=recent_window_days,
                )
            )
    return rows


def _row_from_household(
    household: RegistryHousehold,
    rec: Any,
    snapshot: Optional[RegistrySourceSnapshot],
    *,
    recent_window_days: int,
) -> ReengagementRow:
    payload = snapshot.payload if snapshot and isinstance(snapshot.payload, dict) else {}
    evidence = rec.evidence if rec is not None and isinstance(rec.evidence, dict) else {}
    bucket = str((rec.recommendation_type if rec is not None else None) or payload.get("recommended_bucket") or "needs-review")
    flags = sorted({
        str(flag)
        for flag in [
            *(payload.get("risk_flags") or []),
            *(evidence.get("risk_flags") or []),
        ]
        if flag
    })
    phone = payload.get("phone") or household.primary_phone
    email = payload.get("email") or household.primary_email
    display_name = payload.get("lead_name") or payload.get("name") or household.display_name
    first_name, last_name = _split_name(display_name)
    last_outbound_touch = payload.get("last_outbound_touch")
    last_inbound_touch = payload.get("last_inbound_touch")
    last_appointment = payload.get("last_appointment")
    risk_level = str((rec.risk_level if rec is not None else None) or household.risk_level or "unknown")
    excluded = _exclusion_reasons(
        bucket=bucket,
        flags=flags,
        phone=phone,
        risk_level=risk_level,
        last_outbound_touch=last_outbound_touch,
        last_inbound_touch=last_inbound_touch,
        last_appointment=last_appointment,
        recent_window_days=recent_window_days,
    )
    old_outbound_verified = _has_verified_old_outbound(last_outbound_touch, recent_window_days)
    pool_name = _pool_name(
        bucket=bucket,
        excluded_reasons=excluded,
        old_outbound_verified=old_outbound_verified,
    )
    never_responded = not bool(last_inbound_touch or last_appointment)
    eligibility_reason = _eligibility_reason(
        bucket=bucket,
        pool_name=pool_name,
        old_outbound_verified=old_outbound_verified,
        never_responded=never_responded,
    )
    sources = _sources(household, payload)
    return ReengagementRow(
        household_id=household.id,
        recommendation_id=(rec.id if rec is not None else None),
        source_snapshot_id=snapshot.id if snapshot else None,
        display_name=display_name,
        first_name=first_name,
        last_name=last_name,
        phone=phone,
        email=email,
        risk_level=risk_level,
        confidence=(rec.confidence if rec is not None else household.confidence),
        bucket=bucket,
        pool=pool_name,
        sources=sources,
        close_lead_id=payload.get("close_lead_id") or _external_id(household, "close"),
        ghl_contact_id=payload.get("ghl_contact_id") or _external_id(household, "ghl"),
        source_ref=snapshot.source_ref if snapshot else None,
        latest_seen_at=snapshot.created_at if snapshot else household.updated_at,
        last_outbound_touch=last_outbound_touch,
        last_inbound_touch=last_inbound_touch,
        last_appointment=last_appointment,
        never_responded=never_responded,
        eligibility_reason=eligibility_reason,
        risk_flags=flags,
        reason=payload.get("reason") or evidence.get("reason"),
        excluded_reasons=excluded,
        locked_reason=_locked_reason(pool_name, excluded),
    )


def _exclusion_reasons(
    *,
    bucket: str,
    flags: list[str],
    phone: Optional[str],
    risk_level: str,
    last_outbound_touch: Optional[str],
    last_inbound_touch: Optional[str],
    last_appointment: Optional[str],
    recent_window_days: int,
) -> list[str]:
    reasons: list[str] = []
    flag_set = {flag.lower() for flag in flags}
    bucket_l = bucket.lower()
    if not phone:
        reasons.append("missing_phone")
    if bucket_l in DO_NOT_TOUCH_BUCKETS or flag_set.intersection(HARD_STOP_FLAGS):
        reasons.append("hard_stop_or_do_not_touch")
    if bucket_l in {"duplicate", "needs-review"} or flag_set.intersection(REVIEW_FLAGS):
        reasons.append("needs_review")
    if last_inbound_touch or "inbound_response_detected" in flag_set:
        reasons.append("inbound_response_detected")
    if last_appointment or "appointment_detected" in flag_set:
        reasons.append("appointment_detected")
    if bucket_l == "recently-contacted" or _is_recent(last_outbound_touch, recent_window_days):
        reasons.append("recent_outbound_touch")
    if bucket_l == "already-automated" or flag_set.intersection(AUTOMATION_FLAGS):
        reasons.append("active_automation")
    if risk_level.lower() == "high":
        reasons.append("high_risk")
    return sorted(set(reasons))


def _pool_name(*, bucket: str, excluded_reasons: list[str], old_outbound_verified: bool) -> str:
    bucket_l = bucket.lower()
    if "hard_stop_or_do_not_touch" in excluded_reasons or bucket_l in DO_NOT_TOUCH_BUCKETS:
        return "do_not_touch"
    if (
        bucket_l in {"recently-contacted", "already-automated"}
        or "recent_outbound_touch" in excluded_reasons
        or "active_automation" in excluded_reasons
    ):
        return "excluded"
    if excluded_reasons:
        return "needs_review"
    if bucket_l == "reengage-ready":
        return "eligible"
    if bucket_l == "previous-outreach-detected" and old_outbound_verified:
        return "eligible"
    if bucket_l in NEEDS_REVIEW_BUCKETS:
        return "needs_review"
    return "needs_review"


def _eligibility_reason(
    *,
    bucket: str,
    pool_name: str,
    old_outbound_verified: bool,
    never_responded: bool,
) -> Optional[str]:
    if pool_name != "eligible" or not never_responded:
        return None
    bucket_l = bucket.lower()
    if bucket_l == "reengage-ready":
        return "reengage-ready-never-responded"
    if bucket_l == "previous-outreach-detected" and old_outbound_verified:
        return "old-outbound-never-responded"
    return None


def _filter_rows(
    rows: list[ReengagementRow],
    *,
    view: str,
    source: Optional[str],
    risk: Optional[str],
    bucket: Optional[str],
    source_ref: Optional[str],
) -> list[ReengagementRow]:
    if view not in {"eligible", "needs_review", "do_not_touch", "excluded"}:
        view = "eligible"
    filtered = [row for row in rows if row.pool == view]
    if source:
        wanted = {item.strip().lower() for item in source.split(",") if item.strip()}
        filtered = [row for row in filtered if wanted.intersection({src.lower() for src in row.sources})]
    if risk:
        wanted = {item.strip().lower() for item in risk.split(",") if item.strip()}
        filtered = [row for row in filtered if row.risk_level.lower() in wanted]
    if bucket:
        wanted = {item.strip().lower() for item in bucket.split(",") if item.strip()}
        filtered = [row for row in filtered if row.bucket.lower() in wanted]
    if source_ref:
        filtered = [row for row in filtered if row.source_ref == source_ref]
    return filtered


def _sort_rows(rows: list[ReengagementRow], *, sort: str) -> list[ReengagementRow]:
    if sort == "name":
        return sorted(rows, key=lambda row: row.display_name.lower())
    if sort == "latest":
        return sorted(rows, key=lambda row: row.latest_seen_at or datetime.min.replace(tzinfo=timezone.utc), reverse=True)
    return sorted(
        rows,
        key=lambda row: (
            _risk_rank(row.risk_level),
            -(row.confidence or 0.0),
            row.latest_seen_at or datetime.min.replace(tzinfo=timezone.utc),
            row.display_name.lower(),
        ),
    )


def _excluded_counts(rows: list[ReengagementRow]) -> dict[str, int]:
    counts: Counter[str] = Counter()
    for row in rows:
        if row.pool == "eligible":
            continue
        for reason in row.excluded_reasons or [row.pool]:
            counts[reason] += 1
    return dict(counts)


def _risk_rank(value: str) -> int:
    return {"low": 0, "medium": 1, "unknown": 2, "high": 3}.get(value.lower(), 2)


def _row_key(row: ReengagementRow) -> tuple[int, Optional[int], Optional[int], str]:
    return (row.household_id, row.recommendation_id, row.source_snapshot_id, row.bucket)


def _public_row_key(row: dict[str, Any]) -> tuple[int, Optional[int], Optional[int], str]:
    return (
        int(row["household_id"]),
        row.get("recommendation_id"),
        row.get("source_snapshot_id"),
        str(row.get("bucket") or ""),
    )


def _parse_touch_datetime(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def _is_recent(value: Optional[str], recent_window_days: int) -> bool:
    parsed = _parse_touch_datetime(value)
    if parsed is None:
        return False
    return parsed >= datetime.now(timezone.utc) - timedelta(days=recent_window_days)


def _has_verified_old_outbound(value: Optional[str], recent_window_days: int) -> bool:
    parsed = _parse_touch_datetime(value)
    if parsed is None:
        return False
    return parsed < datetime.now(timezone.utc) - timedelta(days=recent_window_days)


def _split_name(display_name: str, first_name: Optional[str] = None, last_name: Optional[str] = None) -> tuple[Optional[str], Optional[str]]:
    if first_name or last_name:
        return first_name, last_name
    parts = [part for part in (display_name or "").split() if part]
    if not parts:
        return None, None
    if len(parts) == 1:
        return parts[0], None
    return parts[0], " ".join(parts[1:])


def _sources(household: RegistryHousehold, payload: dict[str, Any]) -> list[str]:
    sources = {
        record.source
        for record in household.external_records
        if record.source and record.source != "report"
    }
    if payload.get("close_lead_id"):
        sources.add("close")
    if payload.get("ghl_contact_id"):
        sources.add("ghl")
    if payload.get("notion_page_id"):
        sources.add("notion")
    if household.derived_from:
        sources.add(household.derived_from)
    return sorted(sources)


def _external_id(household: RegistryHousehold, source: str) -> Optional[str]:
    for record in household.external_records:
        if record.source == source:
            return record.external_id
    return None


def _locked_reason(pool_name: str, excluded: list[str]) -> Optional[str]:
    if pool_name == "do_not_touch":
        return "Locked from campaign actions due to hard-stop or do-not-touch evidence."
    if pool_name == "needs_review":
        return "Held for review before batch staging."
    if pool_name == "excluded":
        return "Excluded from batches because of recent touch or active automation."
    if excluded:
        return ", ".join(excluded)
    return None


def _latest_source_ref(rows: list[ReengagementRow]) -> Optional[str]:
    for row in rows:
        if row.source_ref:
            return row.source_ref
    return None
