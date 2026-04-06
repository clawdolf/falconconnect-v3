"""SQLAlchemy async engine, session factory, and init helper."""

import logging
import os

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from config import get_settings

logger = logging.getLogger("falconconnect.db")

# Engine and session factory are created lazily on first use so that
# DATABASE_URL is read AFTER all env vars are loaded (avoids Render
# startup race where module-level get_settings() fires before env is set).
_engine = None
_async_session_factory = None


def _coerce_database_url(url: str) -> str:
    """Normalize DATABASE_URL to the format SQLAlchemy async engine expects.

    Render (and some other hosts) provide a bare 'postgres://' or
    'postgresql://' connection string.  SQLAlchemy's async engine requires
    the driver to be specified explicitly; asyncpg is the only async driver
    in our requirements.

    Transformation rules:
      postgres://...      -> postgresql+asyncpg://...
      postgresql://...    -> postgresql+asyncpg://...
      (anything else)     -> unchanged (e.g. sqlite+aiosqlite://...)
    """
    if url.startswith("postgres://"):
        return "postgresql+asyncpg://" + url[len("postgres://"):]
    if url.startswith("postgresql://"):
        return "postgresql+asyncpg://" + url[len("postgresql://"):]
    return url


def _get_engine():
    global _engine
    if _engine is None:
        settings = get_settings()
        db_url = _coerce_database_url(settings.database_url)

        # Hard-fail if sqlite sneaks in — this always means a missing DATABASE_URL
        # in Render env vars (the secret file has a stale sqlite fallback).
        # Starting on SQLite crashes immediately on ARRAY/JSONB column types anyway.
        if "sqlite" in db_url:
            raise RuntimeError(
                "FATAL: DATABASE_URL resolved to SQLite. This means DATABASE_URL is missing "
                "from Render env vars and the stale secret file fallback activated. "
                "Fix: add DATABASE_URL=postgresql+asyncpg://... to the Render env vars panel."
            )

        if db_url != settings.database_url:
            logger.info(
                "DATABASE_URL scheme coerced to postgresql+asyncpg:// "
                "(original prefix: %s)", settings.database_url.split("://")[0]
            )
        _engine = create_async_engine(
            db_url,
            echo=False,
            pool_pre_ping=True,
        )
    return _engine


def _get_session_factory():
    global _async_session_factory
    if _async_session_factory is None:
        _async_session_factory = async_sessionmaker(
            _get_engine(), class_=AsyncSession, expire_on_commit=False
        )
    return _async_session_factory


async def get_session() -> AsyncSession:  # type: ignore[misc]
    """FastAPI dependency that yields an async DB session."""
    async with _get_session_factory()() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


async def init_db() -> None:
    """Create all tables that don't exist yet, then seed required records.

    create_all is idempotent — safe to run on every startup.
    Seeding is guarded by existence checks — also idempotent.
    """
    from db.models import Base, DBAgent  # noqa: F811
    from sqlalchemy import select
    import json

    async with _get_engine().begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    logger.info("Database tables verified / created.")

    # One-time migration: update old internal UUID → real Clerk user ID on licenses + agents
    CLERK_ID = os.environ.get("CLERK_ADMIN_USER_ID", "user_3ASrwDOrSTaDxCus6f1B5lnDsgz")
    OLD_UUID = "72dc5b7c-ba2c-4a1d-83b9-733ff600c0d5"
    from sqlalchemy import text as _text
    async with _get_session_factory()() as session:
        await session.execute(
            _text("UPDATE licenses SET user_id = :new WHERE user_id = :old"),
            {"new": CLERK_ID, "old": OLD_UUID},
        )
        await session.execute(
            _text("UPDATE agents SET user_id = :new WHERE user_id = :old"),
            {"new": CLERK_ID, "old": OLD_UUID},
        )
        await session.commit()

    # Seed Seb's agent record if not present
    async with _get_session_factory()() as session:
        result = await session.execute(
            select(DBAgent).where(DBAgent.slug == "seb")
        )
        existing = result.scalar_one_or_none()
        if not existing:
            carriers = json.dumps([
                "Transamerica", "Mutual of Omaha", "AIG", "Americo",
                "Foresters Financial", "Protective Life", "Prudential",
                "Lincoln Financial", "Pacific Life", "Penn Mutual",
                "Nationwide", "Securian Financial",
            ])
            seb = DBAgent(
                user_id=os.environ.get("CLERK_ADMIN_USER_ID", "user_3ASrwDOrSTaDxCus6f1B5lnDsgz"),
                slug="seb",
                name="Sébastien Taillieu",
                title="Founder & Principal Advisor",
                bio=(
                    "Independent life insurance broker with access to 47+ A-rated carriers. "
                    "Specializing in mortgage protection, term life, IUL, and final expense coverage."
                ),
                phone="+14809999040",
                phone_display="(480) 999-9040",
                email="seb@falconfinancial.org",
                calendar_url=None,
                npn="21408357",
                location="Scottsdale Airpark, Arizona",
                carrier_count=47,
                carriers_json=carriers,
                is_active=True,
            )
            session.add(seb)
            await session.commit()
            logger.info("Seeded Seb's agent record.")
