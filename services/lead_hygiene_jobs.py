"""Background job runner + registry for the dry-run lead hygiene audit.

This is an in-process registry suitable for FalconConnect's single-instance
FastAPI on Render. Jobs run as asyncio Tasks; their lifecycle and metadata are
held in `_REGISTRY` and snapshotted to a `meta.json` file inside the run's
report directory so completed runs survive a process restart.

NEVER writes to Close, GHL, or Notion. Only writes local report files inside
the sandboxed reports base.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import shutil
import uuid
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from db.database import _get_session_factory
from db.models import LeadHygieneReportRun

from services.lead_hygiene_collect import (
    run_audit_from_fixtures,
    run_audit_from_live,
)

logger = logging.getLogger("falconconnect.lead_hygiene_jobs")

# Reports always land here. The same env var as routers/lead_hygiene.py.
REPORTS_BASE: Path = Path(
    os.environ.get("LEAD_HYGIENE_REPORTS_BASE", "/tmp/falconconnect/lead_hygiene_reports")
).resolve()

# Sub-directory layout: run-<utc-timestamp>-<short-id>/
_RUN_DIR_RE = re.compile(r"^run-\d{8}T\d{6}Z-[a-f0-9]{12}$")
# Job IDs are 32-char hex (uuid4.hex).
_JOB_ID_RE = re.compile(r"^[a-f0-9]{32}$")
# Report kind whitelist — only files the audit actually emits.
_REPORT_FILES = {
    "csv": "lead_hygiene_report.csv",
    "json": "lead_hygiene_report.json",
}
_META_FILENAME = "meta.json"

JobStatus = str  # "queued" | "running" | "completed" | "failed" | "cancelled"


@dataclass
class JobParams:
    limit: int = 100
    status_label: Optional[str] = None
    extra_query: Optional[str] = None
    recent_window_days: int = 30
    include_ghl: bool = True
    notion_csv_path: Optional[str] = None
    fixture_mode: bool = False


@dataclass
class JobRecord:
    job_id: str
    status: JobStatus
    params: Dict[str, Any]
    started_at: str
    finished_at: Optional[str] = None
    phase: str = "queued"
    summary: Optional[Dict[str, Any]] = None
    csv_path: Optional[str] = None
    json_path: Optional[str] = None
    meta_path: Optional[str] = None
    run_dir: Optional[str] = None
    error: Optional[str] = None
    sources: Dict[str, Dict[str, Any]] = field(default_factory=dict)

    def to_public(self) -> Dict[str, Any]:
        """Public-facing dict — strips raw filesystem paths and internal metadata."""
        public_params = dict(self.params)
        public_params["notion_csv_path"] = bool(public_params.get("notion_csv_path"))
        row_count = _summary_row_count(self.summary)
        return {
            "job_id": self.job_id,
            "short_job_id": self.job_id[:8],
            "label": _display_label(
                status=self.status,
                row_count=row_count,
                started_at=self.started_at,
                short_job_id=self.job_id[:8],
            ),
            "status": self.status,
            "phase": self.phase,
            "params": public_params,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "summary": self.summary,
            "row_count": row_count,
            "error": self.error,
            "sources": self.sources,
            "reports": _available_reports(self.run_dir),
        }


_REGISTRY: Dict[str, JobRecord] = {}
_TASKS: Dict[str, asyncio.Task] = {}
_LOCK = asyncio.Lock()


def _new_job_id() -> str:
    return uuid.uuid4().hex


def _run_dirname(started_at: datetime, job_id: str) -> str:
    return f"run-{started_at.strftime('%Y%m%dT%H%M%SZ')}-{job_id[:12]}"


def _resolve_run_dir(run_dirname: str) -> Path:
    """Return the on-disk path for a run dirname, validated against the base."""
    base = REPORTS_BASE
    base.mkdir(parents=True, exist_ok=True)
    if not _RUN_DIR_RE.match(run_dirname):
        raise ValueError("Invalid run directory name.")
    candidate = (base / run_dirname).resolve()
    # Belt-and-suspenders: must stay inside the base.
    if base != candidate and base not in candidate.parents:
        raise ValueError("Run directory escapes reports base.")
    return candidate


def _available_reports(run_dir_str: Optional[str]) -> Dict[str, bool]:
    """Return {kind: exists} for each known report file in a safe run dir."""
    out = {k: False for k in _REPORT_FILES}
    if not run_dir_str:
        return out
    try:
        base = REPORTS_BASE.resolve()
        run_dir = Path(run_dir_str).resolve()
    except Exception:  # noqa: BLE001
        return out
    if not _RUN_DIR_RE.match(run_dir.name):
        return out
    if base != run_dir and base not in run_dir.parents:
        return out
    for kind, fname in _REPORT_FILES.items():
        out[kind] = (run_dir / fname).is_file()
    return out


def _summary_row_count(summary: Optional[Dict[str, Any]]) -> Optional[int]:
    if not isinstance(summary, dict):
        return None
    for key in ("total", "total_rows", "rows_seen", "row_count"):
        value = summary.get(key)
        if isinstance(value, int):
            return value
    return None


def _display_label(status: str, row_count: Optional[int], started_at: str, short_job_id: str) -> str:
    row_label = f"{row_count:,} rows" if isinstance(row_count, int) else "rows unknown"
    return f"{status.replace('_', ' ').title()} - {row_label} - {started_at or 'date unknown'} - {short_job_id}"


def _write_meta(record: JobRecord) -> None:
    """Snapshot the record to meta.json so it survives a process restart."""
    if not record.run_dir:
        return
    try:
        run_dir = Path(record.run_dir)
        run_dir.mkdir(parents=True, exist_ok=True)
        meta_path = run_dir / _META_FILENAME
        meta_path.write_text(json.dumps(asdict(record), indent=2, default=str))
        record.meta_path = str(meta_path)
    except Exception as exc:  # noqa: BLE001 — meta is non-critical
        logger.warning("Failed to write meta.json for job %s: %s", record.job_id, exc)



def _parse_dt(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except Exception:
        return None


def _report_json_from_record(record: JobRecord) -> Optional[Dict[str, Any]]:
    if not record.json_path:
        return None
    try:
        path = Path(record.json_path)
        if path.is_file():
            data = json.loads(path.read_text())
            return data if isinstance(data, dict) else None
    except Exception as exc:  # noqa: BLE001
        logger.warning("Failed to read JSON report for durable save %s: %s", record.job_id, exc)
    return None


def _report_csv_from_record(record: JobRecord) -> Optional[str]:
    if not record.csv_path:
        return None
    try:
        path = Path(record.csv_path)
        if path.is_file():
            return path.read_text()
    except Exception as exc:  # noqa: BLE001
        logger.warning("Failed to read CSV report for durable save %s: %s", record.job_id, exc)
    return None


def _row_to_public(row: LeadHygieneReportRun) -> Dict[str, Any]:
    record = JobRecord(
        job_id=row.job_id,
        status=row.status,
        params=row.params or {},
        started_at=row.started_at.isoformat() if row.started_at else "",
        finished_at=row.finished_at.isoformat() if row.finished_at else None,
        phase=row.phase or "",
        summary=row.summary,
        error=row.error,
        sources=row.sources or {},
    )
    public = record.to_public()
    public["reports"] = {
        "csv": bool(row.csv_text) or public["reports"].get("csv", False),
        "json": bool(row.report_payload) or public["reports"].get("json", False),
    }
    public["durable"] = True
    return public


async def persist_record_to_db(record: JobRecord, session: Optional[AsyncSession] = None) -> None:
    """Save completed/failed report metadata and artifacts to durable DB storage."""
    owns_session = session is None
    if session is None:
        try:
            session = _get_session_factory()()
        except Exception as exc:  # noqa: BLE001
            logger.warning("Lead Hygiene durable report save unavailable for %s: %s", record.job_id, exc)
            return
    try:
        report_payload = _report_json_from_record(record)
        csv_text = _report_csv_from_record(record)
        existing = await session.scalar(
            select(LeadHygieneReportRun).where(LeadHygieneReportRun.job_id == record.job_id)
        )
        if existing is None:
            existing = LeadHygieneReportRun(job_id=record.job_id)
            session.add(existing)
        existing.status = record.status
        existing.phase = record.phase
        existing.params = record.params
        existing.summary = record.summary
        existing.sources = record.sources
        existing.started_at = _parse_dt(record.started_at)
        existing.finished_at = _parse_dt(record.finished_at)
        existing.error = record.error
        if report_payload is not None:
            existing.report_payload = report_payload
        if csv_text is not None:
            existing.csv_text = csv_text
        existing.deleted_at = None
        if owns_session:
            await session.commit()
    except Exception as exc:  # noqa: BLE001
        if owns_session:
            await session.rollback()
        logger.warning("Failed durable Lead Hygiene report save for %s: %s", record.job_id, exc)
    finally:
        if owns_session and session is not None:
            await session.close()


def _params_with_defaults(params: JobParams) -> Dict[str, Any]:
    return {
        "limit": params.limit,
        "status_label": params.status_label,
        "extra_query": params.extra_query,
        "recent_window_days": params.recent_window_days,
        "include_ghl": params.include_ghl,
        "notion_csv_path": params.notion_csv_path,
        "fixture_mode": params.fixture_mode,
    }


def _detect_source_availability(params: JobParams) -> Dict[str, Dict[str, Any]]:
    """Cheap pre-flight check — does each source have what it needs to run?"""
    close_key = ""
    ghl_key = ""
    notion_present = bool(params.notion_csv_path) and Path(params.notion_csv_path).is_file()
    try:
        from config import get_settings  # type: ignore
        s = get_settings()
        close_key = getattr(s, "close_api_key", "") or os.environ.get("CLOSE_API_KEY", "")
        ghl_key = getattr(s, "ghl_api_key", "") or os.environ.get("GHL_API_KEY", "")
    except Exception:  # noqa: BLE001
        close_key = os.environ.get("CLOSE_API_KEY", "")
        ghl_key = os.environ.get("GHL_API_KEY", "")
    if params.fixture_mode:
        return {
            "close": {"available": True, "mode": "fixture"},
            "ghl": {"available": True, "mode": "fixture"},
            "notion": {"available": True, "mode": "fixture"},
        }
    return {
        "close": {"available": bool(close_key), "mode": "live"},
        "ghl": {"available": bool(ghl_key) and params.include_ghl, "mode": "live"},
        "notion": {"available": notion_present, "mode": "csv"},
    }


async def _run_job(record: JobRecord, params: JobParams) -> None:
    """Execute the audit and update the registry. Never raises."""
    try:
        record.status = "running"
        record.phase = "collecting"
        _write_meta(record)
        if params.fixture_mode:
            out = await asyncio.to_thread(
                run_audit_from_fixtures,
                out_dir=Path(record.run_dir) if record.run_dir else None,
                recent_window_days=params.recent_window_days,
                limit=params.limit,
            )
        else:
            out = await run_audit_from_live(
                out_dir=Path(record.run_dir),
                limit=params.limit,
                status_label=params.status_label,
                recent_window_days=params.recent_window_days,
                notion_csv=Path(params.notion_csv_path) if params.notion_csv_path else None,
                extra_query=params.extra_query,
                include_ghl=params.include_ghl,
            )
        record.summary = out["summary"]
        record.csv_path = str(out["csv_path"])
        record.json_path = str(out["json_path"])
        record.status = "completed"
        record.phase = "done"
    except Exception as exc:  # noqa: BLE001 — surface to caller via registry
        logger.exception("Lead hygiene job %s failed", record.job_id)
        record.status = "failed"
        record.phase = "error"
        record.error = f"{type(exc).__name__}: {exc}"
    finally:
        record.finished_at = datetime.now(timezone.utc).isoformat()
        _write_meta(record)
        await persist_record_to_db(record)


async def start_job(params: JobParams, max_active: Optional[int] = None) -> JobRecord:
    """Register a new job and schedule it on the running loop."""
    job_id = _new_job_id()
    now = datetime.now(timezone.utc)
    run_dir = _resolve_run_dir(_run_dirname(now, job_id))
    record = JobRecord(
        job_id=job_id,
        status="queued",
        params=_params_with_defaults(params),
        started_at=now.isoformat(),
        run_dir=str(run_dir),
        sources=_detect_source_availability(params),
    )
    async with _LOCK:
        if max_active is not None and active_run_count() >= max_active:
            raise RuntimeError(
                "A lead hygiene audit is already queued or running. Wait for it to finish before starting another."
            )
        _REGISTRY[job_id] = record
    _write_meta(record)
    task = asyncio.create_task(_run_job(record, params))
    _TASKS[job_id] = task
    return record


def _load_meta_from_disk(run_dir: Path) -> Optional[JobRecord]:
    meta_path = run_dir / _META_FILENAME
    if not meta_path.is_file():
        return None
    try:
        data = json.loads(meta_path.read_text())
        return JobRecord(**{k: data.get(k) for k in JobRecord.__dataclass_fields__})
    except Exception as exc:  # noqa: BLE001
        logger.warning("Failed to read meta.json at %s: %s", meta_path, exc)
        return None


async def list_runs_async(session: AsyncSession, limit: int = 50) -> List[Dict[str, Any]]:
    """Return recent runs from durable DB, active memory, and legacy local files."""
    by_id: Dict[str, Dict[str, Any]] = {}
    result = await session.execute(
        select(LeadHygieneReportRun)
        .where(LeadHygieneReportRun.deleted_at.is_(None))
        .order_by(LeadHygieneReportRun.started_at.desc().nullslast(), LeadHygieneReportRun.id.desc())
        .limit(limit)
    )
    for row in result.scalars().all():
        by_id[row.job_id] = _row_to_public(row)

    for item in list_runs(limit=limit):
        by_id[item["job_id"]] = {**item, **by_id.get(item["job_id"], {})}
        if item["job_id"] in _REGISTRY:
            by_id[item["job_id"]] = item

    rows = sorted(by_id.values(), key=lambda r: r.get("started_at") or "", reverse=True)
    return rows[:limit]


async def get_run_public_async(session: AsyncSession, job_id: str) -> Optional[Dict[str, Any]]:
    if not _JOB_ID_RE.match(job_id or ""):
        return None
    rec = get_run(job_id)
    if rec is not None:
        return rec.to_public()
    row = await session.scalar(
        select(LeadHygieneReportRun).where(
            LeadHygieneReportRun.job_id == job_id,
            LeadHygieneReportRun.deleted_at.is_(None),
        )
    )
    return _row_to_public(row) if row else None


async def load_report_payload_async(session: AsyncSession, job_id: str) -> Dict[str, Any]:
    try:
        path = resolve_report_path(job_id, "json")
        data = json.loads(path.read_text())
        if isinstance(data, dict):
            return data
    except FileNotFoundError:
        pass
    if not _JOB_ID_RE.match(job_id or ""):
        raise ValueError("Invalid job id.")
    row = await session.scalar(
        select(LeadHygieneReportRun).where(
            LeadHygieneReportRun.job_id == job_id,
            LeadHygieneReportRun.deleted_at.is_(None),
        )
    )
    if row is None or not row.report_payload:
        raise FileNotFoundError("Report payload not found.")
    return row.report_payload


async def load_csv_text_async(session: AsyncSession, job_id: str) -> str:
    try:
        path = resolve_report_path(job_id, "csv")
        return path.read_text()
    except FileNotFoundError:
        pass
    if not _JOB_ID_RE.match(job_id or ""):
        raise ValueError("Invalid job id.")
    row = await session.scalar(
        select(LeadHygieneReportRun).where(
            LeadHygieneReportRun.job_id == job_id,
            LeadHygieneReportRun.deleted_at.is_(None),
        )
    )
    if row is None or row.csv_text is None:
        raise FileNotFoundError("CSV report not found.")
    return row.csv_text


async def load_report_preview_async(
    session: AsyncSession,
    job_id: str,
    limit: int = 25,
    category: str | None = None,
) -> Dict[str, Any]:
    data = await load_report_payload_async(session, job_id)
    rows = data.get("rows") or []
    bucket_filter = _bucket_filter(category)
    if bucket_filter is not None:
        rows = [r for r in rows if r.get("recommended_bucket") in bucket_filter]
    total = len(rows)
    preview = [_preview_row(r) for r in rows[:limit]]
    return {
        "total_rows": total,
        "preview_limit": limit,
        "category": category or "all",
        "summary": data.get("summary"),
        "rows": preview,
    }


async def delete_run_async(session: AsyncSession, job_id: str) -> Dict[str, Any]:
    """Soft-delete durable history and remove any local cache files."""
    if not _JOB_ID_RE.match(job_id or ""):
        raise ValueError("Invalid job id.")
    rec = get_run(job_id)
    row = await session.scalar(select(LeadHygieneReportRun).where(LeadHygieneReportRun.job_id == job_id))
    status_value = rec.status if rec is not None else (row.status if row is not None else None)
    if status_value is None:
        raise FileNotFoundError("Run not found.")
    if status_value in {"queued", "running"}:
        raise RuntimeError("Cannot delete a queued or running Lead Hygiene job.")
    removed_files = 0
    if rec is not None and rec.run_dir:
        try:
            base = REPORTS_BASE.resolve()
            run_dir = Path(rec.run_dir).resolve()
            if _RUN_DIR_RE.match(run_dir.name) and (base == run_dir or base in run_dir.parents) and run_dir.exists():
                removed_files = sum(1 for child in run_dir.rglob("*") if child.is_file())
                shutil.rmtree(run_dir)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Failed local cache delete for %s: %s", job_id, exc)
    if row is not None:
        row.deleted_at = datetime.now(timezone.utc)
    _REGISTRY.pop(job_id, None)
    task = _TASKS.pop(job_id, None)
    if task and not task.done():
        _TASKS[job_id] = task
    return {"deleted": True, "job_id": job_id, "removed_files": removed_files, "soft_deleted": row is not None}


async def purge_all_runs_async(session: AsyncSession) -> Dict[str, Any]:
    if active_run_count() > 0:
        raise RuntimeError("Cannot purge report history while a Lead Hygiene job is queued or running.")
    result = await session.execute(delete(LeadHygieneReportRun))
    removed_files = 0
    REPORTS_BASE.mkdir(parents=True, exist_ok=True)
    for child in REPORTS_BASE.iterdir():
        if child.is_dir() and _RUN_DIR_RE.match(child.name):
            removed_files += sum(1 for item in child.rglob("*") if item.is_file())
            shutil.rmtree(child)
    _REGISTRY.clear()
    _TASKS.clear()
    return {"purged": True, "deleted_rows": result.rowcount or 0, "removed_files": removed_files}


def list_runs(limit: int = 50) -> List[Dict[str, Any]]:
    """Return recent runs, merging in-memory registry with on-disk meta.

    On-disk records cover runs from prior process lifetimes. In-memory
    records win when the same job_id exists in both (in-memory is fresher).
    """
    REPORTS_BASE.mkdir(parents=True, exist_ok=True)
    by_id: Dict[str, JobRecord] = dict(_REGISTRY)
    for child in REPORTS_BASE.iterdir():
        if not child.is_dir() or not _RUN_DIR_RE.match(child.name):
            continue
        rec = _load_meta_from_disk(child)
        if not rec or rec.job_id in by_id:
            continue
        by_id[rec.job_id] = rec
    records = sorted(
        by_id.values(),
        key=lambda r: r.started_at or "",
        reverse=True,
    )
    return [r.to_public() for r in records[:limit]]


def active_run_count() -> int:
    """Return queued/running jobs so the router can prevent pile-ups."""
    return sum(1 for r in _REGISTRY.values() if r.status in {"queued", "running"})


def get_run(job_id: str) -> Optional[JobRecord]:
    """Return a single run by id (in-memory first, then on-disk)."""
    if not _JOB_ID_RE.match(job_id or ""):
        return None
    if job_id in _REGISTRY:
        return _REGISTRY[job_id]
    REPORTS_BASE.mkdir(parents=True, exist_ok=True)
    for child in REPORTS_BASE.iterdir():
        if not child.is_dir() or not _RUN_DIR_RE.match(child.name):
            continue
        if not child.name.endswith(job_id[:12]):
            continue
        rec = _load_meta_from_disk(child)
        if rec and rec.job_id == job_id:
            return rec
    return None


def resolve_report_path(job_id: str, kind: str) -> Path:
    """Return a safe filesystem path to a report file. Raises ValueError on bad input."""
    if not _JOB_ID_RE.match(job_id or ""):
        raise ValueError("Invalid job id.")
    if kind not in _REPORT_FILES:
        raise ValueError("Unknown report kind.")
    rec = get_run(job_id)
    if rec is None or not rec.run_dir:
        raise FileNotFoundError("Job not found.")
    base = REPORTS_BASE
    run_dir = Path(rec.run_dir).resolve()
    if base != run_dir and base not in run_dir.parents:
        raise ValueError("Run directory escapes reports base.")
    candidate = (run_dir / _REPORT_FILES[kind]).resolve()
    if run_dir not in candidate.parents:
        raise ValueError("Report path escapes run directory.")
    if not candidate.is_file():
        raise FileNotFoundError("Report file does not exist yet.")
    return candidate


def delete_run(job_id: str) -> Dict[str, Any]:
    """Delete one local report run directory and its in-memory registry entry.

    This only removes Lead Hygiene report files under REPORTS_BASE. It refuses
    active jobs and never touches Registry-imported database records or any
    external system.
    """
    if not _JOB_ID_RE.match(job_id or ""):
        raise ValueError("Invalid job id.")
    rec = get_run(job_id)
    if rec is None or not rec.run_dir:
        raise FileNotFoundError("Run not found.")
    if rec.status in {"queued", "running"}:
        raise RuntimeError("Cannot delete a queued or running Lead Hygiene job.")
    if rec.status not in {"completed", "failed", "canceled", "cancelled"}:
        raise RuntimeError("Only completed, failed, or canceled Lead Hygiene jobs can be deleted.")

    base = REPORTS_BASE.resolve()
    run_dir = Path(rec.run_dir).resolve()
    if not _RUN_DIR_RE.match(run_dir.name):
        raise ValueError("Invalid run directory name.")
    if base != run_dir and base not in run_dir.parents:
        raise ValueError("Run directory escapes reports base.")
    if not run_dir.exists() or not run_dir.is_dir():
        raise FileNotFoundError("Run not found.")

    removed_count = sum(1 for child in run_dir.rglob("*") if child.is_file())
    shutil.rmtree(run_dir)
    _REGISTRY.pop(job_id, None)
    task = _TASKS.pop(job_id, None)
    if task and not task.done():
        _TASKS[job_id] = task
    return {
        "deleted": True,
        "job_id": job_id,
        "removed_files": removed_count,
    }


def load_report_preview(
    job_id: str,
    limit: int = 25,
    category: str | None = None,
) -> Dict[str, Any]:
    """Read the JSON report and return summary + first `limit` rows.

    Rows are returned as a thin projection — only the fields the UI displays —
    so a 7k-row report never ships in full to the browser. Use the download
    endpoint to grab the complete CSV/JSON.
    """
    json_path = resolve_report_path(job_id, "json")
    data = json.loads(json_path.read_text())
    rows = data.get("rows") or []
    bucket_filter = _bucket_filter(category)
    if bucket_filter is not None:
        rows = [r for r in rows if r.get("recommended_bucket") in bucket_filter]
    total = len(rows)
    preview = [_preview_row(r) for r in rows[:limit]]
    return {
        "total_rows": total,
        "preview_limit": limit,
        "category": category or "all",
        "summary": data.get("summary"),
        "rows": preview,
    }


def _bucket_filter(category: str | None) -> set[str] | None:
    """Map UI report-detail filters to concrete audit buckets."""
    if not category or category == "all":
        return None
    grouped_filters = {
        "needs-review-group": {"needs-review", "duplicate", "missing-phone"},
        "hard-stop": {"do-not-contact", "not-interested", "invalid"},
        "recent-touch-group": {"recently-contacted", "previous-outreach-detected"},
    }
    concrete_buckets = {
        "reengage-ready",
        "already-automated",
        "previous-outreach-detected",
        "needs-review",
        "duplicate",
        "missing-phone",
        "client",
        "invalid",
        "not-interested",
        "do-not-contact",
        "recently-contacted",
    }
    if category in concrete_buckets:
        return {category}
    if category in grouped_filters:
        return grouped_filters[category]
    raise ValueError("Unknown preview category.")


def _preview_row(row: Dict[str, Any]) -> Dict[str, Any]:
    """Project a full report row down to the columns the UI table renders."""
    return {
        "lead_name": row.get("lead_name") or "",
        "phone": row.get("phone") or "",
        "email": row.get("email") or "",
        "close_lead_id": row.get("close_lead_id") or "",
        "ghl_contact_id": row.get("ghl_contact_id") or "",
        "notion_page_id": row.get("notion_page_id") or "",
        "close_status": row.get("close_status") or "",
        "recommended_bucket": row.get("recommended_bucket") or "",
        "risk_flags": row.get("risk_flags") or [],
        "reason": row.get("reason") or "",
        "confidence": row.get("confidence"),
        "last_outbound_touch": row.get("last_outbound_touch"),
    }


# ─── Test helpers ────────────────────────────────────────────────────
# Not part of the API surface but needed by the test suite to reset state
# between cases. Underscore prefix marks them as internal.


def _reset_registry_for_tests() -> None:
    _REGISTRY.clear()
    _TASKS.clear()
