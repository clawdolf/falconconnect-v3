"""Admin-only Registry v1 endpoints.

Registry v1 is review-only. This router writes only local registry tables and
never mutates Close, GHL, or Notion.
"""

from __future__ import annotations

import csv
import io
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import Response
from sqlalchemy.ext.asyncio import AsyncSession

from db.database import get_session
from routers.lead_hygiene import require_admin
from services.registry import REGISTRY_V1_ENABLED
from services.registry import reengagement
from services.registry import service
from services.registry.schemas import (
    ReengagementCampaignPreview,
    ReengagementCampaignPreviewRequest,
    ReengagementPoolRow,
    ReengagementPoolSummary,
    RegistryConnectionStatus,
    RegistryConsentEventOut,
    RegistryHouseholdDetail,
    RegistryHouseholdOut,
    RegistryImportSummary,
    RegistryLeadHygieneReportOut,
    RegistryPersonDetail,
    RegistryPersonOut,
    RegistryRecommendationOut,
    RegistrySankeyOut,
)

router = APIRouter()


def _enabled() -> None:
    if not REGISTRY_V1_ENABLED:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Registry v1 is disabled.")


@router.get("/summary")
async def get_summary(
    _user=Depends(require_admin),
    session: AsyncSession = Depends(get_session),
):
    _enabled()
    return await service.summary(session)


@router.get("/sankey", response_model=RegistrySankeyOut)
async def get_sankey(
    from_: datetime | None = Query(None, alias="from"),
    to: datetime | None = Query(None),
    sources: str | None = Query(None),
    level: str = Query("household", pattern="^(household|row)$"),
    top_n: int = Query(8, ge=1, le=20),
    include_unknown_risk: bool = Query(True),
    _user=Depends(require_admin),
    session: AsyncSession = Depends(get_session),
):
    _enabled()
    source_list = [item.strip() for item in sources.split(",")] if sources else None
    return await service.sankey(
        session,
        from_date=from_,
        to_date=to,
        sources=source_list,
        level=level,
        top_n=top_n,
        include_unknown_risk=include_unknown_risk,
    )


@router.get("/households", response_model=list[RegistryHouseholdOut])
async def get_households(
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    q: str | None = Query(None, max_length=256),
    risk: str | None = Query(None, max_length=128),
    source: str | None = Query(None, max_length=128),
    bucket: str | None = Query(None, max_length=256),
    has_dnc: bool | None = Query(None),
    has_conflict: bool | None = Query(None),
    sort: str = Query("latest", pattern="^(latest|risk|recommendations|name)$"),
    _user=Depends(require_admin),
    session: AsyncSession = Depends(get_session),
):
    _enabled()
    return await service.list_households(
        session,
        limit=limit,
        offset=offset,
        q=q,
        risk=risk,
        source=source,
        bucket=bucket,
        has_dnc=has_dnc,
        has_conflict=has_conflict,
        sort=sort,
    )


@router.get("/households/{household_id}", response_model=RegistryHouseholdDetail)
async def get_household(
    household_id: int,
    _user=Depends(require_admin),
    session: AsyncSession = Depends(get_session),
):
    _enabled()
    household = await service.household_detail(session, household_id)
    if household is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Household not found.")
    return household


@router.get("/people", response_model=list[RegistryPersonOut])
async def get_people(
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    _user=Depends(require_admin),
    session: AsyncSession = Depends(get_session),
):
    _enabled()
    return await service.list_people(session, limit=limit, offset=offset)


@router.get("/people/{person_id}", response_model=RegistryPersonDetail)
async def get_person(
    person_id: int,
    _user=Depends(require_admin),
    session: AsyncSession = Depends(get_session),
):
    _enabled()
    person = await service.person_detail(session, person_id)
    if person is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Person not found.")
    return {
        **RegistryPersonOut.model_validate(person).model_dump(),
        "household": person.household,
        "contact_methods": person.contact_methods,
        "external_records": await service.external_records_for_person(session, person_id),
        "recommendations": await service.recommendations_for_person(session, person_id),
        "consent_events": await service.consent_events_for_person(session, person_id),
    }


@router.get("/search")
async def search(
    q: str = Query(..., min_length=1, max_length=256),
    limit: int = Query(25, ge=1, le=100),
    _user=Depends(require_admin),
    session: AsyncSession = Depends(get_session),
):
    _enabled()
    results = await service.search(session, q=q, limit=limit)
    return {
        "households": [RegistryHouseholdOut.model_validate(service.household_row(item)) for item in results["households"]],
        "people": [RegistryPersonOut.model_validate(item) for item in results["people"]],
        # Search is a household/person discovery surface. Keep raw contact methods
        # and external IDs out of the payload; full contact values are available
        # only inside the admin household detail drawer.
        "contact_methods": [],
        "external_records": [],
    }


