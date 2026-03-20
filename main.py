"""FalconConnect v3 — middleware layer for dual GHL + Notion sync."""

import asyncio
import logging
import os
from datetime import datetime, timezone

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from db.database import init_db
from routers import leads, webhooks, calendar, analytics, admin, sync, licenses, agents, campaigns, ad_leads, close_webhooks
from routers.sheets import router as sheets_router
from routers.sms_templates import router as sms_templates_router
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
                            "VALUES (:uid, :state, :abbr, :lic_num, :verify_url, :manual, 'active', 'insurance_producer', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
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


async def _seed_sms_templates() -> None:
    """Seed default SMS templates if table is empty. Idempotent."""
    from sqlalchemy import text
    try:
        from db.database import _get_session_factory as _sf
        from services.close_sms import DEFAULT_TEMPLATES

        async with _sf()() as session:
            result = await session.execute(text("SELECT COUNT(*) FROM sms_templates"))
            if result.scalar() == 0:
                logger.info("Seeding default SMS templates")
                for key, body in DEFAULT_TEMPLATES.items():
                    await session.execute(
                        text(
                            "INSERT INTO sms_templates (template_key, body, created_at, updated_at) "
                            "VALUES (:key, :body, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
                        ),
                        {"key": key, "body": body},
                    )
                await session.commit()
                logger.info("SMS template seed complete — %d templates", len(DEFAULT_TEMPLATES))
            else:
                logger.info("SMS templates already seeded — skipping")
    except Exception as exc:
        logger.warning("SMS template seed failed (non-fatal): %s", exc)


async def _seed_phone_numbers() -> None:
    """Seed phone number pool if table is empty. Idempotent."""
    import json
    from sqlalchemy import text
    try:
        from db.database import _get_session_factory as _sf

        NUMBER_POOL = [
            {"number": "+14809999040", "state": "AZ", "area_codes": [480]},
            {"number": "+14066463344", "state": "MT", "area_codes": [406]},
            {"number": "+19808909888", "state": "NC", "area_codes": [980, 984]},
            {"number": "+12078881046", "state": "ME", "area_codes": [207]},
            {"number": "+12078087772", "state": "ME", "area_codes": [207]},
            {"number": "+19133793347", "state": "KS", "area_codes": [913]},
            {"number": "+19719993141", "state": "OR", "area_codes": [971, 541]},
            {"number": "+15419195227", "state": "OR", "area_codes": [541, 971]},
            {"number": "+18323042324", "state": "TX", "area_codes": [832, 469, 972]},
            {"number": "+14699492579", "state": "TX", "area_codes": [469, 832, 972]},
            {"number": "+12156077444", "state": "PA", "area_codes": [215]},
            {"number": "+19843685120", "state": "NC", "area_codes": [984, 980]},
            {"number": "+12076067024", "state": "ME", "area_codes": [207]},
            {"number": "+17862548006", "state": "FL", "area_codes": [786, 305, 954]},
            {"number": "+17867677634", "state": "FL", "area_codes": [786, 305, 954]},
            {"number": "+18322420926", "state": "TX", "area_codes": [832, 469, 972]},
            {"number": "+18326482428", "state": "TX", "area_codes": [832, 469, 972]},
            {"number": "+19727341666", "state": "TX", "area_codes": [972, 469, 832]},
        ]

        async with _sf()() as session:
            result = await session.execute(text("SELECT COUNT(*) FROM phone_numbers"))
            if result.scalar() == 0:
                logger.info("Seeding phone number pool (%d numbers)", len(NUMBER_POOL))
                for entry in NUMBER_POOL:
                    await session.execute(
                        text(
                            "INSERT INTO phone_numbers (number, state, area_codes_json, is_active, created_at) "
                            "VALUES (:number, :state, :area_codes_json, 1, CURRENT_TIMESTAMP)"
                        ),
                        {
                            "number": entry["number"],
                            "state": entry["state"],
                            "area_codes_json": json.dumps(entry["area_codes"]),
                        },
                    )
                await session.commit()
                logger.info("Phone number seed complete — %d numbers", len(NUMBER_POOL))
            else:
                logger.info("Phone numbers already seeded — skipping")
    except Exception as exc:
        logger.warning("Phone number seed failed (non-fatal): %s", exc)


