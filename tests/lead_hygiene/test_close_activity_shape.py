"""Fixture coverage for the Close activity shape contract.

Validates that an activity dict shaped like Close's live /activity/ response
(TaskCompleted with `text`, Email with `body_text` + `subject`) classifies
correctly when handed straight to classify_lead.
"""

from datetime import datetime, timezone

import pytest

from services.lead_hygiene import ClassificationContext, classify_lead


NOW = datetime(2026, 5, 18, 12, 0, tzinfo=timezone.utc)


def _ctx(activities):
    return ClassificationContext(
        close_lead_id="lead_y",
        ghl_contact_id=None,
        notion_page_id=None,
        lead_name="Sample Lead",
        phones=["+14801234567"],
        emails=[],
        close_status="Voicemail",
        cadence_stage=None,
        ghl_tags=[],
        notion_status=None,
        notion_opportunity_stage=None,
        close_activities=activities,
        notion_body="",
        ambiguous_match=False,
        duplicate_phone=False,
        now=NOW,
        recent_window_days=30,
    )


def test_close_task_completed_text_field_reaches_classifier():
    # Matches the shape returned by services.lead_hygiene_collect
    # _fetch_close_activities_live for a TaskCompleted activity.
    result = classify_lead(_ctx([
        {
            "type": "task_completed",
            "direction": "",
            "duration": None,
            "text": "Reached out, lead said do not call back.",
            "note": None,
            "body": None,
            "body_text": None,
            "task_text": None,
            "subject": None,
            "activity_type_name": "",
            "date_created": "2025-12-01T15:00:00Z",
        },
    ]))
    assert result.recommended_bucket == "do-not-contact"
    assert "dnc_language" in result.risk_flags


def test_close_email_body_text_field_reaches_classifier():
    result = classify_lead(_ctx([
        {
            "type": "email",
            "direction": "incoming",  # inbound emails use "incoming" in Close
            "duration": None,
            "text": None,
            "note": None,
            "body": None,
            "body_text": "Please unsubscribe me from this list. Thanks.",
            "task_text": None,
            "subject": "Re: Mortgage protection follow-up",
            "activity_type_name": "",
            "date_created": "2025-11-15T08:00:00Z",
        },
    ]))
    assert result.recommended_bucket == "do-not-contact"
    assert "sms_opt_out" in result.risk_flags


def test_close_call_note_field_reaches_classifier():
    result = classify_lead(_ctx([
        {
            "type": "call",
            "direction": "outbound",
            "duration": 45,
            "text": None,
            "note": "Spoke with lead. Asked to stop texting and calling.",
            "body": None,
            "body_text": None,
            "task_text": None,
            "subject": None,
            "activity_type_name": "",
            "date_created": "2025-10-01T10:00:00Z",
        },
    ]))
    # Outbound CALL bodies (notes) ARE scanned — the note is agent-authored,
    # not template copy. Hard-stop should fire.
    assert result.recommended_bucket == "do-not-contact"
    assert "stop_language" in result.risk_flags
