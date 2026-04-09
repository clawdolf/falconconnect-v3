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
