"""Research Engine endpoints — dashboard for FalconLeads research loop.

Core data (cycles, hypotheses, ads) lives in PostgreSQL (synced from
Mac Mini SQLite via POST /sync). DAG, playbook, and performance split
still read from local SQLite for now.

Trigger endpoints use PostgreSQL so the dashboard can queue cycles
from Render while the Mac Mini poller reads them back.
"""

import os
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Body, Depends, Header, HTTPException, Query
from sqlalchemy import select, func as sa_func
from sqlalchemy.ext.asyncio import AsyncSession

from db.database import get_session
from db.models import (
    ResearchTrigger,
    ResearchCycle,
    ResearchHypothesis,
    ResearchAd,
)
from middleware.auth import require_auth

router = APIRouter()

# ── DB path — env var override for Render, fallback to Mac dev path ──────────
_FALCONLEADS_BASE = Path(
    os.environ.get("FALCONLEADS_BASE", "/Users/clawdolf/.openclaw/workspace/falconleads")
)
_DB_PATH = Path(
    os.environ.get("FALCONLEADS_DB_PATH", str(_FALCONLEADS_BASE / "data" / "falcon_campaigns.db"))
)
_PLAYBOOK_PATH = Path(
    os.environ.get("FALCONLEADS_PLAYBOOK_PATH", str(_FALCONLEADS_BASE / "research_loop" / "playbook.md"))
)


def _get_conn() -> sqlite3.Connection:
    """Get a read-only SQLite connection to the falconleads DB."""
    db_path = _DB_PATH
    if not db_path.exists():
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        return conn
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def _get_write_conn() -> sqlite3.Connection:
    """Get a writable SQLite connection."""
    db_path = _DB_PATH
    try:
        db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(db_path))
    except (PermissionError, OSError):
        db_path = Path("/tmp/falconleads_triggers.db")
        conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def _safe_query(conn, sql, params=(), fetchone=False):
    """Execute a query, returning empty list/None if table doesn't exist."""
    try:
        cursor = conn.execute(sql, params)
        if fetchone:
            return cursor.fetchone()
        return cursor.fetchall()
    except sqlite3.OperationalError as e:
        if "no such table" in str(e):
            return None if fetchone else []
        raise


def _row_to_dict(row):
    if row is None:
        return None
    return dict(row)


def _rows_to_dicts(rows):
    return [dict(r) for r in rows] if rows else []


def _verify_loop_token(x_loop_token: Optional[str]) -> None:
    """Verify X-Loop-Token header against LOOP_SERVICE_TOKEN env var."""
    expected = os.environ.get("LOOP_SERVICE_TOKEN", "")
    if not expected or x_loop_token != expected:
        raise HTTPException(status_code=401, detail="Invalid loop token.")


# ══════════════════════════════════════════════════════════════════════════════
#  SYNC — Mac Mini pushes cycle results to PostgreSQL
# ══════════════════════════════════════════════════════════════════════════════

@router.post("/sync")
async def sync_cycle_results(
    body: dict = Body(...),
    x_loop_token: str = Header(None, alias="X-Loop-Token"),
    session: AsyncSession = Depends(get_session),
):
    """Called by Mac Mini loop after each cycle. Pushes SQLite results to PostgreSQL."""
    _verify_loop_token(x_loop_token)

    cycle_id = body.get("cycle_id")
    if not cycle_id:
        raise HTTPException(status_code=400, detail="cycle_id required.")

    # Upsert cycle record
    result = await session.execute(
        select(ResearchCycle).where(ResearchCycle.cycle_id == cycle_id)
    )
    cycle = result.scalar_one_or_none()
    if not cycle:
        cycle = ResearchCycle(
            cycle_id=cycle_id,
            ads_generated=body.get("ads_generated", 0),
            mutations_generated=body.get("mutations_generated", 0),
            hypotheses_formed=body.get("hypotheses_formed", 0),
            analysis_summary=body.get("analysis_summary"),
            status="complete",
        )
        session.add(cycle)

    # Insert hypotheses
    for h in body.get("hypotheses", []):
        hyp = ResearchHypothesis(
            cycle_id=cycle_id,
            hypothesis_text=h.get("text"),
            account_type=h.get("account_type", "both"),
            status=h.get("status", "proposed"),
            confidence=h.get("confidence", 0.5),
        )
        session.add(hyp)

    # Insert ads
    inserted_ads = 0
    for ad in body.get("ads", []):
        new_ad = ResearchAd(
            cycle_id=cycle_id,
            name=ad.get("name", ""),
            ad_copy=ad.get("ad_copy", ""),
            headline=ad.get("headline"),
            description=ad.get("description"),
            cta=ad.get("cta"),
            account_type=ad.get("account_type", "SAC"),
            status="pending_approval",
        )
        session.add(new_ad)
        inserted_ads += 1

    await session.flush()
    return {
        "synced": True,
        "cycle_id": cycle_id,
        "ads_inserted": inserted_ads,
        "hypotheses_inserted": len(body.get("hypotheses", [])),
    }


