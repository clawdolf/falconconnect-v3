"""Admin and health-check routes."""

import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from db.database import get_session
from middleware.auth import require_auth

logger = logging.getLogger("falconconnect.admin")

router = APIRouter()


@router.get("/health")
async def health_check():
    """Basic liveness probe — returns 200 if the app is running. Public."""
    return {
        "status": "healthy",
        "service": "FalconConnect v3",
        "version": "3.1.0",
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


@router.get("/health/db")
async def db_health(session: AsyncSession = Depends(get_session)):
    """Database connectivity check — runs a simple query. Public."""
    try:
        result = await session.execute(text("SELECT 1"))
        result.scalar()
        return {
            "status": "healthy",
            "database": "connected",
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
    except Exception as exc:
        logger.error("Database health check failed: %s", exc)
        return {
            "status": "unhealthy",
            "database": "disconnected",
            "error": str(exc),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }


@router.post("/rename-gcal-events", dependencies=[Depends(require_auth)])
async def rename_gcal_events():
    """One-shot: rename all GCal events starting with 'Call with ' to just the name."""
    from services.google_calendar import _get_calendar_service, update_appointment_event
    from config import get_settings

    settings = get_settings()
    cal_id = settings.google_calendar_id
    service = _get_calendar_service()

    def _list():
        return (
            service.events()
            .list(
                calendarId=cal_id,
                timeMin="2026-01-01T00:00:00Z",
                maxResults=200,
                singleEvents=True,
                orderBy="startTime",
            )
            .execute()
        )

    import asyncio
    result = await asyncio.to_thread(_list)
    events = result.get("items", [])

    renamed = []
    skipped = 0

    for event in events:
        summary = event.get("summary", "")
        event_id = event.get("id", "")

        if summary.startswith("Call with "):
            new_summary = summary.replace("Call with ", "", 1)
            try:
                await update_appointment_event(event_id, summary=new_summary)
                renamed.append({"old": summary, "new": new_summary, "id": event_id})
            except Exception as exc:
                logger.error("Failed to rename event %s: %s", event_id, exc)
                renamed.append({"old": summary, "error": str(exc), "id": event_id})
        else:
            skipped += 1

    return {"renamed": len(renamed), "skipped": skipped, "details": renamed}


@router.get("/version")
async def version():
    """Return the current application version. Public."""
    return {
        "service": "FalconConnect",
        "version": "3.1.0",
        "codename": "clerk-auth",
    }


@router.get("/me")
async def me(user=Depends(require_auth)):
    """Return the authenticated user's Clerk profile. Requires auth."""
    return {"user": user}
