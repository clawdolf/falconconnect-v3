"""Admin-only dry-run lead hygiene endpoints.

This router never writes to Close, GHL, or Notion. It exposes:
  * POST /audit/dry-run           — synchronous fixture-friendly run (kept for tests + CLI parity)
  * GET  /sources                 — credential availability for Close / GHL / Notion
  * POST /upload-notion-csv       — multipart upload of a Notion CSV export (sandboxed)
  * POST /runs                    — start a background audit, returns job_id
  * GET  /runs                    — list recent runs (in-memory + on-disk meta)
  * GET  /runs/{job_id}           — single run status
  * GET  /runs/{job_id}/preview   — first N rows of the JSON report
  * GET  /runs/{job_id}/report/{kind} — download csv|json

All endpoints require Clerk JWT auth. All file paths are server-sandboxed:
report files always land under LEAD_HYGIENE_REPORTS_BASE and the caller can
never traverse out of it.
"""

from __future__ import annotations

import logging
import os
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field, field_validator

from middleware.auth import require_auth
from services.lead_hygiene_collect import (
    run_audit_from_fixtures,
    run_audit_from_live,
)
from services.lead_hygiene_jobs import (
    JobParams,
    REPORTS_BASE,
    get_run,
    list_runs,
    load_report_preview,
    resolve_report_path,
    start_job,
)

logger = logging.getLogger("falconconnect.lead_hygiene_route")

router = APIRouter()

# Reports always land here. Override only by setting LEAD_HYGIENE_REPORTS_BASE
# in the Render env vars panel — never via the request.
DEFAULT_REPORTS_BASE = Path(
    os.environ.get("LEAD_HYGIENE_REPORTS_BASE", "/tmp/falconconnect/lead_hygiene_reports")
).resolve()

# Uploaded Notion CSVs are stored in a separate sandbox under the same base.
NOTION_UPLOAD_DIR = DEFAULT_REPORTS_BASE / "_uploads"

# Sub-directory name must be a single safe slug. No slashes, no ".." — these
# would let a caller traverse outside the base dir.
_SUBDIR_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_\-]{0,63}$")
# Upload tokens — 32-char hex.
_UPLOAD_TOKEN_RE = re.compile(r"^[a-f0-9]{32}$")
# Status labels we accept on the start-job endpoint. Empty string == no filter.
_STATUS_LABEL_RE = re.compile(r"^[A-Za-z0-9 _\-]{1,64}$")
_EXTRA_QUERY_RE = re.compile(r"^[A-Za-z0-9_ .:\"'()\-/<>+=]{1,200}$")


async def require_admin(user=Depends(require_auth)):
    """Require Seb/admin Clerk user for PII-heavy lead hygiene endpoints."""
    admin_id = os.environ.get("CLERK_ADMIN_USER_ID", "")
    if not admin_id:
        try:
            from config import get_settings  # type: ignore
            admin_id = getattr(get_settings(), "clerk_admin_user_id", "") or ""
        except Exception:  # noqa: BLE001
            admin_id = ""
    if not admin_id:
        admin_id = "user_3ASrwDOrSTaDxCus6f1B5lnDsgz"
    user_id = user.get("sub") or user.get("user_id")
    if not admin_id or user_id != admin_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Lead hygiene is restricted to the FalconConnect admin user.",
        )
    return user


# ─── Schemas ───────────────────────────────────────────────────────────


