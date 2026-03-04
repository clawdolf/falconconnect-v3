"""FalconConnect v3 — middleware layer for dual GHL + Notion sync."""

import asyncio
import logging
import os
from datetime import datetime, timezone

from contextlib import asynccontextmanager
from fastapi import FastAPI, Depends
from fastapi.staticfiles import StaticFiles

from db.database import init_db, get_session
from sqlalchemy.ext.asyncio import AsyncSession
from routers import leads, webhooks, calendar, analytics, admin, sync, licenses
from services.notion_ghl_sync import sync_loop

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger("falconconnect")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup / shutdown lifecycle."""
    logger.info("FalconConnect v3 starting up …")

    # init_db() runs create_all (idempotent — creates missing tables, skips existing)
    # Alembic migrations ran at build time; this is a fast safety net only.
    await init_db()

    # Start background Notion → GHL sync loop
    sync_task = asyncio.create_task(sync_loop())
    logger.info("Notion→GHL background sync task started")

    yield

    # Shutdown
    sync_task.cancel()
    try:
        await sync_task
    except asyncio.CancelledError:
        pass
    logger.info("FalconConnect v3 shutting down …")


app = FastAPI(
    title="FalconConnect v3",
    description="Middleware layer: dual GHL + Notion sync, iCal feed, analytics hub.",
    version="3.1.0",
    lifespan=lifespan,
)

# Root-level health check (Render probes /health)
@app.get("/health")
async def root_health():
    """Root-level liveness probe — Render expects /health."""
    from config import get_settings
    settings = get_settings()
    return {
        "status": "healthy",
        "service": "FalconConnect v3",
        "version": "3.1.0",
        "clerk_configured": bool(settings.clerk_secret_key),
        "sync_enabled": settings.notion_ghl_sync_enabled,
        "sync_dry_run": settings.notion_ghl_sync_dry_run,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


@app.get("/debug/env")
async def debug_env():
    """Temporary debug endpoint — checks raw env vars. Remove after verifying Clerk."""
    import os
    from pathlib import Path

    from config import get_settings
    settings = get_settings()
    return {
        "CLERK_SECRET_KEY_set": bool(os.environ.get("CLERK_SECRET_KEY", "")),
        "CLERK_PUBLISHABLE_KEY_set": bool(os.environ.get("CLERK_PUBLISHABLE_KEY", "")),
        "CLERK_SECRET_KEY_len": len(os.environ.get("CLERK_SECRET_KEY", "")),
        "GHL_API_KEY_set": bool(os.environ.get("GHL_API_KEY", "")),
        "settings_clerk_key_len": len(settings.clerk_secret_key),
        "settings_clerk_pub_len": len(settings.clerk_publishable_key),
        "etc_secrets_env_exists": Path("/etc/secrets/.env").is_file(),
        "local_env_exists": Path(".env").is_file(),
        "cwd": os.getcwd(),
    }


@app.get("/debug/db")
async def debug_db():
    """Temporary debug endpoint — checks DB state (license count, alembic version)."""
    from sqlalchemy import text
    from db.database import get_engine
    async with get_engine().connect() as conn:
        alembic_result = await conn.execute(text("SELECT version_num FROM alembic_version"))
        versions = [r[0] for r in alembic_result.fetchall()]
        count_result = await conn.execute(text("SELECT COUNT(*) FROM licenses"))
        count = count_result.scalar()
        sample_result = await conn.execute(
            text("SELECT state_abbreviation, license_number, status FROM licenses LIMIT 10")
        )
        rows = [{"state": r[0], "license_number": r[1], "status": r[2]} for r in sample_result.fetchall()]
    return {"alembic_versions": versions, "license_count": count, "sample_licenses": rows}


# API routers
app.include_router(leads.router, prefix="/api/public", tags=["Leads"])
app.include_router(webhooks.router, prefix="/api/webhooks", tags=["Webhooks"])
app.include_router(calendar.router, prefix="/api/calendar", tags=["Calendar"])
app.include_router(analytics.router, prefix="/api/analytics", tags=["Analytics"])
app.include_router(admin.router, prefix="/api/admin", tags=["Admin"])
app.include_router(sync.router, prefix="/api/sync", tags=["Sync"])
app.include_router(licenses.router, prefix="/api/licenses", tags=["Licenses"])

# Serve React frontend (built files) — must be LAST so API routes take priority
frontend_dist = os.path.join(os.path.dirname(__file__), "frontend", "dist")
if os.path.isdir(frontend_dist):
    app.mount("/", StaticFiles(directory=frontend_dist, html=True), name="frontend")
    logger.info("Serving frontend from %s", frontend_dist)
else:
    logger.info("No frontend/dist directory found — frontend not served")