# ══════════════════════════════════════════════════════════════════════════════
#  STATUS — reads from PostgreSQL
# ══════════════════════════════════════════════════════════════════════════════

@router.get("/status")
async def research_status(
    session: AsyncSession = Depends(get_session),
    user=Depends(require_auth),
):
    """Return research loop status: last cycle, totals, next scheduled run."""

    # Last cycle from PostgreSQL
    last_cycle_result = await session.execute(
        select(ResearchCycle).order_by(ResearchCycle.created_at.desc()).limit(1)
    )
    last_cycle = last_cycle_result.scalar_one_or_none()

    # Total cycles
    cycles_count_result = await session.execute(
        select(sa_func.count(ResearchCycle.id))
    )
    cycles_total = cycles_count_result.scalar() or 0

    # Total ads generated across all cycles
    ads_total_result = await session.execute(
        select(sa_func.coalesce(sa_func.sum(ResearchCycle.ads_generated), 0))
    )
    ads_total = ads_total_result.scalar() or 0

    # Total hypotheses in PostgreSQL
    hypo_count_result = await session.execute(
        select(sa_func.count(ResearchHypothesis.id))
    )
    hypotheses_total = hypo_count_result.scalar() or 0

    # Total winners
    winners_result = await session.execute(
        select(sa_func.count(ResearchHypothesis.id)).where(
            ResearchHypothesis.status == "winner"
        )
    )
    winners_total = winners_result.scalar() or 0

    # Pending approval ads
    pending_ads_result = await session.execute(
        select(sa_func.count(ResearchAd.id)).where(
            ResearchAd.status == "pending_approval"
        )
    )
    pending_ads = pending_ads_result.scalar() or 0

    # Pending triggers count
    pending_triggers_result = await session.execute(
        select(sa_func.count(ResearchTrigger.id)).where(
            ResearchTrigger.status == "pending"
        )
    )
    pending_triggers = pending_triggers_result.scalar() or 0

    # Next Sunday midnight MST
    now = datetime.now()
    days_until_sunday = (6 - now.weekday()) % 7
    if days_until_sunday == 0:
        days_until_sunday = 7
    next_sunday = now.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=days_until_sunday)

    return {
        "last_cycle_id": last_cycle.cycle_id if last_cycle else None,
        "last_run": last_cycle.created_at.isoformat() if last_cycle and last_cycle.created_at else None,
        "next_run": next_sunday.isoformat(),
        "cycles_total": cycles_total,
        "ads_generated_total": ads_total,
        "mutations_generated_total": 0,
        "hypotheses_total": hypotheses_total,
        "winners_total": winners_total,
        "pending_ads": pending_ads,
        "pending_triggers": pending_triggers,
    }


# ══════════════════════════════════════════════════════════════════════════════
#  CYCLES — reads from PostgreSQL
# ══════════════════════════════════════════════════════════════════════════════