class AuditRequest(BaseModel):
    limit: int = Field(100, ge=1, le=1000)
    # Status name (e.g. "Voicemail"). Sent to Close as the search-syntax
    # query `status:"<value>"` — Close ignores `status_label=` on /lead/.
    status_label: Optional[str] = None
    # Optional Close search-syntax clause AND-combined with status_label.
    query: Optional[str] = None
    recent_window_days: int = Field(30, ge=1, le=365)
    notion_csv_path: Optional[str] = None
    fixture_mode: bool = False
    # Optional sub-directory name under the server-controlled reports base.
    # Validated: alnum + dash + underscore only, no traversal. If omitted,
    # a timestamped sub-directory is used.
    output_subdir: Optional[str] = None

    @field_validator("output_subdir")
    @classmethod
    def _validate_subdir(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return v
        if not _SUBDIR_RE.match(v):
            raise ValueError(
                "output_subdir must be 1-64 chars, alnum/dash/underscore only, "
                "and may not contain path separators or traversal segments."
            )
        return v

    @field_validator("notion_csv_path")
    @classmethod
    def _reject_raw_notion_path(cls, v: Optional[str]) -> Optional[str]:
        if v:
            raise ValueError("Raw server paths are not accepted. Use /upload-notion-csv and POST /runs.")
        return None


class AuditResponse(BaseModel):
    csv_path: str
    json_path: str
    summary: dict
    dry_run: bool = True


class StartJobRequest(BaseModel):
    limit: int = Field(200, ge=1, le=10000)
    status_label: Optional[str] = "Voicemail"
    extra_query: Optional[str] = None
    recent_window_days: int = Field(30, ge=1, le=365)
    include_ghl: bool = True
    notion_upload_token: Optional[str] = None
    fixture_mode: bool = False

    @field_validator("status_label")
    @classmethod
    def _validate_status_label(cls, v: Optional[str]) -> Optional[str]:
        if v is None or v == "":
            return None
        if not _STATUS_LABEL_RE.match(v):
            raise ValueError(
                "status_label must be 1-64 chars, alnum / space / dash / underscore only."
            )
        return v

    @field_validator("notion_upload_token")
    @classmethod
    def _validate_upload_token(cls, v: Optional[str]) -> Optional[str]:
        if v is None or v == "":
            return None
        if not _UPLOAD_TOKEN_RE.match(v):
            raise ValueError("notion_upload_token must be a 32-char hex token.")
        return v

    @field_validator("extra_query")
    @classmethod
    def _validate_extra_query(cls, v: Optional[str]) -> Optional[str]:
        if v is None or v == "":
            return None
        if not _EXTRA_QUERY_RE.match(v):
            raise ValueError("extra_query contains unsupported characters or is too long.")
        return v


# ─── Helpers ───────────────────────────────────────────────────────────


def _resolve_out_dir(subdir: Optional[str]) -> Path:
    base = DEFAULT_REPORTS_BASE
    base.mkdir(parents=True, exist_ok=True)
    name = subdir or datetime.now(timezone.utc).strftime("run-%Y%m%dT%H%M%SZ")
    candidate = (base / name).resolve()
    # Defense-in-depth: even if validation slipped, refuse anything that
    # escapes the base directory.
    if base != candidate and base not in candidate.parents:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="output_subdir resolves outside the reports base directory.",
        )
    return candidate


def _resolve_upload_path(token: str) -> Path:
    """Validate a Notion CSV upload token → on-disk CSV path."""
    if not _UPLOAD_TOKEN_RE.match(token or ""):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid notion_upload_token.",
        )
    base = NOTION_UPLOAD_DIR.resolve()
    candidate = (base / f"{token}.csv").resolve()
    if base not in candidate.parents:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Upload token resolves outside upload sandbox.",
        )
    if not candidate.is_file():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Uploaded CSV not found — it may have been cleaned up.",
        )
    return candidate


# ─── Legacy synchronous endpoint (kept for CLI / test parity) ─────────


@router.post("/audit/dry-run", response_model=AuditResponse)
async def dry_run_audit(payload: AuditRequest, _user=Depends(require_admin)):
    """Run the lead hygiene audit synchronously. No upstream writes.

    Prefer POST /runs for live data — this endpoint blocks for the full
    audit duration and will time out the HTTP request on 7k+ leads. Kept
    for fixture mode and CLI parity.
    """
    out_dir = _resolve_out_dir(payload.output_subdir)

    try:
        if payload.fixture_mode:
            out = run_audit_from_fixtures(
                out_dir=out_dir,
                recent_window_days=payload.recent_window_days,
                limit=payload.limit,
            )
        else:
            out = await run_audit_from_live(
                out_dir=out_dir,
                limit=payload.limit,
                status_label=payload.status_label,
                recent_window_days=payload.recent_window_days,
                notion_csv=None,
                extra_query=payload.query,
            )
    except RuntimeError as exc:
        # Surface credential / config errors as a 400 so the operator sees it.
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))

    logger.info(
        "lead_hygiene_audit complete: total=%d buckets=%s",
        out["summary"]["total"], out["summary"]["by_bucket"],
    )
    return AuditResponse(
        csv_path=Path(out["csv_path"]).name,
        json_path=Path(out["json_path"]).name,
        summary=out["summary"],
        dry_run=True,
    )


# ─── Source coverage ───────────────────────────────────────────────────