async def _fix_agent_user_id() -> None:
    """Ensure agents.user_id matches the canonical Clerk ID (licenses.user_id).

    Bug: migration 007 seeded agents with a dev-mode hardcoded Clerk ID
    ('user_3ASljZWeTNVAOMGP62n87Eq0GG9') instead of the real admin Clerk ID.
    Migration 008 fixed licenses but not agents. This runs on every startup
    as a safe idempotent fix.
    """
    from sqlalchemy import text
    try:
        from db.database import _get_session_factory as _sf
        canonical_uid = os.environ.get("CLERK_ADMIN_USER_ID", "user_3ASrwDOrSTaDxCus6f1B5lnDsgz")
        stale_uids = [
            "user_3ASljZWeTNVAOMGP62n87Eq0GG9",          # dev-mode hardcoded (wrong)
            "72dc5b7c-ba2c-4a1d-83b9-733ff600c0d5",       # FC v3 UUID (wrong)
        ]
        async with _sf()() as session:
            for old_uid in stale_uids:
                if old_uid == canonical_uid:
                    continue
                result = await session.execute(
                    text("UPDATE agents SET user_id = :new_uid WHERE user_id = :old_uid"),
                    {"new_uid": canonical_uid, "old_uid": old_uid},
                )
                if result.rowcount:
                    logger.info("Fixed agents.user_id: %s → %s (%d row(s))", old_uid, canonical_uid, result.rowcount)
            await session.commit()
    except Exception as exc:
        logger.warning("Agent user_id fix failed (non-fatal): %s", exc)


def _validate_critical_env() -> None:
    """Check critical env vars at startup and log warnings for any missing.

    This is a diagnostic guard — the app still starts, but operators get
    clear log output about what will break if vars are absent.
    """
    from config import get_settings

    settings = get_settings()
    critical = {
        "CLOSE_API_KEY": bool(settings.close_api_key),
        "CLOSE_WEBHOOK_SECRET": bool(settings.close_webhook_secret),
        "CLOSE_APPOINTMENT_ACTIVITY_TYPE_ID": bool(settings.close_appointment_activity_type_id),
        "GOOGLE_CLIENT_ID": bool(settings.google_client_id),
        "GOOGLE_CLIENT_SECRET": bool(settings.google_client_secret),
        "GOOGLE_REFRESH_TOKEN": bool(settings.google_refresh_token),
        "CLERK_SECRET_KEY": bool(settings.clerk_secret_key),
        "CLERK_PUBLISHABLE_KEY": bool(settings.clerk_publishable_key),
        "DATABASE_URL": bool(settings.database_url),
        "GHL_API_KEY": bool(settings.ghl_api_key),
    }
    missing = [k for k, present in critical.items() if not present]

    # Also report which .env files were loaded
    from pathlib import Path
    env_files = [p for p in [".env", "/etc/secrets/.env"] if Path(p).is_file()]
    logger.info("STARTUP ENV — .env files found: %s", env_files or "(none)")

    if missing:
        logger.warning(
            "STARTUP WARNING — %d critical env var(s) missing: %s",
            len(missing),
            missing,
        )
        logger.warning(
            "Features will degrade. If on Render, check the Secret File "
            "(/etc/secrets/.env) — it is the primary config source. "
            "Render Dashboard env-vars are overrides only."
        )
    else:
        logger.info("STARTUP OK — all %d critical env vars present", len(critical))