@router.get("/cycles")
async def research_cycles(
    limit: int = Query(10, ge=1, le=100),
    session: AsyncSession = Depends(get_session),
    user=Depends(require_auth),
):
    """Return last N research cycles from PostgreSQL."""
    result = await session.execute(
        select(ResearchCycle).order_by(ResearchCycle.created_at.desc()).limit(limit)
    )
    cycles = result.scalars().all()
    return {
        "cycles": [
            {
                "cycle_id": c.cycle_id,
                "ads_generated": c.ads_generated,
                "mutations_generated": c.mutations_generated,
                "hypotheses_formed": c.hypotheses_formed,
                "analysis_summary": c.analysis_summary,
                "status": c.status,
                "created_at": c.created_at.isoformat() if c.created_at else None,
            }
            for c in cycles
        ]
    }


# ══════════════════════════════════════════════════════════════════════════════
#  HYPOTHESES — reads from PostgreSQL
# ══════════════════════════════════════════════════════════════════════════════

@router.get("/hypotheses")
async def research_hypotheses(
    status: str = Query("all"),
    limit: int = Query(50, ge=1, le=200),
    session: AsyncSession = Depends(get_session),
    user=Depends(require_auth),
):
    """Return hypothesis log entries from PostgreSQL."""
    q = select(ResearchHypothesis).order_by(ResearchHypothesis.created_at.desc()).limit(limit)
    if status and status != "all":
        q = q.where(ResearchHypothesis.status == status)
    result = await session.execute(q)
    hyps = result.scalars().all()
    return {
        "hypotheses": [
            {
                "id": h.id,
                "cycle_id": h.cycle_id,
                "hypothesis_text": h.hypothesis_text,
                "account_type": h.account_type,
                "status": h.status,
                "confidence": h.confidence,
                "created_at": h.created_at.isoformat() if h.created_at else None,
            }
            for h in hyps
        ]
    }


# ══════════════════════════════════════════════════════════════════════════════
#  ADS — reads from PostgreSQL (approval queue)
# ══════════════════════════════════════════════════════════════════════════════

@router.get("/ads")
async def get_ads(
    status: Optional[str] = Query(None),
    account_type: Optional[str] = Query(None),
    session: AsyncSession = Depends(get_session),
    user=Depends(require_auth),
):
    """Return research ads from PostgreSQL, optionally filtered."""
    q = select(ResearchAd).order_by(ResearchAd.created_at.desc())
    if status:
        q = q.where(ResearchAd.status == status)
    if account_type:
        q = q.where(ResearchAd.account_type == account_type)
    result = await session.execute(q.limit(50))
    ads = result.scalars().all()
    return [
        {
            "id": a.id,
            "name": a.name,
            "ad_copy": a.ad_copy,
            "headline": a.headline,
            "description": a.description,
            "cta": a.cta,
            "account_type": a.account_type,
            "status": a.status,
            "created_at": a.created_at.isoformat() if a.created_at else None,
            "cycle_id": a.cycle_id,
        }
        for a in ads
    ]


# ══════════════════════════════════════════════════════════════════════════════
#  APPROVE / REJECT — writes to PostgreSQL
# ══════════════════════════════════════════════════════════════════════════════

@router.post("/ads/{ad_id}/approve")
async def approve_ad(
    ad_id: int,
    session: AsyncSession = Depends(get_session),
    user=Depends(require_auth),
):
    """Approve a research ad in PostgreSQL."""
    result = await session.execute(
        select(ResearchAd).where(ResearchAd.id == ad_id)
    )
    ad = result.scalar_one_or_none()
    if not ad:
        raise HTTPException(status_code=404, detail="Ad not found.")

    ad.status = "approved"
    ad.approved_at = datetime.now(timezone.utc)
    await session.flush()
    return {
        "ad": {
            "id": ad.id,
            "name": ad.name,
            "ad_copy": ad.ad_copy,
            "headline": ad.headline,
            "description": ad.description,
            "cta": ad.cta,
            "account_type": ad.account_type,
            "status": ad.status,
            "approved_at": ad.approved_at.isoformat() if ad.approved_at else None,
            "created_at": ad.created_at.isoformat() if ad.created_at else None,
        }
    }


