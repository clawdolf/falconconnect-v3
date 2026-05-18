"""End-to-end fixture test: run the full audit against bundled data."""

import csv
import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from services.lead_hygiene_collect import run_audit_from_fixtures


FIXED_NOW = datetime(2026, 5, 18, 12, 0, tzinfo=timezone.utc)


def test_fixture_audit_produces_expected_buckets(tmp_path: Path):
    out = run_audit_from_fixtures(
        out_dir=tmp_path,
        now=FIXED_NOW,
        recent_window_days=30,
    )

    assert out["csv_path"].exists()
    assert out["json_path"].exists()

    by_lead = {}
    with out["csv_path"].open() as fh:
        reader = csv.DictReader(fh)
        for row in reader:
            by_lead[row["close_lead_id"]] = row

    # Hard-stop SMS → do-not-contact
    assert by_lead["lead_dnc_1"]["recommended_bucket"] == "do-not-contact"
    assert "stop_language" in by_lead["lead_dnc_1"]["risk_flags"]

    # Close status Not Interested → not-interested
    assert by_lead["lead_not_interested_1"]["recommended_bucket"] == "not-interested"

    # Close status Client → client
    assert by_lead["lead_client_1"]["recommended_bucket"] == "client"

    # Close status Invalid → invalid
    assert by_lead["lead_invalid_1"]["recommended_bucket"] == "invalid"

    # No phone → missing-phone
    assert by_lead["lead_missing_phone_1"]["recommended_bucket"] == "missing-phone"

    # Outbound call within window → recently-contacted
    assert by_lead["lead_recent_1"]["recommended_bucket"] == "recently-contacted"

    # Appointment evidence → needs-review (no auto-rvm)
    assert by_lead["lead_appointment_1"]["recommended_bucket"] == "needs-review"

    # Voicemail w/ old touch + no hard stop → reengage-ready
    assert by_lead["lead_reengage_1"]["recommended_bucket"] == "reengage-ready"
    assert "rvm-staging" in by_lead["lead_reengage_1"]["recommended_ghl_tags"]
    assert "rvm-pending" not in by_lead["lead_reengage_1"]["recommended_ghl_tags"]

    # GHL automation tag → already-automated
    assert by_lead["lead_already_automated_1"]["recommended_bucket"] == "already-automated"

    # Two leads sharing one phone → duplicate
    assert by_lead["lead_duplicate_phone_a"]["recommended_bucket"] == "duplicate"
    assert by_lead["lead_duplicate_phone_b"]["recommended_bucket"] == "duplicate"


def test_fixture_audit_summary_counts(tmp_path: Path):
    out = run_audit_from_fixtures(out_dir=tmp_path, now=FIXED_NOW)
    summary = out["summary"]
    assert summary["total"] == 11
    assert summary["by_bucket"]["do-not-contact"] >= 1
    assert summary["by_bucket"]["duplicate"] == 2


def test_no_recommendation_ever_contains_rvm_pending(tmp_path: Path):
    out = run_audit_from_fixtures(out_dir=tmp_path, now=FIXED_NOW)
    data = json.loads(out["json_path"].read_text())
    for row in data["rows"]:
        assert "rvm-pending" not in (row.get("recommended_ghl_tags") or []), (
            f"Lead {row['close_lead_id']} got rvm-pending recommendation"
        )


def test_notion_link_resolved_for_matching_records(tmp_path: Path):
    """Alice exists in Close + GHL + Notion — all IDs should populate."""
    out = run_audit_from_fixtures(out_dir=tmp_path, now=FIXED_NOW)
    data = json.loads(out["json_path"].read_text())
    alice = next(r for r in data["rows"] if r["close_lead_id"] == "lead_dnc_1")
    assert alice["ghl_contact_id"] == "ghl_alice"
    assert alice["notion_page_id"] == "page_alice"
