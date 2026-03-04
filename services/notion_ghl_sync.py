"""Notion → GHL Appointment Poll Sync.

Background loop that polls Notion every N seconds for recently modified
leads with appointment dates and pushes new/changed appointments to GHL.

Features:
  - DRY_RUN mode: logs what WOULD happen, makes no GHL calls
  - SYNC_AFTER_DATE filter: only syncs appointments on or after this date
  - 6-minute overlap buffer for the poll window (catches edits between cycles)
  - Manual dry-run endpoint returns 30-day lookahead

Configuration (env vars):
  NOTION_GHL_SYNC_ENABLED=true       # Master on/off switch
  NOTION_GHL_SYNC_DRY_RUN=true       # Log-only mode (no GHL writes)
  NOTION_GHL_SYNC_AFTER_DATE=2026-03-03  # Only sync appointments >= this date
  NOTION_GHL_SYNC_INTERVAL=300       # Seconds between polls (default 5 min)
"""

import asyncio
import json
import logging
from datetime import date, datetime, timezone
from typing import Any, Dict, List, Optional

from config import get_settings
from services import ghl, notion

logger = logging.getLogger("falconconnect.sync.notion_ghl")


def _extract_page_data(page: Dict[str, Any]) -> Dict[str, Any]:
    """Extract structured data from a Notion page object.

    Returns a dict with id, name, phone, appointment_date, or None values
    for missing fields.
    """
    props = page.get("properties", {})

    # Name (title)
    name_items = props.get("Name", {}).get("title", [])
    name = "".join(item.get("plain_text", "") for item in name_items) if name_items else ""

    # Phone (phone_number)
    phone = props.get("Mobile Phone", {}).get("phone_number", "") or ""

    # Appointment Date (date)
    appt_date_obj = props.get("Appointment Date", {}).get("date")
    appt_date = appt_date_obj.get("start", "") if appt_date_obj else ""

    # GHL Contact ID from Aggregate Comments (contains "GHL:<id>")
    comments_items = props.get("Aggregate Comments", {}).get("rich_text", [])
    comments = "".join(item.get("plain_text", "") for item in comments_items) if comments_items else ""
    ghl_contact_id = ""
    if "GHL:" in comments:
        ghl_contact_id = comments.split("GHL:")[1].split("|")[0].split(" ")[0].strip()

    return {
        "id": page.get("id", ""),
        "name": name,
        "phone": phone,
        "appointment_date": appt_date,
        "ghl_contact_id": ghl_contact_id,
        "last_edited": page.get("last_edited_time", ""),
    }


async def run_notion_ghl_sync(
    force_dry_run: bool = False,
    lookahead_days: Optional[int] = None,
) -> List[Dict[str, Any]]:
    """Poll Notion for recently modified records with appointment dates.

    Push new/changed appointments to GHL.
    Respects DRY_RUN and SYNC_AFTER_DATE settings.

    Args:
        force_dry_run: If True, forces dry-run mode regardless of settings.
        lookahead_days: If set, queries upcoming N days instead of recent changes.

    Returns a list of result dicts for each processed appointment.
    """
    settings = get_settings()

    if not settings.notion_ghl_sync_enabled:
        logger.debug("Notion→GHL sync is disabled")
        return []

    dry_run = settings.notion_ghl_sync_dry_run or force_dry_run

    # Determine which pages to process
    if lookahead_days:
        # Manual trigger — get upcoming appointments for the next N days
        pages_raw = await notion.get_upcoming_appointments(days=lookahead_days)
    else:
        # Background poll — get recently modified pages with appointments
        pages_raw = await notion.poll_recent_changes(minutes=6)

    if not pages_raw:
        logger.debug("No pages to process")
        return []

    results: List[Dict[str, Any]] = []

    for page_raw in pages_raw:
        page = _extract_page_data(page_raw)

        appt_date_str = page["appointment_date"]
        if not appt_date_str:
            continue

        # Apply date filter
        if settings.notion_ghl_sync_after_date:
            try:
                cutoff = date.fromisoformat(settings.notion_ghl_sync_after_date)
                appt_d = date.fromisoformat(appt_date_str[:10])
                if appt_d < cutoff:
                    logger.debug(
                        "Skipping %s — appointment %s before cutoff %s",
                        page["name"], appt_date_str, cutoff,
                    )
                    continue
            except ValueError:
                logger.warning("Invalid date format: %s", appt_date_str)
                continue

        result: Dict[str, Any] = {
            "notion_page_id": page["id"],
            "name": page["name"],
            "phone": page["phone"],
            "appointment_date": appt_date_str,
        }

        if dry_run:
            result["action"] = "would_create"
            result["dry_run"] = True
            logger.info(
                "[DRY RUN] Would push appointment to GHL: %s at %s",
                page["name"], appt_date_str,
            )
        else:
            # Find GHL contact ID — check extracted data first, then DB xref
            ghl_contact_id = page.get("ghl_contact_id", "")

            if not ghl_contact_id:
                # Try to find via DB xref
                try:
                    from db.database import _get_session_factory
                    from db.models import LeadXref
                    from sqlalchemy import select

                    async with _get_session_factory()() as session:
                        stmt = select(LeadXref).where(
                            LeadXref.notion_page_id == page["id"]
                        )
                        row = await session.execute(stmt)
                        xref = row.scalar_one_or_none()
                        if xref:
                            ghl_contact_id = xref.ghl_contact_id
                except Exception as e:
                    logger.warning("DB xref lookup failed: %s", e)

            if not ghl_contact_id:
                result["action"] = "skipped_no_xref"
                result["error"] = "No GHL contact ID found for this Notion page"
                results.append(result)
                continue

            try:
                appt_result = await ghl.upsert_appointment(
                    contact_id=ghl_contact_id,
                    start_time=appt_date_str,
                    title=f"Phone Appointment — {page['name']}",
                    calendar_id=settings.ghl_calendar_id,
                )
                result["action"] = "created"
                result["ghl_appointment_id"] = appt_result.get("id", "")
                result["ghl_contact_id"] = ghl_contact_id
            except Exception as e:
                result["action"] = "failed"
                result["error"] = str(e)
                logger.error(
                    "Failed to push appointment for %s: %s",
                    page["name"], e,
                )

        results.append(result)

    # Log summary
    if results:
        mode = "DRY RUN" if dry_run else "LIVE"
        logger.info(
            "[%s] Notion→GHL sync: %d appointments processed", mode, len(results)
        )
        for r in results:
            logger.info("  %s", r)

    return results


async def sync_loop():
    """Background loop — runs every NOTION_GHL_SYNC_INTERVAL seconds.

    Catches all exceptions to prevent the loop from dying.
    Logs errors and continues.
    """
    settings = get_settings()
    interval = settings.notion_ghl_sync_interval

    logger.info(
        "Notion→GHL sync loop starting (interval=%ds, dry_run=%s, after_date=%s)",
        interval,
        settings.notion_ghl_sync_dry_run,
        settings.notion_ghl_sync_after_date,
    )

    # Initial delay — let the app fully start up
    await asyncio.sleep(10)

    while True:
        try:
            await run_notion_ghl_sync()
        except asyncio.CancelledError:
            logger.info("Notion→GHL sync loop cancelled")
            break
        except Exception as e:
            logger.error("Notion→GHL sync error: %s", e, exc_info=True)

        await asyncio.sleep(interval)