@router.post("/ads/{ad_id}/reject")
async def reject_ad(
    ad_id: int,
    session: AsyncSession = Depends(get_session),
    user=Depends(require_auth),
):
    """Reject a research ad in PostgreSQL."""
    result = await session.execute(
        select(ResearchAd).where(ResearchAd.id == ad_id)
    )
    ad = result.scalar_one_or_none()
    if not ad:
        raise HTTPException(status_code=404, detail="Ad not found.")

    ad.status = "rejected"
    ad.rejected_at = datetime.now(timezone.utc)
    await session.flush()
    return {
        "ad": {
            "id": ad.id,
            "name": ad.name,
            "status": ad.status,
            "rejected_at": ad.rejected_at.isoformat() if ad.rejected_at else None,
        }
    }


# ══════════════════════════════════════════════════════════════════════════════
#  MUTATIONS (pending) — still reads SQLite (legacy ads table)
# ══════════════════════════════════════════════════════════════════════════════

@router.get("/mutations/pending")
async def pending_mutations(user=Depends(require_auth)):
    """Return ads with status='pending_approval' from SQLite."""
    conn = _get_conn()
    try:
        rows = _safe_query(conn, """
            SELECT id, name, ad_copy, headline, description, cta,
                   account_type, variant, angle, hypothesis_id,
                   status, created_date as created_at
            FROM ads
            WHERE status = 'pending_approval'
            ORDER BY created_date DESC
        """)
        return {"pending": _rows_to_dicts(rows)}
    finally:
        conn.close()


# ══════════════════════════════════════════════════════════════════════════════
#  MUTATIONS APPROVE / REJECT — still writes SQLite (legacy ads table)
# ══════════════════════════════════════════════════════════════════════════════

@router.post("/mutations/{ad_id}/approve")
async def approve_mutation(
    ad_id: int,
    user=Depends(require_auth),
):
    """Set ad status to ACTIVE in SQLite (legacy)."""
    conn = _get_write_conn()
    try:
        ad = _safe_query(conn, "SELECT id, status FROM ads WHERE id = ?", (ad_id,), fetchone=True)
        if not ad:
            raise HTTPException(status_code=404, detail="Ad not found.")

        conn.execute("UPDATE ads SET status = 'ACTIVE', updated_at = CURRENT_TIMESTAMP WHERE id = ?", (ad_id,))
        conn.commit()

        updated = _safe_query(conn, """
            SELECT id, name, ad_copy, headline, description, cta,
                   account_type, status, created_date as created_at
            FROM ads WHERE id = ?
        """, (ad_id,), fetchone=True)
        return {"ad": _row_to_dict(updated)}
    finally:
        conn.close()


@router.post("/mutations/{ad_id}/reject")
async def reject_mutation(
    ad_id: int,
    user=Depends(require_auth),
):
    """Set ad status to rejected in SQLite (legacy)."""
    conn = _get_write_conn()
    try:
        ad = _safe_query(conn, "SELECT id, status FROM ads WHERE id = ?", (ad_id,), fetchone=True)
        if not ad:
            raise HTTPException(status_code=404, detail="Ad not found.")

        conn.execute("UPDATE ads SET status = 'rejected', updated_at = CURRENT_TIMESTAMP WHERE id = ?", (ad_id,))
        conn.commit()

        updated = _safe_query(conn, """
            SELECT id, name, ad_copy, headline, description, cta,
                   account_type, status, created_date as created_at
            FROM ads WHERE id = ?
        """, (ad_id,), fetchone=True)
        return {"ad": _row_to_dict(updated)}
    finally:
        conn.close()


# ══════════════════════════════════════════════════════════════════════════════
#  DAG — still reads SQLite
# ══════════════════════════════════════════════════════════════════════════════