@router.get("/recommendations", response_model=list[RegistryRecommendationOut])
async def get_recommendations(
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    _user=Depends(require_admin),
    session: AsyncSession = Depends(get_session),
):
    _enabled()
    return await service.recommendations(session, limit=limit, offset=offset)


@router.get("/consent-events", response_model=list[RegistryConsentEventOut])
async def get_consent_events(
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    _user=Depends(require_admin),
    session: AsyncSession = Depends(get_session),
):
    _enabled()
    return await service.consent_events(session, limit=limit, offset=offset)


@router.get("/connections", response_model=list[RegistryConnectionStatus])
async def get_connections(_user=Depends(require_admin)):
    _enabled()
    return service.connection_statuses()


@router.get("/reengagement/summary", response_model=ReengagementPoolSummary)
async def get_reengagement_summary(
    recent_window_days: int = Query(30, ge=1, le=365),
    _user=Depends(require_admin),
    session: AsyncSession = Depends(get_session),
):
    _enabled()
    return await reengagement.summary(session, recent_window_days=recent_window_days)


@router.get("/reengagement/pool", response_model=list[ReengagementPoolRow])
async def get_reengagement_pool(
    view: str = Query("eligible", pattern="^(eligible|needs_review|do_not_touch|excluded)$"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    source: str | None = Query(None, max_length=128),
    risk: str | None = Query(None, max_length=128),
    bucket: str | None = Query(None, max_length=256),
    source_ref: str | None = Query(None, max_length=256),
    recent_window_days: int = Query(30, ge=1, le=365),
    sort: str = Query("rank", pattern="^(rank|latest|name)$"),
    _user=Depends(require_admin),
    session: AsyncSession = Depends(get_session),
):
    _enabled()
    return await reengagement.pool(
        session,
        view=view,
        limit=limit,
        offset=offset,
        source=source,
        risk=risk,
        bucket=bucket,
        source_ref=source_ref,
        recent_window_days=recent_window_days,
        sort=sort,
    )


@router.post("/reengagement/campaign-preview", response_model=ReengagementCampaignPreview)
async def preview_reengagement_campaign(
    payload: ReengagementCampaignPreviewRequest,
    _user=Depends(require_admin),
    session: AsyncSession = Depends(get_session),
):
    _enabled()
    try:
        return await reengagement.campaign_preview(session, **payload.model_dump())
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))


@router.post("/reengagement/export")
async def export_reengagement_campaign(
    payload: ReengagementCampaignPreviewRequest,
    _user=Depends(require_admin),
    session: AsyncSession = Depends(get_session),
):
    _enabled()
    try:
        rows, preview = await reengagement.export_rows(session, **payload.model_dump())
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))

    out = io.StringIO()
    fieldnames = [
        "first_name",
        "last_name",
        "phone",
        "email",
        "close_lead_id",
        "ghl_contact_id",
        "source",
        "proposed_tag",
        "channel_mode",
        "batch_source_reference",
    ]
    writer = csv.DictWriter(out, fieldnames=fieldnames)
    writer.writeheader()
    writer.writerows(rows)
    filename = f"lead_reengagement_{preview['proposed_tag']}_{preview['selected_count']}.csv"
    return Response(
        content=out.getvalue(),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/lead-hygiene-reports", response_model=list[RegistryLeadHygieneReportOut])
async def get_lead_hygiene_reports(
    limit: int = Query(50, ge=1, le=100),
    _user=Depends(require_admin),
    session: AsyncSession = Depends(get_session),
):
    _enabled()
    return await service.list_lead_hygiene_reports(session, limit=limit)


@router.post("/imports/lead-hygiene/{job_id}", response_model=RegistryImportSummary)
async def import_lead_hygiene(
    job_id: str,
    _user=Depends(require_admin),
    session: AsyncSession = Depends(get_session),
):
    _enabled()
    try:
        counters = await service.import_lead_hygiene_report(session, job_id=job_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    return service.import_summary_dict(counters)


@router.post("/imports/source/{source}")
async def import_source_shell(source: str, _user=Depends(require_admin)):
    _enabled()
    if source not in {"close", "ghl", "notion"}:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Unknown source.")
    raise HTTPException(
        status_code=status.HTTP_501_NOT_IMPLEMENTED,
        detail=f"{source} live import is review-only shell in Registry v1. No external writes are available.",
    )
