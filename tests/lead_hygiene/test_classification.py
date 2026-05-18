"""Tests for the classification logic in services.lead_hygiene.

Buckets:
  do-not-contact, not-interested, invalid, client, duplicate, missing-phone,
  recently-contacted, already-automated, previous-outreach-detected,
  reengage-ready, needs-review.

Risk flags (selection):
  sms_opt_out, dnc_language, stop_language, not_interested_status,
  invalid_status, client_status, recent_outbound_touch,
  inbound_response_detected, appointment_detected, ghl_workflow_detected,
  rvm_tag_detected, ambiguous_match, missing_phone, duplicate_phone.
"""

from datetime import datetime, timedelta, timezone

import pytest

from services.lead_hygiene import classify_lead, ClassificationContext


NOW = datetime(2026, 5, 18, 12, 0, tzinfo=timezone.utc)


def _ctx(**overrides) -> ClassificationContext:
    base = dict(
        close_lead_id="lead_1",
        ghl_contact_id=None,
        notion_page_id=None,
        lead_name="John Smith",
        phones=["+14801234567"],
        emails=["john@example.com"],
        close_status="New Lead",
        cadence_stage="1. r0-pending",
        ghl_tags=[],
        notion_status=None,
        notion_opportunity_stage=None,
        close_activities=[],
        notion_body="",
        ambiguous_match=False,
        duplicate_phone=False,
        now=NOW,
        recent_window_days=30,
    )
    base.update(overrides)
    return ClassificationContext(**base)


# ───────── do-not-contact bucket ─────────

class TestDoNotContact:
    def test_sms_opt_out_activity_triggers_dnc(self):
        ctx = _ctx(close_activities=[
            {"type": "sms", "direction": "inbound", "body": "STOP",
             "date_created": "2025-12-01T10:00:00Z"},
        ])
        result = classify_lead(ctx)

        assert result.recommended_bucket == "do-not-contact"
        assert "stop_language" in result.risk_flags
        assert "rvm-staging" not in result.recommended_ghl_tags
        assert "do-not-contact" in result.recommended_ghl_tags

    def test_dnc_phrase_in_note(self):
        ctx = _ctx(close_activities=[
            {"type": "note", "body": "Lead asked to be put on the do not call list",
             "date_created": "2025-11-20T10:00:00Z"},
        ])
        result = classify_lead(ctx)
        assert result.recommended_bucket == "do-not-contact"
        assert "dnc_language" in result.risk_flags

    def test_unsubscribe_in_inbound_sms(self):
        ctx = _ctx(close_activities=[
            {"type": "sms", "direction": "inbound", "body": "Please unsubscribe me",
             "date_created": "2025-11-01T10:00:00Z"},
        ])
        result = classify_lead(ctx)
        assert result.recommended_bucket == "do-not-contact"


# ───────── not-interested bucket ─────────

class TestNotInterested:
    def test_close_status_not_interested(self):
        ctx = _ctx(close_status="Not Interested")
        result = classify_lead(ctx)
        assert result.recommended_bucket == "not-interested"
        assert "not_interested_status" in result.risk_flags
        assert "not-interested" in result.recommended_ghl_tags

    def test_notion_status_not_interested_lost(self):
        ctx = _ctx(notion_status="Not Interested/Lost", close_status="Contacted")
        result = classify_lead(ctx)
        assert result.recommended_bucket == "not-interested"


# ───────── invalid bucket ─────────

class TestInvalid:
    def test_close_status_invalid(self):
        ctx = _ctx(close_status="Invalid")
        result = classify_lead(ctx)
        assert result.recommended_bucket == "invalid"
        assert "invalid_status" in result.risk_flags


# ───────── client bucket ─────────

class TestClient:
    def test_close_status_client(self):
        ctx = _ctx(close_status="Client")
        result = classify_lead(ctx)
        assert result.recommended_bucket == "client"
        assert "client_status" in result.risk_flags

    def test_notion_opportunity_approved(self):
        ctx = _ctx(notion_opportunity_stage="Approved")
        result = classify_lead(ctx)
        assert result.recommended_bucket == "client"


# ───────── missing-phone bucket ─────────

class TestMissingPhone:
    def test_no_phones_returns_missing_phone(self):
        ctx = _ctx(phones=[])
        result = classify_lead(ctx)
        assert result.recommended_bucket == "missing-phone"
        assert "missing_phone" in result.risk_flags


# ───────── duplicate bucket ─────────

class TestDuplicate:
    def test_duplicate_phone_marked_as_duplicate(self):
        ctx = _ctx(duplicate_phone=True)
        result = classify_lead(ctx)
        # Duplicates need manual review — they get the duplicate bucket
        # and the duplicate_phone risk flag.
        assert result.recommended_bucket == "duplicate"
        assert "duplicate_phone" in result.risk_flags


# ───────── recently-contacted bucket ─────────

