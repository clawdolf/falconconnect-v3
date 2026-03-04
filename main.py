"""FalconConnect v3 — middleware layer for dual GHL + Notion sync."""

import asyncio
import logging
import os
from datetime import datetime, timezone

from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from db.database import init_db
from routers import leads, webhooks, calendar, analytics, admin, sync, licenses
from services.notion_ghl_sync import sync_loop

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger("falconconnect")


@asynccontextmanager
async def _seed_licenses_if_empty() -> None:
    """Seed Seb's 8 licenses from v2 prod DB if table is empty. Idempotent."""
    from sqlalchemy import text

    SEB_USER_ID = "72dc5b7c-ba2c-4a1d-83b9-733ff600c0d5"
    LICENSES = [
        ("Arizona",        "AZ", None,      "https://sbs.naic.org/solar-external-lookup/lookup/licensee/summary/21408357?jurisdiction=AZ&entityType=IND&licenseType=PRO", False),
        ("Florida",        "FL", "G258860", "https://licenseesearch.fldfs.com/Licensee/2700806", False),
        ("Kansas",         "KS", None,      "https://sbs.naic.org/solar-external-lookup/lookup/licensee/summary/21408357?jurisdiction=KS&entityType=IND&licenseType=PRO", False),
        ("Maine",          "ME", None,      "https://www.pfr.maine.gov/ALMSOnline/ALMSQuery/ShowDetail.aspx?DetailToken=704F3C701A9F11E086BB0F98AA047C448C67C5003D086308CD98C8424EC1769E", False),
        ("North Carolina", "NC", None,      "https://sbs.naic.org/solar-external-lookup/lookup/licensee/summary/21408357?jurisdiction=NC&entityType=IND&licenseType=PRO", False),
        ("Oregon",         "OR", None,      "https://sbs.naic.org/solar-external-lookup/lookup/licensee/summary/21408357?jurisdiction=OR&entityType=IND&licenseType=PRO", False),
        ("Pennsylvania",   "PA", "1152553", "https://www.sircon.com/ComplianceExpress/Inquiry/consumerInquiry.do?nonSscrb=Y", True),
        ("Texas",          "TX", "3317972", "https://www.sircon.com/ComplianceExpress/Inquiry/consumerInquiry.do?nonSscrb=Y", True),
    ]
    try:
        from db.database import _get_session_factory as _sf
        async with _sf()() as session:
            result = await session.execute(text("SELECT COUNT(*) FROM licenses WHERE user_id = :uid"), {"uid": SEB_USER_ID})
            if result.scalar() == 0:
                logger.info("Seeding 8 licenses for Seb (table empty)")
                for state, abbr, lic_num, verify_url, manual in LICENSES:
                    await session.execute(
                        text(
                            "INSERT INTO licenses (user_id, state, state_abbreviation, license_number, "
                            "verify_url, needs_manual_verification, status, license_type, created_at, updated_at) "
                            "VALUES (:uid, :state, :abbr, :lic_num, :verify_url, :manual, 'active', 'insurance_producer', NOW(), NOW())"
                        ),
                        {"uid": SEB_USER_ID, "state": state, "abbr": abbr, "lic_num": lic_num, "verify_url": verify_url, "manual": manual},
                    )
                await session.commit()
                logger.info("License seed complete — 8 records inserted")
            else:
                logger.info("Licenses already seeded — skipping")
    except Exception as exc:
        logger.warning("License seed failed (non-fatal): %s", exc)


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


@app.post("/admin/seed-licenses")
async def seed_licenses_now():
    """One-shot: force-insert Seb's 8 licenses. Idempotent — skips existing rows."""
    from sqlalchemy import text
    from db.database import _get_session_factory as _sf

    SEB_UID = "72dc5b7c-ba2c-4a1d-83b9-733ff600c0d5"
    LICENSES = [
        ("Arizona",        "AZ", None,      "https://sbs.naic.org/solar-external-lookup/lookup/licensee/summary/21408357?jurisdiction=AZ&entityType=IND&licenseType=PRO", False),
        ("Florida",        "FL", "G258860", "https://licenseesearch.fldfs.com/Licensee/2700806", False),
        ("Kansas",         "KS", None,      "https://sbs.naic.org/solar-external-lookup/lookup/licensee/summary/21408357?jurisdiction=KS&entityType=IND&licenseType=PRO", False),
        ("Maine",          "ME", None,      "https://www.pfr.maine.gov/ALMSOnline/ALMSQuery/ShowDetail.aspx?DetailToken=704F3C701A9F11E086BB0F98AA047C448C67C5003D086308CD98C8424EC1769E", False),
        ("North Carolina", "NC", None,      "https://sbs.naic.org/solar-external-lookup/lookup/licensee/summary/21408357?jurisdiction=NC&entityType=IND&licenseType=PRO", False),
        ("Oregon",         "OR", None,      "https://sbs.naic.org/solar-external-lookup/lookup/licensee/summary/21408357?jurisdiction=OR&entityType=IND&licenseType=PRO", False),
        ("Pennsylvania",   "PA", "1152553", "https://www.sircon.com/ComplianceExpress/Inquiry/consumerInquiry.do?nonSscrb=Y", True),
        ("Texas",          "TX", "3317972", "https://www.sircon.com/ComplianceExpress/Inquiry/consumerInquiry.do?nonSscrb=Y", True),
    ]
    inserted = 0
    skipped = 0
    try:
        async with _sf()() as session:
            for state, abbr, lic_num, verify_url, manual in LICENSES:
                result = await session.execute(
                    text("SELECT COUNT(*) FROM licenses WHERE user_id=:uid AND state_abbreviation=:abbr"),
                    {"uid": SEB_UID, "abbr": abbr}
                )
                if result.scalar() == 0:
                    await session.execute(
                        text(
                            "INSERT INTO licenses (user_id, state, state_abbreviation, license_number, "
                            "verify_url, needs_manual_verification, status, license_type, created_at, updated_at) "
                            "VALUES (:uid,:state,:abbr,:lic_num,:verify_url,:manual,'active','insurance_producer',NOW(),NOW())"
                        ),
                        {"uid": SEB_UID, "state": state, "abbr": abbr, "lic_num": lic_num,
                         "verify_url": verify_url, "manual": manual}
                    )
                    inserted += 1
                else:
                    skipped += 1
            await session.commit()
    except Exception as exc:
        return {"ok": False, "error": str(exc)}
    return {"ok": True, "inserted": inserted, "skipped": skipped}


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