@router.get("/sources")
async def sources(_user=Depends(require_admin)):
    """Report which upstream sources have credentials available.

    UI uses this to grey out toggles for sources that won't be reachable.
    """
    close_key = ""
    ghl_key = ""
    try:
        from config import get_settings  # type: ignore
        s = get_settings()
        close_key = getattr(s, "close_api_key", "") or os.environ.get("CLOSE_API_KEY", "")
        ghl_key = getattr(s, "ghl_api_key", "") or os.environ.get("GHL_API_KEY", "")
    except Exception:  # noqa: BLE001 — config is optional
        close_key = os.environ.get("CLOSE_API_KEY", "")
        ghl_key = os.environ.get("GHL_API_KEY", "")
    return {
        "close": {"available": bool(close_key), "mode": "live"},
        "ghl": {"available": bool(ghl_key), "mode": "live"},
        "notion": {"available": True, "mode": "csv_upload"},
        "dry_run_only": True,
    }


# ─── Notion CSV upload ─────────────────────────────────────────────────


@router.post("/upload-notion-csv")
async def upload_notion_csv(
    file: UploadFile = File(...),
    _user=Depends(require_admin),
):
    """Accept a Notion CSV export, sandbox it, return an upload token.

    Token is a 32-char hex string the caller passes back as
    `notion_upload_token` on POST /runs. The file lives under
    NOTION_UPLOAD_DIR and never leaves it. Max 25 MB.
    """
    NOTION_UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    if not (file.filename or "").lower().endswith(".csv"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Only .csv files are accepted.",
        )
    token = uuid.uuid4().hex
    dest = NOTION_UPLOAD_DIR / f"{token}.csv"
    size_limit = 25 * 1024 * 1024
    written = 0
    with dest.open("wb") as fh:
        while True:
            chunk = await file.read(1024 * 1024)
            if not chunk:
                break
            written += len(chunk)
            if written > size_limit:
                fh.close()
                dest.unlink(missing_ok=True)
                raise HTTPException(
                    status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                    detail="CSV exceeds 25 MB limit.",
                )
            fh.write(chunk)
    return {"token": token, "size_bytes": written}


# ─── Background job lifecycle ──────────────────────────────────────────


@router.post("/runs")
async def start_run(payload: StartJobRequest, _user=Depends(require_admin)):
    """Start a dry-run audit as a background job and return the job_id."""
    notion_path: Optional[str] = None
    if payload.notion_upload_token:
        notion_path = str(_resolve_upload_path(payload.notion_upload_token))

    params = JobParams(
        limit=payload.limit,
        status_label=payload.status_label,
        extra_query=payload.extra_query,
        recent_window_days=payload.recent_window_days,
        include_ghl=payload.include_ghl,
        notion_csv_path=notion_path,
        fixture_mode=payload.fixture_mode,
    )
    try:
        record = await start_job(params, max_active=1)
    except RuntimeError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))
    return record.to_public()


@router.get("/runs")
async def list_run_records(limit: int = 25, _user=Depends(require_admin)):
    """List the most recent runs (in-memory + on-disk meta)."""
    if limit < 1 or limit > 200:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="limit must be between 1 and 200.",
        )
    return {"runs": list_runs(limit=limit)}


@router.get("/runs/{job_id}")
async def get_run_record(job_id: str, _user=Depends(require_admin)):
    """Return status + summary for a single job."""
    rec = get_run(job_id)
    if rec is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Run not found.",
        )
    return rec.to_public()


@router.get("/runs/{job_id}/preview")
async def get_run_preview(
    job_id: str,
    limit: int = 25,
    category: Optional[str] = None,
    _user=Depends(require_admin),
):
    """Return the first `limit` rows of the JSON report for the UI table."""
    if limit < 1 or limit > 200:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="limit must be between 1 and 200.",
        )
    try:
        return load_report_preview(job_id, limit=limit, category=category)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))


@router.get("/runs/{job_id}/report/{kind}")
async def download_run_report(
    job_id: str,
    kind: str,
    _user=Depends(require_admin),
):
    """Stream a report file (csv | json) for a completed run."""
    try:
        path = resolve_report_path(job_id, kind)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    media = {
        "csv": "text/csv",
        "json": "application/json",
    }[kind]
    filename = f"lead_hygiene_{kind}_{job_id[:12]}{path.suffix}"
    return FileResponse(path=str(path), media_type=media, filename=filename)
