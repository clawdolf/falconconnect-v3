"""SQLAlchemy async engine, session factory, and init helper."""

import logging
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from config import get_settings

logger = logging.getLogger("falconconnect.db")

# Engine and session factory are created lazily on first use so that
# DATABASE_URL is read AFTER all env vars are loaded (avoids Render
# startup race where module-level get_settings() fires before env is set).
_engine = None
_async_session_factory = None


def _get_engine():
    global _engine
    if _engine is None:
        settings = get_settings()
        _engine = create_async_engine(
            settings.database_url,
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


# Convenience aliases (used by routers via Depends)
def get_engine():
    return _get_engine()


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
    """Create all tables that don't exist yet (dev convenience).

    In production Alembic migrations handle schema changes.
    """
    from db.models import Base  # noqa: F811 — imported here to avoid circular deps

    async with _get_engine().begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    logger.info("Database tables verified / created.")
