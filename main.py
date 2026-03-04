"""FalconConnect v3 — middleware layer for dual GHL + Notion sync."""

import logging

from contextlib import asynccontextmanager
from fastapi import FastAPI

from db.database import init_db
from routers import leads, webhooks, calendar, analytics, admin

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger("falconconnect")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup / shutdown lifecycle."""
    logger.info("FalconConnect v3 starting up …")
    await init_db()
    yield
    logger.info("FalconConnect v3 shutting down …")


app = FastAPI(
    title="FalconConnect v3",
    description="Middleware layer: dual GHL + Notion sync, iCal feed, analytics hub.",
    version="3.0.0",
    lifespan=lifespan,
)

app.include_router(leads.router, prefix="/api/public", tags=["Leads"])
app.include_router(webhooks.router, prefix="/api/webhooks", tags=["Webhooks"])
app.include_router(calendar.router, prefix="/api/calendar", tags=["Calendar"])
app.include_router(analytics.router, prefix="/api/analytics", tags=["Analytics"])
app.include_router(admin.router, prefix="/api/admin", tags=["Admin"])
