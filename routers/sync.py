"""Notion → GHL sync endpoints — dry-run trigger, live sync, and status."""

import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends

from middleware.auth import require_auth
from services.notion_ghl_sync import run_notion_ghl_sync
from config import get_settings

logger = logging.getLogger("falconconnect.sync")

router = APIRouter()


@router.post("/notion-to-ghl/dry-run")
async def dry_run_notion_ghl_sync(user=Depends(require_auth)):
    """Manually trigger a dry-run sync — shows what WOULD be pushed to GHL.

    Forces DRY_RUN=true regardless of env setting.
    Uses a 30-day lookahead window (not just the last 6 minutes).
    Requires Clerk authentication.
    """
    settings = get_settings()

    results = await run_notion_ghl_sync(
        force_dry_run=True,
        lookahead_days=30,
    )

    return {
        "mode": "dry_run",
        "sync_after_date": settings.notion_ghl_sync_after_date,
        "sync_enabled": settings.notion_ghl_sync_enabled,
        "appointments_found": len(results),
        "results": results,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


@router.post("/notion-to-ghl/live")
async def live_notion_ghl_sync(user=Depends(require_auth)):
    """Bug 10 fix: Manually trigger a LIVE sync — actually writes to GHL.

    Uses a 30-day lookahead window. Respects the SYNC_AFTER_DATE filter
    but ignores NOTION_GHL_SYNC_DRY_RUN (this is explicitly live).
    Requires Clerk authentication.
    """
    settings = get_settings()

    results = await run_notion_ghl_sync(
        force_dry_run=False,
        lookahead_days=30,
    )

    return {
        "mode": "live",
        "dry_run": False,
        "sync_after_date": settings.notion_ghl_sync_after_date,
        "sync_enabled": settings.notion_ghl_sync_enabled,
        "appointments_found": len(results),
        "results": results,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


@router.get("/status")
async def sync_status(user=Depends(require_auth)):
    """Return current sync configuration and status."""
    settings = get_settings()

    return {
        "sync_enabled": settings.notion_ghl_sync_enabled,
        "dry_run": settings.notion_ghl_sync_dry_run,
        "sync_after_date": settings.notion_ghl_sync_after_date,
        "poll_interval_seconds": settings.notion_ghl_sync_interval,
        "clerk_configured": bool(settings.clerk_secret_key),
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