async def lifespan(app: FastAPI):
    """Startup / shutdown lifecycle."""
    logger.info("FalconConnect v3 starting up …")

    # Validate critical env vars before anything else
    _validate_critical_env()

    # init_db() runs create_all (idempotent — creates missing tables, skips existing)
    # Alembic migrations ran at build time; this is a fast safety net only.
    await init_db()

    # Fix agents.user_id mismatch before seeding/deduping licenses
    await _fix_agent_user_id()

    # Seed Seb's licenses if empty (idempotent), then dedup any duplicates
    await _seed_licenses_if_empty()
    await _dedup_licenses()

    # Seed SMS templates and phone number pool
    await _seed_sms_templates()
    await _seed_phone_numbers()

    # Start background Notion → GHL sync loop (disabled 2026-03-15 — was blocking app startup)
    # sync_task = asyncio.create_task(sync_loop())
    # logger.info("Notion→GHL background sync task started")
    sync_task = None  # placeholder for shutdown logic

    yield

    # Shutdown
    if sync_task:
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
                            "VALUES (:uid,:state,:abbr,:lic_num,:verify_url,:manual,'active','insurance_producer',CURRENT_TIMESTAMP,CURRENT_TIMESTAMP)"
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
    """Temporary debug endpoint — checks raw env vars."""
    import os
    from pathlib import Path

    from config import get_settings
    settings = get_settings()
    return {
        "CLERK_SECRET_KEY_set": bool(os.environ.get("CLERK_SECRET_KEY", "")),
        "CLERK_PUBLISHABLE_KEY_set": bool(os.environ.get("CLERK_PUBLISHABLE_KEY", "")),
        "GHL_API_KEY_set": bool(os.environ.get("GHL_API_KEY", "")),
        "CLOSE_API_KEY_set": bool(os.environ.get("CLOSE_API_KEY", "")),
        "GOOGLE_REFRESH_TOKEN_set": bool(os.environ.get("GOOGLE_REFRESH_TOKEN", "")),
        "settings_clerk_configured": bool(settings.clerk_secret_key),
        "settings_close_configured": bool(settings.close_api_key),
        "settings_gcal_configured": bool(settings.google_refresh_token),
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
app.include_router(ad_leads.router, prefix="/api/public", tags=["Ad Leads"])
app.include_router(sheets_router, prefix="/api/sheets", tags=["Sheets"])
app.include_router(campaigns.router, prefix="/api/campaigns", tags=["Campaigns"])
app.include_router(close_webhooks.router, prefix="/webhooks", tags=["Close Webhooks"])
app.include_router(sms_templates_router, prefix="/api", tags=["SMS Templates"])
from routers import research
app.include_router(research.router, prefix="/api/research", tags=["Research"])

@app.get("/debug/gcal-test")
async def debug_gcal_test():
    """Diagnostic: test Google Calendar event creation and return full error."""
    import traceback as tb
    from datetime import timedelta
    from services.google_calendar import _get_calendar_service, create_appointment_event, delete_event

    results = {"service_ok": False, "event_ok": False}

    # Step 1: test service build
    try:
        service = _get_calendar_service()
        results["service_ok"] = True
        cals = service.calendarList().list(maxResults=1).execute()
        results["calendar_count"] = len(cals.get("items", []))
    except Exception as e:
        results["service_error"] = f"{type(e).__name__}: {e}"
        results["service_traceback"] = tb.format_exc()

    # Step 2: test event creation (same flow as webhook)
    try:
        from datetime import timezone
        start_dt = datetime.now(timezone.utc) + timedelta(hours=2)
        event_id = await create_appointment_event(
            summary="[DIAG] GCal Test",
            description="Diagnostic — safe to delete",
            start_dt=start_dt,
            duration_minutes=15,
            attendee_email="diag-test@cal.falconnect.org",
        )
        results["event_id"] = event_id
        results["event_ok"] = event_id is not None
        if event_id:
            await delete_event(event_id)
            results["cleanup"] = "deleted"
    except Exception as e:
        results["event_error"] = f"{type(e).__name__}: {e}"
        results["event_traceback"] = tb.format_exc()

    return results


@app.get("/debug/appointment-records")
async def debug_appointment_records():
    """Diagnostic: list recent appointment_reminders and calendar_emails from DB."""
    from sqlalchemy import text
    from db.database import _get_session_factory as _sf

    records = []
    try:
        async with _sf()() as session:
            result = await session.execute(text("""
                SELECT id, lead_id, contact_id, appointment_datetime,
                       gcal_event_id, status,
                       sms_id_confirmation, sms_id_24hr, sms_id_1hr
                FROM appointment_reminders
                ORDER BY id DESC
                LIMIT 15
            """))
            rows = result.fetchall()
            for r in rows:
                records.append({
                    "id": r[0], "lead_id": r[1], "contact_id": r[2],
                    "appointment_datetime": str(r[3]),
                    "gcal_event_id": r[4], "status": r[5],
                    "sms_confirmation": r[6], "sms_24hr": r[7], "sms_1hr": r[8],
                })
    except Exception as e:
        return {"error": str(e)}

    cal_emails = []
    try:
        async with _sf()() as session:
            result = await session.execute(text("""
                SELECT id, lead_id, contact_id, dummy_email, gcal_event_id
                FROM appointment_calendar_emails
                ORDER BY id DESC
                LIMIT 15
            """))
            rows = result.fetchall()
            for r in rows:
                cal_emails.append({
                    "id": r[0], "lead_id": r[1], "contact_id": r[2],
                    "dummy_email": r[3], "gcal_event_id": r[4],
                })
    except Exception as e:
        cal_emails = [{"error": str(e)}]

    return {"appointment_reminders": records, "calendar_emails": cal_emails}


# Serve React frontend (built files) — must be LAST so API routes take priority
frontend_dist = os.path.join(os.path.dirname(__file__), "frontend", "dist")
if os.path.isdir(frontend_dist):
    app.mount("/", StaticFiles(directory=frontend_dist, html=True), name="frontend")
    logger.info("Serving frontend from %s", frontend_dist)
else:
    logger.info("No frontend/dist directory found — frontend not served")
