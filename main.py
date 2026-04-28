"""FalconConnect v3 — lead management and CRM integration layer."""

import logging
import os
from datetime import datetime, timezone

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

from db.database import init_db
from middleware.security_headers import SecurityHeadersMiddleware
from routers import leads, webhooks, calendar, analytics, admin, licenses, agents, campaigns, ad_leads, close_webhooks, close_lead_status, conference
from routers import ghl_cadence, cadence_sms, research
from routers.sheets import router as sheets_router
from routers.ghl_dashboard import router as ghl_dashboard_router
from routers.sms_templates import router as sms_templates_router
from utils.rate_limit import limiter

def _configure_logging() -> None:
    """JSON logs in prod (for Render log search), human logs locally.

    Render sets RENDER=true automatically; setting ENVIRONMENT=production on
    any other host opts in. Anything else stays on the old line-based format.
    """
    is_prod = (
        os.environ.get("RENDER", "").lower() == "true"
        or os.environ.get("ENVIRONMENT", "").lower() == "production"
    )
    handler = logging.StreamHandler()
    if is_prod:
        try:
            from pythonjsonlogger.jsonlogger import JsonFormatter
            handler.setFormatter(
                JsonFormatter(
                    "%(asctime)s %(levelname)s %(name)s %(message)s",
                    rename_fields={"asctime": "ts", "levelname": "level", "name": "logger"},
                )
            )
        except ImportError:
            handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    else:
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    # Replace any previously attached handlers so we don't double-log.
    root.handlers[:] = [handler]


_configure_logging()
logger = logging.getLogger("falconconnect")


def _configure_sentry() -> None:
    """Init Sentry if SENTRY_DSN is set. No-op otherwise."""
    dsn = os.environ.get("SENTRY_DSN")
    if not dsn:
        return
    try:
        import sentry_sdk
        sentry_sdk.init(
            dsn=dsn,
            traces_sample_rate=float(os.environ.get("SENTRY_TRACES_SAMPLE_RATE", "0.05")),
            environment=os.environ.get("ENVIRONMENT") or (
                "production" if os.environ.get("RENDER", "").lower() == "true" else "development"
            ),
        )
        logger.info("Sentry initialized")
    except Exception as exc:
        logger.warning("Sentry init failed (non-fatal): %s", exc)


_configure_sentry()


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
        ("Ohio",          "OH", "1733239", "https://gateway.insurance.ohio.gov/UI/ODI.Agent.Public.UI/AgentLocator.mvc/DisplayIndividualDetail/QpHt3y5h2RfCYJRLJrrJLw!3d!3d", False),
        ("Oregon",         "OR", None,      "https://sbs.naic.org/solar-external-lookup/lookup/licensee/summary/21408357?jurisdiction=OR&entityType=IND&licenseType=PRO", False),
        ("Pennsylvania",   "PA", "1152553", "https://www.sircon.com/ComplianceExpress/Inquiry/consumerInquiry.do?nonSscrb=Y", True),
        ("Texas",          "TX", "3317972", "https://www.sircon.com/ComplianceExpress/Inquiry/consumerInquiry.do?nonSscrb=Y", True),
    ]
    try:
        from db.database import _get_session_factory as _sf
        async with _sf()() as session:
            result = await session.execute(text("SELECT COUNT(*) FROM licenses WHERE user_id = :uid"), {"uid": SEB_USER_ID})
            if result.scalar() == 0:
                logger.info("Seeding 9 licenses for Seb (table empty)")
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
                logger.info("License seed complete — 9 records inserted")
            else:
                logger.info("Licenses already seeded — skipping")
    except Exception as exc:
        logger.warning("License seed failed (non-fatal): %s", exc)



async def _fix_ohio_verify_url() -> None:
    """Fix Ohio license verify_url — Ohio uses its own portal, not NAIC SOLAR.
    Runs on every startup to patch any existing DB records that have the wrong SOLAR URL.
    """
    from sqlalchemy import text
    try:
        from db.database import _get_session_factory as _sf
        canonical_uid = os.environ.get("CLERK_ADMIN_USER_ID", "user_3ASrwDOrSTaDxCus6f1B5lnDsgz")
        ohio_direct_url = (
            "https://gateway.insurance.ohio.gov/UI/ODI.Agent.Public.UI/"
            "AgentLocator.mvc/DisplayIndividualDetail/QpHt3y5h2RfCYJRLJrrJLw!3d!3d"
        )
        async with _sf()() as session:
            result = await session.execute(
                text(
                    "UPDATE licenses SET verify_url = :url, needs_manual_verification = false "
                    "WHERE user_id = :uid AND state_abbreviation = 'OH' "
                    "AND (verify_url LIKE '%naic.org%' OR verify_url = '')"
                ),
                {"uid": canonical_uid, "url": ohio_direct_url},
            )
            if result.rowcount:
                await session.commit()
                logger.info(
                    "Fixed Ohio license verify_url: %d row(s) updated to Ohio direct link",
                    result.rowcount,
                )
    except Exception as exc:
        logger.warning("Ohio license fix failed (non-fatal): %s", exc)


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




