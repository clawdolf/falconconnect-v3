"""Notion → GHL Appointment Poll Sync.

Background loop that polls Notion every N seconds for recently modified
leads with appointment dates and pushes new/changed appointments to GHL.

Features:
  - DRY_RUN mode: logs what WOULD happen, makes no GHL calls
  - SYNC_AFTER_DATE filter: only syncs appointments on or after this date
  - 6-minute overlap buffer for the poll window (catches edits between cycles)
  - Manual dry-run endpoint returns 30-day lookahead
  - Bug 2 fix: DB audit trail via sync_log writes
  - Bug 4 fix: Cancellation propagation (detects removed Appointment Dates)
  - Bug 6 fix: Notion API rate limiting (334ms between operations)

Configuration (env vars):
  NOTION_GHL_SYNC_ENABLED=true       # Master on/off switch
  NOTION_GHL_SYNC_DRY_RUN=true       # Log-only mode (no GHL writes)
  NOTION_GHL_SYNC_AFTER_DATE=2026-03-03  # Only sync appointments >= this date
  NOTION_GHL_SYNC_INTERVAL=300       # Seconds between polls (default 5 min)
"""

import asyncio
import json
import logging
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from config import get_settings
from services import ghl, notion

logger = logging.getLogger("falconconnect.sync.notion_ghl")


async def _write_sync_log(
    event_type: str,
    direction: str = "notion_to_ghl",
    source_id: str = "",
    target_id: str = "",
    payload: Optional[Dict] = None,
    status: str = "ok",
    error_detail: Optional[str] = None,
) -> None:
    """Bug 2 fix: Write a row to sync_log for every background sync operation."""
    try:
        from db.database import _get_session_factory
        from db.models import SyncLog

        async with _get_session_factory()() as session:
            log = SyncLog(
                event_type=event_type,
                direction=direction,
                source_id=source_id or "",
                target_id=target_id or "",
                payload=json.dumps(payload, default=str) if payload else None,
                status=status,
                error_detail=error_detail,
            )
            session.add(log)
            await session.commit()
    except Exception as e:
        logger.warning("Failed to write sync_log: %s", e)


def _extract_phone(props: Dict[str, Any]) -> str:
    """Resolve the best phone number from a Notion page's properties.

    Priority:
    1. Read "Best Phone" select field (values: "Home", "Cell", "Spouse")
    2. Map to corresponding phone_number property:
       - "Home"   → "Home Phone"
       - "Cell"   → "Mobile Phone"
       - "Spouse" → "Spouse Phone"
    3. Fall back to "Mobile Phone" if Best Phone is unset or the mapped field is empty.
    """
    best_phone_select = props.get("Best Phone", {}).get("select") or {}
    best_phone_label = best_phone_select.get("name", "")

    phone_field_map = {
        "Home": "Home Phone",
        "Cell": "Mobile Phone",
        "Spouse": "Spouse Phone",
    }

    preferred_field = phone_field_map.get(best_phone_label, "Mobile Phone")
    phone = props.get(preferred_field, {}).get("phone_number", "") or ""

    # Fall back to Mobile Phone if preferred field is empty
    if not phone and preferred_field != "Mobile Phone":
        phone = props.get("Mobile Phone", {}).get("phone_number", "") or ""

    return phone


def _extract_page_data(page: Dict[str, Any]) -> Dict[str, Any]:
    """Extract structured data from a Notion page object.

    Returns a dict with id, name, phone, appointment_date, or None values
    for missing fields.
    """
    props = page.get("properties", {})

    # Name (title)
    name_items = props.get("Name", {}).get("title", [])
    name = "".join(item.get("plain_text", "") for item in name_items) if name_items else ""

    # Phone — resolve via "Best Phone" select field, fall back to Mobile Phone
    phone = _extract_phone(props)

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


