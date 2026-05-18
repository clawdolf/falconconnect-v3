"""Admin-only dry-run lead hygiene audit endpoint.

This route never writes to Close, GHL, or Notion. It returns the audit summary
inline and writes a CSV + JSON report under a server-controlled base directory.
Admin (Clerk JWT) required.

Report files always land under LEAD_HYGIENE_REPORTS_BASE; the request can pick
the sub-directory name but cannot traverse out of it. This prevents an
authenticated caller from writing a report to an arbitrary server path.
"""

from __future__ import annotations

import logging
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field, field_validator

from middleware.auth import require_auth
from services.lead_hygiene_collect import (
    run_audit_from_fixtures,
    run_audit_from_live,
)

logger = logging.getLogger("falconconnect.lead_hygiene_route")

router = APIRouter()

# Reports always land here. Override only by setting LEAD_HYGIENE_REPORTS_BASE
# in the Render env vars panel — never via the request.
DEFAULT_REPORTS_BASE = Path(
    os.environ.get("LEAD_HYGIENE_REPORTS_BASE", "/tmp/falconconnect/lead_hygiene_reports")
).resolve()

# Sub-directory name must be a single safe slug. No slashes, no ".." — these
# would let a caller traverse outside the base dir.
_SUBDIR_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_\-]{0,63}$")


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


class AuditResponse(BaseModel):
    csv_path: str
    json_path: str
    summary: dict
    dry_run: bool = True


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


@router.post("/audit/dry-run", response_model=AuditResponse)
async def dry_run_audit(payload: AuditRequest, _user=Depends(require_auth)):
    """Run the lead hygiene audit in dry-run mode. No upstream writes."""
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
                notion_csv=Path(payload.notion_csv_path) if payload.notion_csv_path else None,
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
        csv_path=str(out["csv_path"]),
        json_path=str(out["json_path"]),
        summary=out["summary"],
        dry_run=True,
    )
