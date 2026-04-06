#!/usr/bin/env python3
"""FC startup: reconcile alembic_version with existing schema, then upgrade.

If the DB was bootstrapped via SQLAlchemy create_all() (no alembic history),
this stamps the DB at the last migration before the ones that only ADD columns
to existing tables. This way alembic upgrade head only runs the deltas.
"""
import os
import subprocess
import sys


STAMP_REVISION = "016_add_ghl_dashboard_tables"


def run(cmd: list[str]) -> int:
    print(f"[startup] Running: {' '.join(cmd)}", flush=True)
    result = subprocess.run(cmd, capture_output=False)
    return result.returncode


def alembic_version_exists(db_url: str) -> bool:
    """Check if alembic_version table exists in the DB."""
    try:
        import asyncio
        import asyncpg

        # Coerce URL to asyncpg format
        url = db_url
        if url.startswith("postgres://"):
            url = "postgresql://" + url[len("postgres://"):]
        if url.startswith("postgresql+asyncpg://"):
            url = "postgresql://" + url[len("postgresql+asyncpg://"):]

        async def _check():
            conn = await asyncpg.connect(dsn=url)
            try:
                result = await conn.fetchval(
                    "SELECT COUNT(*) FROM information_schema.tables "
                    "WHERE table_name = 'alembic_version'"
                )
                return result > 0
            finally:
                await conn.close()

        return asyncio.run(_check())
    except Exception as exc:
        print(f"[startup] alembic_version check failed: {exc}", flush=True)
        return True  # Assume it exists to avoid accidental stamp


def main():
    db_url = os.environ.get("DATABASE_URL", "")
    if not db_url or "sqlite" in db_url:
        print(
            "[startup] FATAL: DATABASE_URL is missing or SQLite. "
            "Restore postgresql+asyncpg://... in the Render env vars panel.",
            flush=True,
        )
        sys.exit(1)

    if not alembic_version_exists(db_url):
        print(
            f"[startup] alembic_version table not found — DB was bootstrapped via "
            f"create_all(). Stamping at {STAMP_REVISION} before running upgrade head.",
            flush=True,
        )
        rc = run(["python", "-m", "alembic", "stamp", STAMP_REVISION])
        if rc != 0:
            print(f"[startup] alembic stamp failed (exit {rc}). Aborting.", flush=True)
            sys.exit(rc)
    else:
        print("[startup] alembic_version table exists. Proceeding with upgrade head.", flush=True)

    rc = run(["python", "-m", "alembic", "upgrade", "head"])
    if rc != 0:
        print(f"[startup] alembic upgrade head failed (exit {rc}). Aborting.", flush=True)
        sys.exit(rc)

    print("[startup] Migrations complete. Starting uvicorn.", flush=True)
    port = os.environ.get("PORT", "10000")
    os.execv(
        sys.executable,
        [sys.executable, "-m", "uvicorn", "main:app", "--host", "0.0.0.0", "--port", port],
    )


if __name__ == "__main__":
    main()