async def _sync_timezone_if_changed(
    contact_id: str,
    page_props: Dict[str, Any],
) -> Optional[str]:
    """Sync timezone from Notion page to GHL contact if different.

    Reads State and ZIP Code from Notion page properties, determines timezone,
    and updates GHL if it differs from the current contact timezone.
    """
    try:
        # Extract state and zip from Notion props
        state_select = page_props.get("State", {}).get("select") or {}
        state = state_select.get("name", "")
        zip_items = page_props.get("ZIP Code", {}).get("rich_text", [])
        zip_code = "".join(item.get("plain_text", "") for item in zip_items) if zip_items else ""

        tz = ghl.get_timezone(zip_code, state)
        if not tz:
            return "skipped"

        contact = await ghl.get_contact_by_id(contact_id)
        if not contact:
            return "skipped"

        current_tz = contact.get("timezone", "")
        if current_tz == tz:
            return "match"

        import httpx
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.put(
                f"{ghl.GHL_BASE}/contacts/{contact_id}",
                headers=ghl._headers(),
                json={"timezone": tz},
            )
            resp.raise_for_status()
            logger.info("GHL timezone updated for %s: %s → %s", contact_id, current_tz, tz)
            return "updated"
    except Exception as e:
        logger.warning("Timezone sync failed for %s: %s", contact_id, e)
        return "error"