async def _seed_cadence_sms_templates() -> None:
    """Seed cadence SMS templates (r1_done/r2_done/r3_done) if missing. Idempotent."""
    from sqlalchemy import text
    CADENCE_DEFAULTS = {
        "r1_done": (
            "Hey {first_name}, tried reaching you yesterday "
            "— easier to connect by text? Just takes a couple "
            "minutes to see what coverage looks like for you."
        ),
        "r2_done": (
            "Most homeowners in {state} don't realize their mortgage "
            "has zero protection if something happens. Took 2 min "
            "to fix that for a family last week."
        ),
        "r3_done": (
            "Hey {first_name}, still happy to walk you through what "
            "mortgage protection would look like for your home. "
            "Quick call, no pressure. -Seb"
        ),
    }
    try:
        from db.database import _get_session_factory as _sf
        async with _sf()() as session:
            for key, body in CADENCE_DEFAULTS.items():
                result = await session.execute(
                    text("SELECT COUNT(*) FROM sms_templates WHERE template_key = :key"),
                    {"key": key},
                )
                if result.scalar() == 0:
                    await session.execute(
                        text(
                            "INSERT INTO sms_templates (template_key, body, created_at, updated_at) "
                            "VALUES (:key, :body, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
                        ),
                        {"key": key, "body": body},
                    )
                    logger.info("Seeded cadence SMS template: %s", key)
            await session.commit()
    except Exception as exc:
        logger.warning("Cadence SMS template seed failed (non-fatal): %s", exc)

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
        # Must be postgres — sqlite = Render env var lost, stale secret file activated
        "DATABASE_URL (postgres)": (
            bool(settings.database_url)
            and "sqlite" not in settings.database_url
        ),
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

    # Validate webhook secret length (Close uses 64-char hex strings)
    if settings.close_webhook_secret and len(settings.close_webhook_secret) != 64:
        logger.error(
            "STARTUP ERROR — CLOSE_WEBHOOK_SECRET is %d chars (expected 64). "
            "Likely truncated in Render dashboard. ALL webhooks will fail "
            "signature verification until fixed!",
            len(settings.close_webhook_secret),
        )


