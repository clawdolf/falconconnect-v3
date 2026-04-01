"""GHL Dashboard — read-only intel endpoints."""

import logging
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, Query
from config import Settings, get_settings
from services.ghl_dashboard_client import GHLDashboardClient
from services.ghl_dashboard_sync import run_compliance_check

logger = logging.getLogger("ghl_dashboard")

router = APIRouter(prefix="/ghl-dashboard", tags=["GHL Dashboard"])


def get_client(settings: Settings = Depends(get_settings)) -> GHLDashboardClient:
    """Dependency: instantiate GHL client from settings."""
    return GHLDashboardClient(settings.ghl_private_token, settings.ghl_location_id)


@router.get("/summary")
async def get_summary(client: GHLDashboardClient = Depends(get_client)):
    """GET /api/ghl-dashboard/summary

    Returns high-level metrics:
    - contact_count: total contacts
    - pipeline_count: total pipelines
    - compliance_score: percentage of compliant contacts (cached)
    - last_sync: timestamp of last sync
    """
    try:
        contact_count = await client.get_contacts_count()
        pipelines = await client.get_pipelines()

        return {
            "contact_count": contact_count,
            "pipeline_count": len(pipelines),
            "compliance_score": 0,  # Placeholder
            "last_sync": datetime.now(timezone.utc).isoformat(),
        }
    except Exception as exc:
        logger.error(f"get_summary failed: {exc}")
        return {
            "contact_count": 0,
            "pipeline_count": 0,
            "compliance_score": 0,
            "last_sync": None,
            "error": str(exc),
        }


@router.get("/contacts")
async def get_contacts(
    limit: int = Query(50, ge=1, le=100),
    client: GHLDashboardClient = Depends(get_client),
):
    """GET /api/ghl-dashboard/contacts?limit=50

    Returns contact list (cursor-based, GHL v2).
    """
    try:
        result = await client.get_contacts(limit=limit)
        contacts = result.get("contacts", [])
        meta = result.get("meta", {})
        return {
            "limit": limit,
            "count": len(contacts),
            "total": meta.get("total", len(contacts)),
            "contacts": contacts,
        }
    except Exception as exc:
        logger.error(f"get_contacts failed: {exc}")
        return {
            "limit": limit,
            "count": 0,
            "total": 0,
            "contacts": [],
            "error": str(exc),
        }


@router.get("/contacts/compliance")
async def get_contacts_compliance(client: GHLDashboardClient = Depends(get_client)):
    """GET /api/ghl-dashboard/contacts/compliance

    Returns compliance report across all contacts.
    """
    try:
        # Fetch contacts (first 100 for compliance check)
        result = await client.get_contacts(limit=100)
        contacts_list = result.get("contacts", []) if isinstance(result, dict) else []
        report = run_compliance_check(contacts_list)
        return {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            **report,
        }
    except Exception as exc:
        logger.error(f"get_contacts_compliance failed: {exc}")
        return {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "total": 0,
            "compliant": 0,
            "compliance_rate": 0,
            "issues": [],
            "error": str(exc),
        }


@router.get("/pipelines")
async def get_pipelines(client: GHLDashboardClient = Depends(get_client)):
    """GET /api/ghl-dashboard/pipelines

    Returns list of all pipelines.
    """
    try:
        pipelines = await client.get_pipelines()
        return {
            "count": len(pipelines),
            "pipelines": pipelines,
        }
    except Exception as exc:
        logger.error(f"get_pipelines failed: {exc}")
        return {
            "count": 0,
            "pipelines": [],
            "error": str(exc),
        }


@router.get("/pipelines/{pipeline_id}/opportunities")
async def get_pipeline_opportunities(
    pipeline_id: str,
    limit: int = Query(100, ge=1, le=100),
    client: GHLDashboardClient = Depends(get_client),
):
    """GET /api/ghl-dashboard/pipelines/{pipeline_id}/opportunities

    Returns opportunities for a specific pipeline.
    """
    try:
        opportunities = await client.get_opportunities(pipeline_id, limit=limit)
        return {
            "pipeline_id": pipeline_id,
            "count": len(opportunities),
            "opportunities": opportunities,
        }
    except Exception as exc:
        logger.error(f"get_pipeline_opportunities failed: {exc}")
        return {
            "pipeline_id": pipeline_id,
            "count": 0,
            "opportunities": [],
            "error": str(exc),
        }


@router.get("/conversations")
async def get_conversations(
    limit: int = Query(100, ge=1, le=100),
    client: GHLDashboardClient = Depends(get_client),
):
    """GET /api/ghl-dashboard/conversations

    Returns recent conversations.
    """
    try:
        conversations = await client.get_conversations(limit=limit)
        return {
            "count": len(conversations),
            "conversations": conversations,
        }
    except Exception as exc:
        logger.error(f"get_conversations failed: {exc}")
        return {
            "count": 0,
            "conversations": [],
            "error": str(exc),
        }


@router.get("/sync/status")
async def get_sync_status(client: GHLDashboardClient = Depends(get_client)):
    """GET /api/ghl-dashboard/sync/status

    Returns live status by checking GHL API connectivity + counts.
    """
    try:
        count = await client.get_contacts_count()
        return {
            "last_sync": datetime.now(timezone.utc).isoformat(),
            "records_processed": count,
            "status": "connected" if count > 0 else "empty",
            "error": None,
        }
    except Exception as exc:
        return {
            "last_sync": None,
            "records_processed": 0,
            "status": "error",
            "error": str(exc),
        }


@router.post("/sync/trigger")
async def trigger_sync(client: GHLDashboardClient = Depends(get_client)):
    """POST /api/ghl-dashboard/sync/trigger

    Run a live sync check against GHL and return results.
    """
    try:
        count = await client.get_contacts_count()
        pipelines = await client.get_pipelines()
        return {
            "status": "complete",
            "contact_count": count,
            "pipeline_count": len(pipelines),
            "synced_at": datetime.now(timezone.utc).isoformat(),
        }
    except Exception as exc:
        return {"status": "error", "error": str(exc)}