async def run_notion_ghl_sync(
    force_dry_run: bool = False,
    lookahead_days: Optional[int] = None,
) -> List[Dict[str, Any]]:
    """Poll Notion for recently modified records with appointment dates.

    Push new/changed appointments to GHL.
    Respects DRY_RUN and SYNC_AFTER_DATE settings.

    Bug 2 fix: Writes sync_log DB entries for every operation.
    Bug 4 fix: Also detects cancellations (removed Appointment Date).
    Bug 6 fix: Rate limits Notion API calls (334ms between operations).

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

        # Bug 4 fix: Also poll for recently modified pages WITHOUT appointments
        # (these may be cancellations — appointment date was removed)
        try:
            cancelled_pages = await notion.poll_recent_changes_no_appointment(minutes=6)
            if cancelled_pages:
                for cp in cancelled_pages:
                    cp["_cancelled"] = True
                pages_raw = list(pages_raw) + cancelled_pages
        except Exception as e:
            logger.warning("Failed to poll for cancellations: %s", e)

    if not pages_raw:
        logger.debug("No pages to process")
        return []

    results: List[Dict[str, Any]] = []

    for page_raw in pages_raw:
        page = _extract_page_data(page_raw)

        # Bug 4: Handle cancellations (pages that lost their Appointment Date)
        if page_raw.get("_cancelled"):
            result = await _handle_cancellation(page, dry_run)
            if result:
                results.append(result)
            # Bug 6: Rate limit between operations
            await asyncio.sleep(0.334)
            continue

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
            # In dry-run, report what phone would be used — don't touch GHL
            result["phone_used"] = page["phone"] or "(none)"
            logger.info(
                "[DRY RUN] Would push appointment to GHL: %s at %s (phone: %s)",
                page["name"], appt_date_str, page["phone"],
            )
            # Bug 2: Log dry-run to sync_log
            await _write_sync_log(
                event_type="appointment.dry_run",
                source_id=page["id"],
                payload=result,
                status="ok",
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
                # Bug 2: Log skip to sync_log
                await _write_sync_log(
                    event_type="appointment.sync",
                    source_id=page["id"],
                    payload=result,
                    status="skipped",
                    error_detail="No GHL contact ID (no xref)",
                )
                results.append(result)
                continue

            try:
                # Sync phone — update GHL primary phone if Notion best phone differs
                notion_phone = page.get("phone", "")
                phone_sync_result = await ghl.sync_phone_if_changed(
                    contact_id=ghl_contact_id,
                    notion_phone=notion_phone,
                )
                result["phone_sync"] = phone_sync_result
                if phone_sync_result == "updated":
                    logger.info(
                        "Phone updated in GHL for %s (contact %s) → %s",
                        page["name"], ghl_contact_id, notion_phone,
                    )
                    # Bug 2: Log phone update
                    await _write_sync_log(
                        event_type="phone.updated",
                        source_id=page["id"],
                        target_id=ghl_contact_id,
                        payload={"phone": notion_phone},
                        status="ok",
                    )

                # Sync timezone from Notion to GHL
                tz_result = await _sync_timezone_if_changed(
                    ghl_contact_id, page_raw.get("properties", {})
                )
                result["timezone_sync"] = tz_result

                # Push appointment (with upsert dedup — Bug 1 fix in ghl.py)
                appt_result = await ghl.upsert_appointment(
                    contact_id=ghl_contact_id,
                    start_time=appt_date_str,
                    title=f"Phone Appointment — {page['name']}",
                    calendar_id=settings.ghl_calendar_id,
                )
                result["action"] = "created"
                result["ghl_appointment_id"] = appt_result.get("id", "")
                result["ghl_contact_id"] = ghl_contact_id

                # Bug 2: Log successful appointment creation
                await _write_sync_log(
                    event_type="appointment.created",
                    source_id=page["id"],
                    target_id=f"ghl:{ghl_contact_id}|appt:{appt_result.get('id', '')}",
                    payload=result,
                    status="ok",
                )
            except Exception as e:
                result["action"] = "failed"
                result["error"] = str(e)
                logger.error(
                    "Failed to push appointment for %s: %s",
                    page["name"], e,
                )
                # Bug 2: Log failure
                await _write_sync_log(
                    event_type="appointment.sync",
                    source_id=page["id"],
                    target_id=ghl_contact_id,
                    payload=result,
                    status="error",
                    error_detail=str(e),
                )

        results.append(result)

        # Bug 6: Rate limit — 334ms between Notion operations (~3 req/s)
        await asyncio.sleep(0.334)

    # Log summary
    if results:
        mode = "DRY RUN" if dry_run else "LIVE"
        logger.info(
            "[%s] Notion→GHL sync: %d appointments processed", mode, len(results)
        )
        for r in results:
            logger.info("  %s", r)

    return results


async def _handle_cancellation(
    page: Dict[str, Any],
    dry_run: bool,
) -> Optional[Dict[str, Any]]:
    """Bug 4 fix: Handle pages that had Appointment Date removed (cancellation).

    Looks up the GHL contact and cancels their appointments.
    """
    result: Dict[str, Any] = {
        "notion_page_id": page["id"],
        "name": page["name"],
        "phone": page["phone"],
        "appointment_date": "(cancelled)",
    }

    ghl_contact_id = page.get("ghl_contact_id", "")
    if not ghl_contact_id:
        # Try DB xref
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
        except Exception:
            pass

    if not ghl_contact_id:
        result["action"] = "skipped_no_xref"
        return result

    if dry_run:
        result["action"] = "would_cancel"
        result["dry_run"] = True
        logger.info("[DRY RUN] Would cancel GHL appointments for %s", page["name"])
        return result

    try:
        settings = get_settings()
        existing = await ghl.get_contact_appointments(ghl_contact_id, settings.ghl_calendar_id)
        cancelled_count = 0
        for appt in existing:
            appt_status = (appt.get("appointmentStatus") or appt.get("status") or "").lower()
            if appt_status in ("cancelled", "deleted"):
                continue
            appt_id = appt.get("id", "")
            if appt_id:
                await ghl.cancel_appointment(appt_id)
                cancelled_count += 1

        result["action"] = "cancelled"
        result["cancelled_count"] = cancelled_count
        result["ghl_contact_id"] = ghl_contact_id

        await _write_sync_log(
            event_type="appointment.cancelled_from_notion",
            source_id=page["id"],
            target_id=ghl_contact_id,
            payload=result,
            status="ok",
        )

        logger.info(
            "Cancelled %d GHL appointments for %s (Notion date removed)",
            cancelled_count, page["name"],
        )
    except Exception as e:
        result["action"] = "cancel_failed"
        result["error"] = str(e)
        logger.error("Failed to cancel appointments for %s: %s", page["name"], e)
        await _write_sync_log(
            event_type="appointment.cancel_failed",
            source_id=page["id"],
            target_id=ghl_contact_id,
            payload=result,
            status="error",
            error_detail=str(e),
        )

    return result


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
