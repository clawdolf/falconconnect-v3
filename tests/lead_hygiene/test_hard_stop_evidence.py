"""Regression tests for hard-stop language detection across activity bodies
and Notion aggregate comments.

Findings addressed:
- Hermes #1: classify hard-stop language from notes / tasks / Notion comments
  including phrases like "stop texting me", even when direction is blank.
- Hermes #2: TaskCompleted activities carry their text in `text` (and
  sometimes `task_text`); these must contribute to the body scan.
"""

from datetime import datetime, timezone

import pytest

from services.lead_hygiene import ClassificationContext, classify_lead


NOW = datetime(2026, 5, 18, 12, 0, tzinfo=timezone.utc)


def _ctx(**overrides) -> ClassificationContext:
    base = dict(
        close_lead_id="lead_x",
        ghl_contact_id=None,
        notion_page_id=None,
        lead_name="Test Lead",
        phones=["+14801234567"],
        emails=[],
        close_status="Voicemail",
        cadence_stage=None,
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


# ───────── notes / tasks without a direction ─────────


class TestHardStopFromNoteWithBlankDirection:
    def test_note_says_stop_texting_me_no_direction(self):
        # A Close note transcribed by an agent — no direction field at all.
        ctx = _ctx(close_activities=[
            {"type": "note", "body": "Lead said stop texting me, lose my number.",
             "date_created": "2025-11-01T10:00:00Z"},
        ])
        result = classify_lead(ctx)
        assert result.recommended_bucket == "do-not-contact"
        assert "stop_language" in result.risk_flags

    def test_task_completed_with_stop_calling_text(self):
        # TaskCompleted activities expose body via `text` (and sometimes
        # `task_text`); both must reach the scanner.
        ctx = _ctx(close_activities=[
            {"type": "task_completed",
             "text": "Spoke briefly — said stop calling me, not interested.",
             "date_created": "2025-10-20T10:00:00Z"},
        ])
        result = classify_lead(ctx)
        assert result.recommended_bucket == "do-not-contact"
        assert "stop_language" in result.risk_flags

    def test_task_completed_via_task_text_field(self):
        # Some Close payloads put task copy under task_text rather than text.
        ctx = _ctx(close_activities=[
            {"type": "task_completed",
             "task_text": "Caller asked to be removed — do not contact.",
             "date_created": "2025-10-19T10:00:00Z"},
        ])
        result = classify_lead(ctx)
        assert result.recommended_bucket == "do-not-contact"
        assert "dnc_language" in result.risk_flags

    def test_email_body_text_with_unsubscribe(self):
        # Close email activity stores copy under body_text + subject.
        ctx = _ctx(close_activities=[
            {"type": "email",
             "subject": "Re: Mortgage protection",
             "body_text": "Please unsubscribe me from any further outreach. Thanks.",
             "date_created": "2025-09-15T10:00:00Z"},
        ])
        result = classify_lead(ctx)
        assert result.recommended_bucket == "do-not-contact"
        assert "sms_opt_out" in result.risk_flags


# ───────── word-boundary correctness ─────────


class TestHardStopWordBoundaries:
    def test_word_stopped_does_not_trigger_stop_language(self):
        # "stopped" must NOT match "stop". Otherwise legitimate notes like
        # "Stopped by today" would be flagged.
        ctx = _ctx(close_activities=[
            {"type": "note", "body": "Stopped by today, will call again next week.",
             "date_created": "2025-10-01T10:00:00Z"},
        ])
        result = classify_lead(ctx)
        assert "stop_language" not in result.risk_flags
        assert result.recommended_bucket != "do-not-contact"

    def test_word_end_inside_legend_does_not_match(self):
        # "end" embedded in "legend" or "weekend" must not match.
        ctx = _ctx(close_activities=[
            {"type": "note", "body": "Call back this weekend per the lender legend.",
             "date_created": "2025-10-01T10:00:00Z"},
        ])
        result = classify_lead(ctx)
        assert "stop_language" not in result.risk_flags


# ───────── Notion aggregate comments ─────────


class TestHardStopFromNotion:
    def test_notion_body_stop_texting_me_triggers_dnc(self):
        ctx = _ctx(notion_body="2024-02-15: Caller said stop texting me, not interested.")
        result = classify_lead(ctx)
        assert result.recommended_bucket == "do-not-contact"
        assert "stop_language" in result.risk_flags

    def test_notion_body_take_me_off_list_triggers_dnc(self):
        ctx = _ctx(notion_body="Lead requested: take me off your list immediately.")
        result = classify_lead(ctx)
        assert result.recommended_bucket == "do-not-contact"
        assert "dnc_language" in result.risk_flags

    def test_notion_body_lose_my_number_triggers_dnc(self):
        ctx = _ctx(notion_body="Said to lose my number and never call again.")
        result = classify_lead(ctx)
        assert result.recommended_bucket == "do-not-contact"

    def test_blank_notion_body_no_false_positive(self):
        ctx = _ctx(notion_body="Discussed retirement planning over coffee.")
        result = classify_lead(ctx)
        assert "stop_language" not in result.risk_flags
        assert "dnc_language" not in result.risk_flags
        assert result.recommended_bucket != "do-not-contact"


# ───────── outbound SMS that says "STOP" must NOT trigger ─────────


class TestNoFalsePositivesOnOutboundSms:
    def test_outbound_sms_containing_stop_does_not_dnc_the_lead(self):
        # An outbound template that includes "Reply STOP to unsubscribe"
        # must not flag the lead as DNC.
        ctx = _ctx(close_activities=[
            {"type": "sms", "direction": "outbound",
             "body": "Hey, follow-up on your form. Reply STOP to opt out.",
             "date_created": "2025-09-01T10:00:00Z"},
        ])
        result = classify_lead(ctx)
        assert "stop_language" not in result.risk_flags