@router.get("/dag/nodes")
async def dag_nodes(
    domain: str = Query("all"),
    type: str = Query("all"),
    limit: int = Query(50, ge=1, le=200),
    user=Depends(require_auth),
):
    """Return DAG nodes, optionally filtered by domain and type."""
    conn = _get_conn()
    try:
        conditions = []
        params = []
        if domain and domain != "all":
            conditions.append("domain = ?")
            params.append(domain)
        if type and type != "all":
            conditions.append("type = ?")
            params.append(type)

        where_clause = "WHERE " + " AND ".join(conditions) if conditions else ""
        params.append(limit)

        rows = _safe_query(conn, f"""
            SELECT id, type, domain, content, metric_value, metric_name,
                   created_at, cycle_id
            FROM dag_nodes
            {where_clause}
            ORDER BY created_at DESC
            LIMIT ?
        """, tuple(params))
        return {"nodes": _rows_to_dicts(rows)}
    finally:
        conn.close()


@router.get("/dag/lineage/{node_id}")
async def dag_lineage(
    node_id: str,
    user=Depends(require_auth),
):
    """Traverse DAG edges backward up to depth 5. Return lineage chain."""
    conn = _get_conn()
    try:
        start_node = _safe_query(conn, """
            SELECT id, type, domain, content, metric_value, metric_name,
                   created_at, cycle_id
            FROM dag_nodes WHERE id = ?
        """, (node_id,), fetchone=True)

        if not start_node:
            return {"lineage": [], "node": None}

        lineage = [_row_to_dict(start_node)]
        current_ids = [node_id]
        visited = {node_id}

        for _ in range(5):
            if not current_ids:
                break
            placeholders = ",".join("?" * len(current_ids))
            edges = _safe_query(conn, f"""
                SELECT from_node, relationship FROM dag_edges
                WHERE to_node IN ({placeholders})
            """, tuple(current_ids))

            if not edges:
                break

            next_ids = []
            for edge in edges:
                parent_id = dict(edge)["from_node"]
                if parent_id not in visited:
                    visited.add(parent_id)
                    next_ids.append(parent_id)

            if next_ids:
                placeholders = ",".join("?" * len(next_ids))
                nodes = _safe_query(conn, f"""
                    SELECT id, type, domain, content, metric_value, metric_name,
                           created_at, cycle_id
                    FROM dag_nodes WHERE id IN ({placeholders})
                """, tuple(next_ids))
                for n in nodes:
                    d = _row_to_dict(n)
                    for edge in edges:
                        ed = dict(edge)
                        if ed["from_node"] == d["id"]:
                            d["relationship"] = ed["relationship"]
                            break
                    lineage.append(d)

            current_ids = next_ids

        return {"lineage": lineage, "node": _row_to_dict(start_node)}
    finally:
        conn.close()


@router.get("/dag/syntheses")
async def dag_syntheses(
    limit: int = Query(10, ge=1, le=50),
    user=Depends(require_auth),
):
    """Return DAG cross-domain syntheses."""
    conn = _get_conn()
    try:
        rows = _safe_query(conn, """
            SELECT id, synthesis_text, node_ids_used, created_at, cycle_id
            FROM dag_syntheses
            ORDER BY created_at DESC
            LIMIT ?
        """, (limit,))
        return {"syntheses": _rows_to_dicts(rows)}
    finally:
        conn.close()


# ══════════════════════════════════════════════════════════════════════════════
#  PLAYBOOK — reads from disk
# ══════════════════════════════════════════════════════════════════════════════

@router.get("/playbook")
async def research_playbook(user=Depends(require_auth)):
    """Read playbook.md from disk. Return content + metadata."""
    try:
        if _PLAYBOOK_PATH.exists():
            content = _PLAYBOOK_PATH.read_text()
            mtime = datetime.fromtimestamp(_PLAYBOOK_PATH.stat().st_mtime)
            rules_count = sum(1 for line in content.split("\n") if line.strip().startswith("RULE:"))
            return {
                "content": content,
                "last_updated": mtime.isoformat(),
                "rules_count": rules_count,
            }
        else:
            return {"content": "", "last_updated": None, "rules_count": 0}
    except Exception:
        return {"content": "", "last_updated": None, "rules_count": 0}


# ══════════════════════════════════════════════════════════════════════════════
#  PERFORMANCE SPLIT — still reads SQLite
# ══════════════════════════════════════════════════════════════════════════════

