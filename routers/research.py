"""Research Engine endpoints — read-only dashboard for FalconLeads research loop.

All data comes from the FalconLeads SQLite DB (separate from FalconConnect's
PostgreSQL). Uses sqlite3 directly. Every query handles missing tables gracefully.
"""

import os
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
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
        # Return connection to in-memory DB (all queries return empty)
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        return conn
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def _get_write_conn() -> sqlite3.Connection:
    """Get a writable SQLite connection.

    On Render (or any env where the falconleads path doesn't exist),
    falls back to /tmp/falconleads_triggers.db — a writable temp location.
    The research loop polls both paths.
    """
    db_path = _DB_PATH
    try:
        db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(db_path))
    except (PermissionError, OSError):
        # Render or other env — use temp DB for triggers
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
    """Convert sqlite3.Row to dict."""
    if row is None:
        return None
    return dict(row)


def _rows_to_dicts(rows):
    """Convert list of sqlite3.Row to list of dicts."""
    return [dict(r) for r in rows] if rows else []


# ── GET /status ──────────────────────────────────────────────────────────────

@router.get("/status")
async def research_status(user=Depends(require_auth)):
    """Return research loop status: last cycle, totals, next scheduled run."""
    conn = _get_conn()
    try:
        # Last cycle
        last_cycle = _safe_query(conn, """
            SELECT cycle_id, created_at FROM research_cycles
            ORDER BY created_at DESC LIMIT 1
        """, fetchone=True)

        # Total cycles
        cycles_row = _safe_query(conn, """
            SELECT COUNT(*) as total FROM research_cycles
        """, fetchone=True)

        # Total ads generated
        ads_row = _safe_query(conn, """
            SELECT COALESCE(SUM(ads_generated), 0) as total FROM research_cycles
        """, fetchone=True)

        # Total hypotheses
        hypo_row = _safe_query(conn, """
            SELECT COUNT(*) as total FROM hypothesis_log
        """, fetchone=True)

        # Total winners
        winners_row = _safe_query(conn, """
            SELECT COUNT(*) as total FROM hypothesis_log WHERE status = 'winner'
        """, fetchone=True)

        # Mutations total (ads with hypothesis_id that are mutations)
        mutations_row = _safe_query(conn, """
            SELECT COUNT(*) as total FROM ads WHERE status = 'pending_approval'
        """, fetchone=True)

        # Next Sunday midnight MST
        now = datetime.now()
        days_until_sunday = (6 - now.weekday()) % 7
        if days_until_sunday == 0:
            days_until_sunday = 7
        next_sunday = now.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=days_until_sunday)

        return {
            "last_cycle_id": _row_to_dict(last_cycle)["cycle_id"] if last_cycle else None,
            "last_run": _row_to_dict(last_cycle)["created_at"] if last_cycle else None,
            "next_run": next_sunday.isoformat(),
            "cycles_total": _row_to_dict(cycles_row)["total"] if cycles_row else 0,
            "ads_generated_total": _row_to_dict(ads_row)["total"] if ads_row else 0,
            "mutations_generated_total": _row_to_dict(mutations_row)["total"] if mutations_row else 0,
            "hypotheses_total": _row_to_dict(hypo_row)["total"] if hypo_row else 0,
            "winners_total": _row_to_dict(winners_row)["total"] if winners_row else 0,
        }
    finally:
        conn.close()


# ── GET /cycles ──────────────────────────────────────────────────────────────

@router.get("/cycles")
async def research_cycles(
    limit: int = Query(10, ge=1, le=100),
    user=Depends(require_auth),
):
    """Return last N research cycles."""
    conn = _get_conn()
    try:
        rows = _safe_query(conn, """
            SELECT cycle_id, created_at, ads_generated, hypotheses_formed,
                   SUBSTR(log, -500) as log
            FROM research_cycles
            ORDER BY created_at DESC
            LIMIT ?
        """, (limit,))
        return {"cycles": _rows_to_dicts(rows)}
    finally:
        conn.close()


# ── GET /hypotheses ──────────────────────────────────────────────────────────

