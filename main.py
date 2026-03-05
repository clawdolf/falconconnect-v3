"""FalconConnect v3 — middleware layer for dual GHL + Notion sync."""

import asyncio
import logging
import os
from datetime import datetime, timezone

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from db.database import init_db
from routers import leads, webhooks, calendar, analytics, admin, sync, licenses, agents
from routers.sheets import router as sheets_router
from services.notion_ghl_sync import sync_loop

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger("falconconnect")


async def _seed_licenses_if_empty() -> None:
    """Seed Seb's 8 licenses if table is empty for his Clerk user ID. Idempotent."""
    from sqlalchemy import text

    SEB_USER_ID = os.environ.get("CLERK_ADMIN_USER_ID", "user_3ASrwDOrSTaDxCus6f1B5lnDsgz")
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


async def _dedup_licenses() -> None:
    """Clean up stale/duplicate license rows. Removes rows from old user IDs and deduplicates."""
    from sqlalchemy import text
    try:
        from db.database import _get_session_factory as _sf
        canonical_uid = os.environ.get("CLERK_ADMIN_USER_ID", "user_3ASrwDOrSTaDxCus6f1B5lnDsgz")

        # Known stale user IDs from past bugs
        OLD_UIDS = [
            "72dc5b7c-ba2c-4a1d-83b9-733ff600c0d5",  # FC v3 UUID
            "user_3ASljZWeTNVAOMGP62n87Eq0GG9",        # Old dev mode hardcoded
        ]

        async with _sf()() as session:
            total_deleted = 0

            # Delete rows belonging to old/stale user IDs where canonical ID already has that state
            for old_uid in OLD_UIDS:
                if old_uid == canonical_uid:
                    continue
                result = await session.execute(text(
                    "DELETE FROM licenses WHERE user_id = :old_uid "
                    "AND state_abbreviation IN ("
                    "  SELECT state_abbreviation FROM licenses WHERE user_id = :canonical_uid"
                    ")"
                ), {"old_uid": old_uid, "canonical_uid": canonical_uid})
                total_deleted += result.rowcount

            # General dedup: keep newest row per (user_id, state_abbreviation)
            result = await session.execute(text(
                "DELETE FROM licenses WHERE id IN ("
                "  SELECT id FROM ("
                "    SELECT id, ROW_NUMBER() OVER ("
                "      PARTITION BY user_id, state_abbreviation ORDER BY id DESC"
                "    ) AS rn FROM licenses"
                "  ) ranked WHERE rn > 1"
                ")"
            ))
            total_deleted += result.rowcount

            if total_deleted:
                await session.commit()
                logger.info("License cleanup: removed %d stale/duplicate rows", total_deleted)
    except Exception as exc:
        logger.warning("License cleanup failed (non-fatal): %s", exc)


async def lifespan(app: FastAPI):
    """Startup / shutdown lifecycle."""
    logger.info("FalconConnect v3 starting up …")

    # init_db() runs create_all (idempotent — creates missing tables, skips existing)
    # Alembic migrations ran at build time; this is a fast safety net only.
    await init_db()

    # Seed Seb's licenses if empty (idempotent), then dedup any duplicates
    await _seed_licenses_if_empty()
    await _dedup_licenses()

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

# CORS — allow FalconVerify (falconfinancial.org) to call our API
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "https://falconfinancial.org",
        "https://www.falconfinancial.org",
        "http://localhost:5173",
        "http://localhost:8080",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
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

    SEB_UID = os.environ.get("CLERK_ADMIN_USER_ID", "user_3ASrwDOrSTaDxCus6f1B5lnDsgz")
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


@app.get("/debug/agent-user-ids")
async def debug_agent_user_ids():
    """Temporary: show agents.user_id vs licenses.user_id to diagnose mismatch."""
    from sqlalchemy import text
    from db.database import _get_session_factory as _sf
    async with _sf()() as session:
        agents_result = await session.execute(text("SELECT slug, user_id FROM agents LIMIT 5"))
        agents_rows = agents_result.fetchall()
        lic_result = await session.execute(text("SELECT DISTINCT user_id, COUNT(*) as cnt FROM licenses GROUP BY user_id"))
        lic_rows = lic_result.fetchall()
    return {
        "agents": [{"slug": r[0], "user_id": r[1]} for r in agents_rows],
        "license_user_ids": [{"user_id": r[0], "count": r[1]} for r in lic_rows],
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




# API routers
# BUG 11 FIX: Leads moved from /api/public to /api (requires Clerk auth)
app.include_router(leads.router, prefix="/api", tags=["Leads"])
app.include_router(webhooks.router, prefix="/api/webhooks", tags=["Webhooks"])
app.include_router(calendar.router, prefix="/api/calendar", tags=["Calendar"])
app.include_router(analytics.router, prefix="/api/analytics", tags=["Analytics"])
app.include_router(admin.router, prefix="/api/admin", tags=["Admin"])
app.include_router(sync.router, prefix="/api/sync", tags=["Sync"])
app.include_router(licenses.router, prefix="/api/licenses", tags=["Licenses"])
app.include_router(agents.router, prefix="/api/public", tags=["Agents"])
app.include_router(sheets_router, prefix="/api/sheets", tags=["Sheets"])

# Serve React frontend (built files) — must be LAST so API routes take priority
frontend_dist = os.path.join(os.path.dirname(__file__), "frontend", "dist")
if os.path.isdir(frontend_dist):
    app.mount("/", StaticFiles(directory=frontend_dist, html=True), name="frontend")
    logger.info("Serving frontend from %s", frontend_dist)
else:
    logger.info("No frontend/dist directory found — frontend not served")