async def lifespan(app: FastAPI):
    """Startup / shutdown lifecycle."""
    logger.info("FalconConnect v3 starting up …")

    # Hard guard: crash immediately if DATABASE_URL is missing or pointing to SQLite.
    # Surfaces before init_db() so the error is unambiguous in Render logs.
    _raw_db_url = os.environ.get("DATABASE_URL", "")
    if not _raw_db_url or "sqlite" in _raw_db_url:
        _msg = (
            "FATAL STARTUP: DATABASE_URL is missing or set to SQLite. "
            "The Render env vars panel lost the value. "
            "Restore DATABASE_URL=postgresql+asyncpg://... in Render immediately."
        )
        logger.critical(_msg)
        raise RuntimeError(_msg)

    # Hard guard: refuse to boot with a silent auth bypass.
    # If CLERK_SECRET_KEY is missing, require ALLOW_NO_AUTH=true as an
    # explicit dev opt-in. Production must never have ALLOW_NO_AUTH set.
    _clerk_secret = os.environ.get("CLERK_SECRET_KEY", "")
    _allow_no_auth = os.environ.get("ALLOW_NO_AUTH", "").lower() == "true"
    if not _clerk_secret and not _allow_no_auth:
        _msg = (
            "FATAL STARTUP: CLERK_SECRET_KEY is missing and ALLOW_NO_AUTH is not 'true'. "
            "Booting would silently disable auth on every protected endpoint. "
            "Restore CLERK_SECRET_KEY in Render, or set ALLOW_NO_AUTH=true locally only."
        )
        logger.critical(_msg)
        raise RuntimeError(_msg)

    # Hard guard: refuse to boot in production without Turnstile configured.
    # The public ad-lead endpoints fall back to honeypot+rate-limit only when
    # TURNSTILE_SECRET is empty — that's acceptable in dev, never in prod.
    _is_prod = (
        os.environ.get("RENDER", "").lower() == "true"
        or os.environ.get("ENVIRONMENT", "").lower() == "production"
    )
    _turnstile_secret = os.environ.get("TURNSTILE_SECRET", "")
    if _is_prod and not _turnstile_secret:
        _msg = (
            "FATAL STARTUP: TURNSTILE_SECRET is missing in production. "
            "Public ad-lead endpoints would accept bot traffic with only "
            "honeypot+rate-limit protection. Set TURNSTILE_SECRET in Render."
        )
        logger.critical(_msg)
        raise RuntimeError(_msg)

    # Validate critical env vars before anything else
    _validate_critical_env()

    # init_db() runs create_all (idempotent — creates missing tables, skips existing)
    # Alembic migrations ran at build time; this is a fast safety net only.
    try:
        await init_db()
    except Exception as _init_exc:
        import traceback
        _tb = traceback.format_exc()
        logger.error("STARTUP CRASH in init_db(): %s", _init_exc)
        try:
            from services.telegram_alerts import send_telegram_alert as _tg
            import asyncio as _asyncio
            _asyncio.create_task(_tg("STARTUP CRASH\n" + _tb[:800]))
        except Exception:
            pass
        raise

    # Fix agents.user_id mismatch before seeding/deduping licenses
    await _fix_agent_user_id()

    # Seed Seb's licenses if empty (idempotent), then dedup any duplicates
    await _seed_licenses_if_empty()
    await _fix_ohio_verify_url()
    await _dedup_licenses()

    # Seed SMS templates and phone number pool
    await _seed_sms_templates()
    await _seed_cadence_sms_templates()
    await _seed_phone_numbers()

    # Validate GCal connection at startup — log ERROR + alert if broken, but don't crash
    try:
        from services.google_calendar import test_connection
        from services.telegram_alerts import send_telegram_alert as _tg_alert

        gcal_status = await test_connection()
        if gcal_status["healthy"]:
            logger.info(
                "STARTUP GCal OK — %d calendars, primary: %s",
                gcal_status["calendar_count"],
                gcal_status["primary_calendar"],
            )
        else:
            logger.error(
                "STARTUP GCal FAILED — %s. Appointments will NOT sync to calendar!",
                gcal_status["error"],
            )
            await _tg_alert(
                "<b>STARTUP: GCal connection FAILED</b>\n"
                f"Error: {gcal_status['error']}\n\n"
                "Appointments will NOT appear in Google Calendar until this is fixed.\n"
                "Check GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET, GOOGLE_REFRESH_TOKEN env vars.",
            )
    except Exception as exc:
        logger.error("STARTUP GCal validation crashed: %s", exc)

    # ── APScheduler: GHL dashboard sync every 4 hours ──
    scheduler = None
    try:
        from apscheduler.schedulers.asyncio import AsyncIOScheduler
        from services.ghl_dashboard_sync import full_sync as ghl_full_sync

        scheduler = AsyncIOScheduler()
        scheduler.add_job(ghl_full_sync, "interval", hours=4, id="ghl_dashboard_sync", replace_existing=True)
        scheduler.start()
        logger.info("APScheduler started — GHL dashboard sync every 4 hours")
    except ImportError:
        logger.warning("apscheduler not installed — GHL dashboard auto-sync disabled (pip install apscheduler)")
    except Exception as exc:
        logger.warning("APScheduler startup failed (non-fatal): %s", exc)

    yield

    # Shutdown
    if scheduler:
        scheduler.shutdown(wait=False)
    logger.info("FalconConnect v3 shutting down …")


_IS_PROD = (
    os.environ.get("RENDER", "").lower() == "true"
    or os.environ.get("ENVIRONMENT", "").lower() == "production"
)

app = FastAPI(
    title="FalconConnect v3",
    description="Middleware layer: dual GHL + Notion sync, iCal feed, analytics hub.",
    version="3.1.0",
    lifespan=lifespan,
    docs_url=None if _IS_PROD else "/docs",
    redoc_url=None if _IS_PROD else "/redoc",
    openapi_url=None if _IS_PROD else "/openapi.json",
)

# Rate limiter — prevents public endpoints from being hammered.
# See utils/rate_limit.py for the key function (CF-Connecting-IP aware).
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# Security headers (HSTS, nosniff, framing, referrer, permissions-policy)
app.add_middleware(SecurityHeadersMiddleware)

# CORS — allow FalconVerify (falconfinancial.org) to call our API.
# Clerk uses Bearer tokens, not cookies, so credentials stay off.
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "https://falconfinancial.org",
        "https://www.falconfinancial.org",
        "http://localhost:5173",
        "http://localhost:8080",
    ],
    allow_credentials=False,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=[
        "Authorization",
        "Content-Type",
        "X-Google-Token",
        "X-Requested-With",
    ],
)

