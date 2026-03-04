"""Admin and health-check routes."""

import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from db.database import get_session

logger = logging.getLogger("falconconnect.admin")

router = APIRouter()


@router.get("/health")
async def health_check():
    """Basic liveness probe — returns 200 if the app is running."""
    return {
        "status": "healthy",
        "service": "FalconConnect v3",
        "version": "3.0.0",
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


@router.get("/health/db")
async def db_health(session: AsyncSession = Depends(get_session)):
    """Database connectivity check — runs a simple query."""
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


@router.get("/version")
async def version():
    """Return the current application version."""
    return {
        "service": "FalconConnect",
        "version": "3.0.0",
        "codename": "middleware-rebuild",
    }
