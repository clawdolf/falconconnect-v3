"""Analytics endpoints — daily production metrics."""

import logging
from datetime import date, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from db.database import get_session
from db.models import AnalyticsDaily
from middleware.auth import require_auth

logger = logging.getLogger("falconconnect.analytics")

router = APIRouter()


@router.get("/daily")
async def get_daily_analytics(
    start: Optional[date] = Query(None, description="Start date (YYYY-MM-DD)"),
    end: Optional[date] = Query(None, description="End date (YYYY-MM-DD)"),
    days: int = Query(30, ge=1, le=365, description="Number of days to look back"),
    session: AsyncSession = Depends(get_session),
    user=Depends(require_auth),
):
    """Get daily production metrics for a date range.

    Returns dials, contacts, appointments, closes, and premium data.
    Defaults to the last 30 days if no range is specified.
    """
    if not end:
        end = date.today()
    if not start:
        start = end - timedelta(days=days)

    result = await session.execute(
        select(AnalyticsDaily)
        .where(AnalyticsDaily.date >= start)
        .where(AnalyticsDaily.date <= end)
        .order_by(AnalyticsDaily.date.desc())
    )
    rows = result.scalars().all()

    return {
        "start": start.isoformat(),
        "end": end.isoformat(),
        "count": len(rows),
        "data": [
            {
                "date": row.date.isoformat(),
                "dials": row.dials,
                "contacts": row.contacts,
                "appointments_set": row.appointments_set,
                "appointments_kept": row.appointments_kept,
                "closes": row.closes,
                "premium_submitted": row.premium_submitted,
                "premium_issued": row.premium_issued,
                "notes": row.notes,
            }
            for row in rows
        ],
    }


@router.get("/summary")
async def get_summary(
    days: int = Query(30, ge=1, le=365),
    session: AsyncSession = Depends(get_session),
    user=Depends(require_auth),
):
    """Aggregated production summary for the last N days.

    Returns totals and averages for key metrics.
    """
    start = date.today() - timedelta(days=days)

    result = await session.execute(
        select(AnalyticsDaily)
        .where(AnalyticsDaily.date >= start)
    )
    rows = result.scalars().all()

    if not rows:
        return {
            "period_days": days,
            "data_days": 0,
            "totals": {},
            "averages": {},
        }

    n = len(rows)
    totals = {
        "dials": sum(r.dials for r in rows),
        "contacts": sum(r.contacts for r in rows),
        "appointments_set": sum(r.appointments_set for r in rows),
        "appointments_kept": sum(r.appointments_kept for r in rows),
        "closes": sum(r.closes for r in rows),
        "premium_submitted": sum(r.premium_submitted for r in rows),
        "premium_issued": sum(r.premium_issued for r in rows),
    }

    averages = {k: round(v / n, 1) for k, v in totals.items()}

    # Conversion rates
    rates = {}
    if totals["dials"] > 0:
        rates["contact_rate"] = round(totals["contacts"] / totals["dials"] * 100, 1)
    if totals["contacts"] > 0:
        rates["appt_rate"] = round(totals["appointments_set"] / totals["contacts"] * 100, 1)
    if totals["appointments_kept"] > 0:
        rates["close_rate"] = round(totals["closes"] / totals["appointments_kept"] * 100, 1)

    return {
        "period_days": days,
        "data_days": n,
        "totals": totals,
        "averages": averages,
        "rates": rates,
    }