@router.get("/performance/split")
async def performance_split(user=Depends(require_auth)):
    """Return SAC vs NONSAC performance split."""
    conn = _get_conn()
    try:
        result = {}
        for account_type in ("sac", "nonsac"):
            row = _safe_query(conn, """
                SELECT
                    COALESCE(SUM(p.spend), 0) as total_spend,
                    COALESCE(SUM(p.leads), 0) as total_leads,
                    CASE WHEN SUM(p.leads) > 0
                         THEN ROUND(SUM(p.spend) / SUM(p.leads), 2)
                         ELSE 0 END as avg_cpl,
                    COUNT(DISTINCT a.id) as active_ads
                FROM ads a
                LEFT JOIN performance_daily p ON a.meta_ad_id = p.ad_id
                WHERE a.account_type = ? AND a.status = 'ACTIVE'
            """, (account_type,), fetchone=True)

            angle_row = _safe_query(conn, """
                SELECT a.angle, SUM(p.leads) as total_leads
                FROM ads a
                LEFT JOIN performance_daily p ON a.meta_ad_id = p.ad_id
                WHERE a.account_type = ? AND a.status = 'ACTIVE'
                GROUP BY a.angle
                ORDER BY total_leads DESC
                LIMIT 1
            """, (account_type,), fetchone=True)

            rd = _row_to_dict(row) if row else {}
            result[account_type] = {
                "total_spend": rd.get("total_spend", 0),
                "total_leads": rd.get("total_leads", 0),
                "avg_cpl": rd.get("avg_cpl", 0),
                "active_ads": rd.get("active_ads", 0),
                "top_angle": _row_to_dict(angle_row).get("angle", "—") if angle_row else "—",
            }
        return result
    finally:
        conn.close()


# ══════════════════════════════════════════════════════════════════════════════
#  TRIGGER — PostgreSQL queue for dashboard → Mac Mini
# ══════════════════════════════════════════════════════════════════════════════

@router.post("/cycle/trigger")
async def trigger_cycle(
    session: AsyncSession = Depends(get_session),
    user=Depends(require_auth),
):
    """Queue a research cycle by writing to PostgreSQL. The local Mac Mini polls this."""
    user_id = user.get("user_id", user.get("sub", "dashboard")) if isinstance(user, dict) else str(user)
    trigger = ResearchTrigger(triggered_by=user_id, status="pending")
    session.add(trigger)
    await session.flush()
    return {
        "triggered": True,
        "trigger_id": trigger.id,
        "message": "Cycle queued. The research engine will pick this up within 5 minutes.",
    }


@router.get("/triggers/pending")
async def get_pending_triggers(
    x_loop_token: str = Header(None, alias="X-Loop-Token"),
    session: AsyncSession = Depends(get_session),
):
    """Called by the local research loop to check for pending triggers."""
    _verify_loop_token(x_loop_token)

    result = await session.execute(
        select(ResearchTrigger)
        .where(ResearchTrigger.status == "pending")
        .order_by(ResearchTrigger.triggered_at.asc())
        .limit(1)
    )
    trigger = result.scalar_one_or_none()
    if not trigger:
        return {"pending": False}
    return {
        "pending": True,
        "trigger_id": trigger.id,
        "triggered_at": trigger.triggered_at.isoformat() if trigger.triggered_at else None,
    }


@router.post("/triggers/{trigger_id}/consume")
async def consume_trigger(
    trigger_id: int,
    body: dict = Body(default={}),
    x_loop_token: str = Header(None, alias="X-Loop-Token"),
    session: AsyncSession = Depends(get_session),
):
    """Called by the local loop after successfully running a cycle."""
    _verify_loop_token(x_loop_token)

    result = await session.execute(
        select(ResearchTrigger).where(ResearchTrigger.id == trigger_id)
    )
    trigger = result.scalar_one_or_none()
    if not trigger:
        raise HTTPException(status_code=404, detail="Trigger not found.")

    trigger.status = "consumed"
    trigger.consumed_at = datetime.now(timezone.utc)
    trigger.cycle_id = body.get("cycle_id")
    return {"consumed": True, "trigger_id": trigger_id}
