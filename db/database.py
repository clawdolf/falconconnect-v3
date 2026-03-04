"""SQLAlchemy async engine, session factory, and init helper."""

import logging

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from config import get_settings

logger = logging.getLogger("falconconnect.db")

settings = get_settings()

# For PostgreSQL the DATABASE_URL should start with postgresql+asyncpg://
# For local dev a sqlite+aiosqlite:// URL also works.
engine = create_async_engine(
    settings.database_url,
    echo=False,
    pool_pre_ping=True,
)

async_session_factory = async_sessionmaker(
    engine, class_=AsyncSession, expire_on_commit=False
)


async def get_session() -> AsyncSession:  # type: ignore[misc]
    """FastAPI dependency that yields an async DB session."""
    async with async_session_factory() as session:
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

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    logger.info("Database tables verified / created.")
