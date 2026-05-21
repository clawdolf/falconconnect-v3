from __future__ import annotations

import importlib.util
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from tests.registry.test_registry import _install_report, _make_app, _run, _session_factory


HAS_AIOSQLITE = importlib.util.find_spec("aiosqlite") is not None


def _rows() -> list[dict]:
    recent = (datetime.now(timezone.utc) - timedelta(days=2)).isoformat()
    old = (datetime.now(timezone.utc) - timedelta(days=120)).isoformat()
    return [
        {
            "lead_name": "Eligible Lead",
            "phone": "4805550101",
            "email": "eligible@example.com",
            "close_lead_id": "lead_eligible",
            "ghl_contact_id": "ghl_eligible",
            "recommended_bucket": "reengage-ready",
            "risk_flags": [],
            "confidence": 0.91,
            "reason": "Old lead with no hard stop and no recent activity.",
        },
        {
            "lead_name": "No Phone",
            "phone": "",
            "email": "nophone@example.com",
            "recommended_bucket": "missing-phone",
            "risk_flags": ["missing_phone"],
            "confidence": 0.9,
            "reason": "No usable phone number on file.",
        },
        {
            "lead_name": "Duplicate Lead",
            "phone": "4805550102",
            "recommended_bucket": "duplicate",
            "risk_flags": ["duplicate_phone"],
            "confidence": 0.85,
            "reason": "Phone appears on multiple leads.",
        },
        {
            "lead_name": "Previous Outreach",
            "phone": "4805550103",
            "recommended_bucket": "previous-outreach-detected",
            "risk_flags": [],
            "last_outbound_touch": old,
            "confidence": 0.75,
            "reason": "Old outbound activity exists.",
        },
        {
            "lead_name": "Inbound Responder",
            "phone": "4805550110",
            "recommended_bucket": "previous-outreach-detected",
            "risk_flags": [],
            "last_outbound_touch": old,
            "last_inbound_touch": old,
            "confidence": 0.78,
            "reason": "Old outbound and inbound reply exists.",
        },
        {
            "lead_name": "Appointment Lead",
            "phone": "4805550111",
            "recommended_bucket": "previous-outreach-detected",
            "risk_flags": [],
            "last_outbound_touch": old,
            "last_appointment": old,
            "confidence": 0.77,
            "reason": "Appointment exists.",
        },
        {
            "lead_name": "Malformed Outreach",
            "phone": "4805550112",
            "recommended_bucket": "previous-outreach-detected",
            "risk_flags": [],
            "last_outbound_touch": "unknown",
            "confidence": 0.76,
            "reason": "Outbound activity date is malformed.",
        },
        {
            "lead_name": "Dnc Lead",
            "phone": "4805550104",
            "recommended_bucket": "do-not-contact",
            "risk_flags": ["hard_stop", "stop_language"],
            "confidence": 0.98,
            "reason": "STOP language found.",
        },
        {
            "lead_name": "Not Interested",
            "phone": "4805550105",
            "recommended_bucket": "not-interested",
            "risk_flags": ["not_interested_status"],
            "confidence": 0.9,
            "reason": "Status indicates not interested.",
        },
        {
            "lead_name": "Client Lead",
            "phone": "4805550106",
            "recommended_bucket": "client",
            "risk_flags": ["client_status"],
            "confidence": 0.95,
            "reason": "Existing client.",
        },
        {
            "lead_name": "Invalid Lead",
            "phone": "4805550107",
            "recommended_bucket": "invalid",
            "risk_flags": ["invalid_status"],
            "confidence": 0.95,
            "reason": "Invalid status.",
        },
        {
            "lead_name": "Recent Lead",
            "phone": "4805550108",
            "recommended_bucket": "recently-contacted",
            "risk_flags": ["recent_outbound_touch"],
            "last_outbound_touch": recent,
            "confidence": 0.9,
            "reason": "Outbound touch inside recent window.",
        },
        {
            "lead_name": "Automated Lead",
            "phone": "4805550109",
            "recommended_bucket": "already-automated",
            "risk_flags": ["ghl_workflow_detected"],
            "confidence": 0.85,
            "reason": "Automation already exists.",
        },
    ]


