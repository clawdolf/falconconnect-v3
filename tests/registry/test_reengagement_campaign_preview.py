from __future__ import annotations

import csv
import importlib.util
import io
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from tests.registry.test_reengagement_pool import _rows
from tests.registry.test_registry import _install_report, _make_app, _run, _session_factory


HAS_AIOSQLITE = importlib.util.find_spec("aiosqlite") is not None


def _client(tmp_path, monkeypatch, *, user_id: str | None = "user_3ASrwDOrSTaDxCus6f1B5lnDsgz") -> TestClient:
    monkeypatch.setenv("CLERK_ADMIN_USER_ID", "user_3ASrwDOrSTaDxCus6f1B5lnDsgz")
    job_id = _install_report(tmp_path, monkeypatch, rows=_rows())
    sf = _run(_session_factory())
    client = TestClient(_make_app(sf, user_id=user_id))
    if user_id == "user_3ASrwDOrSTaDxCus6f1B5lnDsgz":
        res = client.post(f"/api/admin/registry/imports/lead-hygiene/{job_id}")
        assert res.status_code == 200, res.text
    return client


@pytest.mark.skipif(not HAS_AIOSQLITE, reason="aiosqlite is not installed")
def test_preview_enforces_cap_and_returns_exclusion_counts(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)

    too_large = client.post(
        "/api/admin/registry/reengagement/campaign-preview",
        json={"batch_size": 1001, "channel_mode": "sms_only"},
    )
    assert too_large.status_code == 422
    assert "batch_size" in too_large.text

    invalid_window = client.post(
        "/api/admin/registry/reengagement/campaign-preview",
        json={"recent_window_days": 0, "channel_mode": "sms_only"},
    )
    assert invalid_window.status_code == 422
    assert "recent_window_days" in invalid_window.text

    res = client.post(
        "/api/admin/registry/reengagement/campaign-preview",
        json={"batch_size": 50, "channel_mode": "sms_only", "sort": "rank"},
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["selected_count"] == 2
    assert body["total_eligible"] == 2
    assert body["rows"][0]["display_name"] == "Eligible Lead"
    assert {row["display_name"] for row in body["rows"]} == {"Eligible Lead", "Previous Outreach"}
    assert body["rows"][0]["masked_phone"].startswith("***-***-")
    assert body["channel_mode"] == "sms_only"
    assert body["proposed_tag"] == "reengage-staging"
    assert body["copy_preview"]["sms_opener"].startswith("Hey {first_name}")
    assert "CSV export contains exactly 2 leads" in body["confirmation_copy"]
    assert "will not send SMS" in body["confirmation_copy"]
    assert "update any external system" in body["confirmation_copy"]
    assert body["excluded_counts"]["hard_stop_or_do_not_touch"] >= 4
    assert body["excluded_counts"]["missing_phone"] >= 1
    assert body["excluded_counts"]["needs_review"] >= 2
    assert body["excluded_counts"]["inbound_response_detected"] >= 1
    assert body["excluded_counts"]["appointment_detected"] >= 1


@pytest.mark.skipif(not HAS_AIOSQLITE, reason="aiosqlite is not installed")
def test_channel_mode_changes_metadata_only(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    sms = client.post(
        "/api/admin/registry/reengagement/campaign-preview",
        json={"batch_size": 50, "channel_mode": "sms_only"},
    ).json()
    rvm = client.post(
        "/api/admin/registry/reengagement/campaign-preview",
        json={"batch_size": 50, "channel_mode": "rvm_only"},
    ).json()
    assert [row["household_id"] for row in sms["rows"]] == [row["household_id"] for row in rvm["rows"]]
    assert sms["channel_mode"] == "sms_only"
    assert rvm["channel_mode"] == "rvm_only"


@pytest.mark.skipif(not HAS_AIOSQLITE, reason="aiosqlite is not installed")
def test_export_contains_only_eligible_rows_and_staging_tag(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)

    res = client.post(
        "/api/admin/registry/reengagement/export",
        json={"batch_size": 50, "channel_mode": "sms_rvm"},
    )
    assert res.status_code == 200, res.text
    assert res.headers["content-type"].startswith("text/csv")
    rows = list(csv.DictReader(io.StringIO(res.text)))
    assert len(rows) == 2
    assert rows[0]["first_name"] == "Eligible"
    assert rows[0]["last_name"] == "Lead"
    assert rows[0]["phone"].endswith("0101")
    assert rows[0]["email"] == "eligible@example.com"
    assert rows[0]["close_lead_id"] == "lead_eligible"
    assert rows[0]["ghl_contact_id"] == "ghl_eligible"
    assert rows[0]["proposed_tag"] == "reengage-staging"
    assert rows[0]["channel_mode"] == "sms_rvm"
    assert rows[0]["eligibility_reason"] == "reengage-ready-never-responded"
    assert rows[0]["never_responded"] == "True"
    previous = next(row for row in rows if row["first_name"] == "Previous")
    assert previous["last_outbound_touch"]
    assert previous["last_inbound_touch"] == ""
    assert previous["last_appointment"] == ""
    assert previous["eligibility_reason"] == "old-outbound-never-responded"
    assert previous["never_responded"] == "True"
    assert "Dnc Lead" not in res.text
    assert "Inbound Responder" not in res.text
    assert "Appointment Lead" not in res.text


@pytest.mark.skipif(not HAS_AIOSQLITE, reason="aiosqlite is not installed")
def test_preview_and_export_are_admin_gated(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch, user_id="not_admin")
    preview = client.post("/api/admin/registry/reengagement/campaign-preview", json={})
    export = client.post("/api/admin/registry/reengagement/export", json={})
    assert preview.status_code == 403
    assert export.status_code == 403


def test_reengagement_service_static_read_only_boundary():
    source = Path("services/registry/reengagement.py").read_text()
    forbidden_imports = [
        "services.ghl",
        "services.close",
        "services.close_client",
        "services.twilio",
        "services.twilio_client",
    ]
    assert not any(item in source for item in forbidden_imports)
    for method in [".post(", ".put(", ".patch(", ".delete("]:
        assert method not in source