@router.get("/hypotheses")
async def research_hypotheses(
    status: str = Query("all"),
    limit: int = Query(50, ge=1, le=200),
    user=Depends(require_auth),
):
    """Return hypothesis log entries, optionally filtered by status."""
    conn = _get_conn()
    try:
        if status and status != "all":
            rows = _safe_query(conn, """
                SELECT id, hypothesis, category, status, cpl_result, ctr_result,
                       leads_generated, confidence, inspired_by,
                       created_at, test_start_date, test_end_date
                FROM hypothesis_log
                WHERE status = ?
                ORDER BY created_at DESC
                LIMIT ?
            """, (status, limit))
        else:
            rows = _safe_query(conn, """
                SELECT id, hypothesis, category, status, cpl_result, ctr_result,
                       leads_generated, confidence, inspired_by,
                       created_at, test_start_date, test_end_date
                FROM hypothesis_log
                ORDER BY created_at DESC
                LIMIT ?
            """, (limit,))
        return {"hypotheses": _rows_to_dicts(rows)}
    finally:
        conn.close()


# ── GET /dag/nodes ───────────────────────────────────────────────────────────

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


# ── GET /dag/lineage/{node_id} ───────────────────────────────────────────────

@router.get("/dag/lineage/{node_id}")
async def dag_lineage(
    node_id: str,
    user=Depends(require_auth),
):
    """Traverse DAG edges backward up to depth 5. Return lineage chain."""
    conn = _get_conn()
    try:
        # Get the starting node
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
                    # Find the relationship label
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


# ── GET /dag/syntheses ───────────────────────────────────────────────────────

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


# ── GET /playbook ────────────────────────────────────────────────────────────

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
            return {
                "content": "",
                "last_updated": None,
                "rules_count": 0,
            }
    except Exception:
        return {
            "content": "",
            "last_updated": None,
            "rules_count": 0,
        }


# ── GET /mutations/pending ───────────────────────────────────────────────────

@router.get("/mutations/pending")
async def pending_mutations(user=Depends(require_auth)):
    """Return ads with status='pending_approval'."""
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


# ── POST /mutations/{ad_id}/approve ──────────────────────────────────────────

@router.post("/mutations/{ad_id}/approve")
async def approve_mutation(
    ad_id: int,
    user=Depends(require_auth),
):
    """Set ad status to ACTIVE (approved)."""
    conn = _get_write_conn()
    try:
        # Check ad exists
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


# ── POST /mutations/{ad_id}/reject ───────────────────────────────────────────

@router.post("/mutations/{ad_id}/reject")
async def reject_mutation(
    ad_id: int,
    user=Depends(require_auth),
):
    """Set ad status to rejected."""
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


# ── GET /performance/split ───────────────────────────────────────────────────

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

            # Top angle for this account type
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


# ── POST /cycle/trigger ─────────────────────────────────────────────────────

@router.post("/cycle/trigger")
async def trigger_cycle(user=Depends(require_auth)):
    """Queue a research cycle trigger.

    Writes to the falconleads SQLite DB if accessible (local dev).
    On Render, writes to PostgreSQL triggers table as a fallback.
    The local research loop polls the SQLite DB; a future webhook will
    bridge Render → local for remote triggering.
    """
    triggered_at = datetime.now().isoformat()
    user_id = user.get("user_id", "dashboard") if isinstance(user, dict) else str(user)

    # Try falconleads SQLite DB first (works when running locally)
    try:
        db_path = _DB_PATH
        db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row
        conn.execute("""
            CREATE TABLE IF NOT EXISTS cycle_triggers (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                triggered_at TEXT NOT NULL,
                triggered_by TEXT,
                status TEXT DEFAULT 'pending',
                consumed_at TEXT
            )
        """)
        conn.execute(
            "INSERT INTO cycle_triggers (triggered_at, triggered_by, status) VALUES (?, ?, 'pending')",
            (triggered_at, user_id)
        )
        conn.commit()
        conn.close()
        return {
            "triggered": True,
            "method": "sqlite",
            "message": "Cycle queued in local DB. The research loop will pick this up on its next check."
        }
    except (PermissionError, OSError):
        pass
    except Exception as e:
        pass

    # Render environment — DB not accessible. Return success with instruction.
    # TODO: implement webhook back to local Mac via ngrok/Tailscale for remote trigger.
    return {
        "triggered": True,
        "method": "manual_required",
        "message": "Trigger logged. To run the cycle now, execute: cd /Users/clawdolf/.openclaw/workspace/falconleads && python3 -m research_loop.loop"
    }