class TestRecentlyContacted:
    def test_outbound_within_window_blocks_automation(self):
        recent = NOW - timedelta(days=10)
        ctx = _ctx(close_activities=[
            {"type": "call", "direction": "outbound", "duration": 30,
             "date_created": recent.isoformat()},
        ])
        result = classify_lead(ctx)
        assert result.recommended_bucket == "recently-contacted"
        assert "recent_outbound_touch" in result.risk_flags

    def test_outbound_older_than_window_does_not_block(self):
        old = NOW - timedelta(days=200)
        ctx = _ctx(close_activities=[
            {"type": "call", "direction": "outbound", "duration": 30,
             "date_created": old.isoformat()},
        ])
        result = classify_lead(ctx)
        # Old outbound touches still indicate prior outreach but should not
        # land in recently-contacted.
        assert result.recommended_bucket != "recently-contacted"


# ───────── inbound response handling ─────────

class TestInboundResponse:
    def test_inbound_call_routes_to_needs_review(self):
        ctx = _ctx(close_activities=[
            {"type": "call", "direction": "inbound", "duration": 45,
             "date_created": "2025-10-01T10:00:00Z"},
        ])
        result = classify_lead(ctx)
        assert "inbound_response_detected" in result.risk_flags
        # An inbound response is a soft positive — must be reviewed, never
        # silently swept into automation.
        assert result.recommended_bucket in {"needs-review", "previous-outreach-detected"}
        assert "rvm-staging" not in result.recommended_ghl_tags


# ───────── appointment handling ─────────

class TestAppointment:
    def test_appointment_activity_flags_and_excludes(self):
        ctx = _ctx(close_activities=[
            {"type": "custom_activity", "activity_type_name": "Book Appointment",
             "date_created": "2025-09-01T10:00:00Z"},
        ])
        result = classify_lead(ctx)
        assert "appointment_detected" in result.risk_flags
        assert "rvm-staging" not in result.recommended_ghl_tags


# ───────── already-automated bucket ─────────

class TestAlreadyAutomated:
    def test_rvm_complete_tag(self):
        ctx = _ctx(ghl_tags=["rvm-complete"])
        result = classify_lead(ctx)
        assert result.recommended_bucket == "already-automated"
        assert "rvm_tag_detected" in result.risk_flags

    def test_r0_complete_tag(self):
        ctx = _ctx(ghl_tags=["r0-complete"])
        result = classify_lead(ctx)
        assert result.recommended_bucket == "already-automated"
        assert "ghl_workflow_detected" in result.risk_flags

    def test_rvm_pending_tag_is_already_automated(self):
        ctx = _ctx(ghl_tags=["rvm-pending"])
        result = classify_lead(ctx)
        assert result.recommended_bucket == "already-automated"


# ───────── previous-outreach-detected bucket ─────────

class TestPreviousOutreach:
    def test_old_outbound_with_no_hard_stop(self):
        old = NOW - timedelta(days=180)
        ctx = _ctx(
            close_status="Contacted",
            close_activities=[
                {"type": "call", "direction": "outbound", "duration": 25,
                 "date_created": old.isoformat()},
            ],
        )
        result = classify_lead(ctx)
        assert result.recommended_bucket == "previous-outreach-detected"


# ───────── reengage-ready bucket ─────────

class TestReengageReady:
    def test_voicemail_with_old_touch_and_no_hard_stop(self):
        old = NOW - timedelta(days=240)
        ctx = _ctx(
            close_status="Voicemail",
            close_activities=[
                {"type": "call", "direction": "outbound", "duration": 0,
                 "date_created": old.isoformat()},
            ],
        )
        result = classify_lead(ctx)
        assert result.recommended_bucket == "reengage-ready"
        # Safe to recommend staging tag — never the active workflow trigger.
        assert "rvm-staging" in result.recommended_ghl_tags
        assert "rvm-pending" not in result.recommended_ghl_tags


# ───────── needs-review bucket ─────────

class TestNeedsReview:
    def test_ambiguous_match_falls_to_needs_review(self):
        ctx = _ctx(ambiguous_match=True)
        result = classify_lead(ctx)
        assert result.recommended_bucket == "needs-review"
        assert "ambiguous_match" in result.risk_flags

    def test_no_signals_at_all_falls_to_needs_review(self):
        # A fresh New Lead with no activity is too unclear to bucket.
        ctx = _ctx(close_status="New Lead", close_activities=[])
        result = classify_lead(ctx)
        assert result.recommended_bucket == "needs-review"


# ───────── invariants ─────────

class TestInvariants:
    def test_never_recommends_rvm_pending(self):
        # Across every bucket, rvm-pending must never appear.
        for status in ["New Lead", "Voicemail", "Contacted"]:
            ctx = _ctx(close_status=status)
            result = classify_lead(ctx)
            assert "rvm-pending" not in result.recommended_ghl_tags, (
                f"rvm-pending leaked into bucket {result.recommended_bucket}"
            )

    def test_confidence_is_zero_to_one(self):
        ctx = _ctx(close_status="Not Interested")
        result = classify_lead(ctx)
        assert 0.0 <= result.confidence <= 1.0

    def test_reason_is_non_empty(self):
        ctx = _ctx(close_status="Not Interested")
        result = classify_lead(ctx)
        assert result.reason