def _client(tmp_path, monkeypatch) -> TestClient:
    monkeypatch.setenv("CLERK_ADMIN_USER_ID", "user_3ASrwDOrSTaDxCus6f1B5lnDsgz")
    job_id = _install_report(tmp_path, monkeypatch, rows=_rows())
    sf = _run(_session_factory())
    client = TestClient(_make_app(sf))
    res = client.post(f"/api/admin/registry/imports/lead-hygiene/{job_id}")
    assert res.status_code == 200, res.text
    return client


@pytest.mark.skipif(not HAS_AIOSQLITE, reason="aiosqlite is not installed")
def test_pool_maps_buckets_and_masks_contact(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)

    eligible = client.get("/api/admin/registry/reengagement/pool?view=eligible")
    assert eligible.status_code == 200, eligible.text
    eligible_rows = eligible.json()
    assert [row["display_name"] for row in eligible_rows] == ["Eligible Lead", "Previous Outreach"]
    assert eligible_rows[0]["bucket"] == "reengage-ready"
    assert eligible_rows[0]["never_responded"] is True
    assert eligible_rows[0]["eligibility_reason"] == "reengage-ready-never-responded"
    assert eligible_rows[0]["masked_phone"].startswith("***-***-")
    assert "4805550101" not in eligible.text
    assert "eligible@example.com" not in eligible.text
    previous = next(row for row in eligible_rows if row["display_name"] == "Previous Outreach")
    assert previous["bucket"] == "previous-outreach-detected"
    assert previous["never_responded"] is True
    assert previous["eligibility_reason"] == "old-outbound-never-responded"
    assert previous["last_outbound_touch"]
    assert previous["last_inbound_touch"] is None
    assert previous["last_appointment"] is None

    review = client.get("/api/admin/registry/reengagement/pool?view=needs_review&sort=name")
    assert review.status_code == 200, review.text
    review_names = {row["display_name"] for row in review.json()}
    assert {"Appointment Lead", "Duplicate Lead", "Inbound Responder", "Malformed Outreach", "No Phone"}.issubset(review_names)
    assert "Previous Outreach" not in review_names
    malformed = next(row for row in review.json() if row["display_name"] == "Malformed Outreach")
    assert malformed["never_responded"] is True
    assert malformed["eligibility_reason"] is None
    assert malformed["locked_reason"]
    inbound = next(row for row in review.json() if row["display_name"] == "Inbound Responder")
    assert inbound["never_responded"] is False
    assert "inbound_response_detected" in inbound["excluded_reasons"]
    assert inbound["locked_reason"]
    appointment = next(row for row in review.json() if row["display_name"] == "Appointment Lead")
    assert appointment["never_responded"] is False
    assert "appointment_detected" in appointment["excluded_reasons"]
    assert appointment["last_appointment"]

    locked = client.get("/api/admin/registry/reengagement/pool?view=do_not_touch")
    assert locked.status_code == 200, locked.text
    locked_names = {row["display_name"] for row in locked.json()}
    assert {"Dnc Lead", "Not Interested", "Client Lead", "Invalid Lead"}.issubset(locked_names)
    assert all(row["locked_reason"] for row in locked.json())

    excluded = client.get("/api/admin/registry/reengagement/pool?view=excluded")
    assert excluded.status_code == 200, excluded.text
    excluded_names = {row["display_name"] for row in excluded.json()}
    assert {"Recent Lead", "Automated Lead"}.issubset(excluded_names)


@pytest.mark.skipif(not HAS_AIOSQLITE, reason="aiosqlite is not installed")
def test_summary_counts_pools(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)

    res = client.get("/api/admin/registry/reengagement/summary")
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["eligible"] == 2
    assert body["needs_review"] >= 4
    assert body["do_not_touch"] >= 4
    assert body["excluded_recent_or_automated"] >= 2
    assert body["staged_batches"] == 0
    assert body["released_batches"] == 0
    assert body["persistence_enabled"] is False
    assert body["proposed_tag"] == "reengage-staging"