# Root-level health check (Render probes /health)
@app.get("/health")
@limiter.limit("30/minute")
async def root_health(request: Request):
    """Root-level liveness probe — Render expects /health."""
    from config import get_settings
    settings = get_settings()
    return {
        "status": "healthy",
        "service": "FalconConnect v3",
        "version": "3.1.0",
        "clerk_configured": bool(settings.clerk_secret_key),
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


# API routers
# BUG 11 FIX: Leads moved from /api/public to /api (requires Clerk auth)
app.include_router(leads.router, prefix="/api", tags=["Leads"])
app.include_router(webhooks.router, prefix="/api/webhooks", tags=["Webhooks"])
app.include_router(calendar.router, prefix="/api/calendar", tags=["Calendar"])
app.include_router(analytics.router, prefix="/api/analytics", tags=["Analytics"])
app.include_router(admin.router, prefix="/api/admin", tags=["Admin"])
app.include_router(licenses.router, prefix="/api/licenses", tags=["Licenses"])
app.include_router(agents.router, prefix="/api/public", tags=["Agents"])
app.include_router(ad_leads.router, prefix="/api/public", tags=["Ad Leads"])
app.include_router(sheets_router, prefix="/api/sheets", tags=["Sheets"])
app.include_router(campaigns.router, prefix="/api/campaigns", tags=["Campaigns"])
app.include_router(close_webhooks.router, prefix="/webhooks", tags=["Close Webhooks"])
app.include_router(sms_templates_router, prefix="/api", tags=["SMS Templates"])
app.include_router(research.router, prefix="/api/research", tags=["Research"])
app.include_router(ghl_dashboard_router, prefix="/api", tags=["GHL Dashboard"])
app.include_router(conference.router, prefix="/api", tags=["Conference Bridge"])
app.include_router(ghl_cadence.router, prefix="/api/ghl", tags=["GHL Cadence"])
app.include_router(cadence_sms.router, prefix="/api/close", tags=["Cadence SMS"])
app.include_router(close_lead_status.router, prefix="/api/close", tags=["Close Lead Status Kill-Switch"])

@app.get("/api/health/gcal")
async def health_gcal():
    """Health check for Google Calendar integration.

    Tests OAuth token refresh and calendar access. Use for:
    - Heartbeat monitoring
    - Post-deploy verification
    - Debugging GCal failures

    Returns 200 with healthy=True if GCal is accessible,
    503 with healthy=False and error details if not.
    """
    from fastapi.responses import JSONResponse
    from services.google_calendar import test_connection

    result = await test_connection()
    if result["healthy"]:
        return {
            "status": "healthy",
            "service": "google_calendar",
            "calendar_count": result["calendar_count"],
            "primary_calendar": result["primary_calendar"],
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
    else:
        return JSONResponse(
            status_code=503,
            content={
                "status": "unhealthy",
                "service": "google_calendar",
                "error": result["error"],
                "timestamp": datetime.now(timezone.utc).isoformat(),
            },
        )


# Serve React frontend — must be LAST so API routes take priority
frontend_dist = os.path.join(os.path.dirname(__file__), "frontend", "dist")
if os.path.isdir(frontend_dist):
    # Static assets (JS, CSS, images) — served by Starlette StaticFiles
    app.mount("/assets", StaticFiles(directory=os.path.join(frontend_dist, "assets")), name="frontend-assets")

    # SPA catch-all: any non-API, non-asset path returns index.html
    # StaticFiles(html=True) does NOT do SPA fallback — it only serves
    # index.html for directory paths, not arbitrary paths like /licenses.
    from fastapi.responses import FileResponse

    _BLOCKED_DOC_PATHS = {"docs", "redoc", "openapi.json"}

    @app.get("/{full_path:path}")
    async def spa_catchall(full_path: str):
        """Serve index.html for all unmatched paths (SPA client-side routing)."""
        # In prod, explicitly 404 the API doc paths so the SPA fallback
        # doesn't mask the FastAPI docs_url=None gating.
        if _IS_PROD and full_path in _BLOCKED_DOC_PATHS:
            from fastapi import HTTPException
            raise HTTPException(status_code=404)
        # Try to serve the exact file first (favicon.ico, falcon-logo.png, etc.)
        file_path = os.path.join(frontend_dist, full_path)
        if full_path and os.path.isfile(file_path):
            return FileResponse(file_path)
        # Otherwise serve index.html for SPA routing
        return FileResponse(os.path.join(frontend_dist, "index.html"))

    logger.info("Serving frontend from %s (SPA catch-all enabled)", frontend_dist)
else:
    logger.info("No frontend/dist directory found — frontend not served")
