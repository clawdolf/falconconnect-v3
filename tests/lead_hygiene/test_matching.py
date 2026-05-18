"""Tests for cross-source matching in services.lead_hygiene.

Matching priority (per spec):
1. normalized phone
2. normalized email
3. full name + last-name verification fallback
4. never first-name-only
5. ambiguous → needs-review
"""

import pytest

from services.lead_hygiene import (
    build_record_index,
    match_records,
    MatchResult,
)


def _close_lead(lead_id, phones=None, emails=None, name=""):
    return {
        "source": "close",
        "source_id": lead_id,
        "name": name,
        "phones": phones or [],
        "emails": emails or [],
    }


def _ghl_contact(contact_id, phones=None, emails=None, name=""):
    return {
        "source": "ghl",
        "source_id": contact_id,
        "name": name,
        "phones": phones or [],
        "emails": emails or [],
    }


def _notion_row(page_id, phones=None, emails=None, name=""):
    return {
        "source": "notion",
        "source_id": page_id,
        "name": name,
        "phones": phones or [],
        "emails": emails or [],
    }


class TestPhoneMatchingPrimary:
    def test_phone_match_links_records_across_sources(self):
        close = _close_lead("lead_1", phones=["+14801234567"], name="John Smith")
        ghl = _ghl_contact("ghl_1", phones=["(480) 123-4567"], name="John Smith")

        index = build_record_index([close], [ghl], [])
        result = match_records(close, index)

        assert isinstance(result, MatchResult)
        assert result.ghl_id == "ghl_1"
        assert result.match_basis == "phone"
        assert result.ambiguous is False

    def test_phone_match_wins_over_name_mismatch(self):
        # Phone is authoritative — last name mismatch is a separate warning,
        # not a disqualifier for the link.
        close = _close_lead("lead_1", phones=["+14801234567"], name="John Smith")
        ghl = _ghl_contact("ghl_1", phones=["+14801234567"], name="Jane Doe")

        index = build_record_index([close], [ghl], [])
        result = match_records(close, index)

        assert result.ghl_id == "ghl_1"
        assert result.match_basis == "phone"
        assert "name_mismatch" in result.warnings


class TestEmailMatchingFallback:
    def test_email_used_when_no_phone(self):
        close = _close_lead("lead_1", emails=["jane@example.com"], name="Jane Doe")
        ghl = _ghl_contact("ghl_1", emails=["JANE@EXAMPLE.COM"], name="Jane Doe")

        index = build_record_index([close], [ghl], [])
        result = match_records(close, index)

        assert result.ghl_id == "ghl_1"
        assert result.match_basis == "email"

    def test_dummy_emails_are_not_a_match_basis(self):
        # Dummy emails (noemail@…) must not produce a match.
        close = _close_lead("lead_1", emails=["noemail@falconfinancial.org"], name="Jane Doe")
        ghl = _ghl_contact("ghl_1", emails=["noemail@falconfinancial.org"], name="Bob Different")

        index = build_record_index([close], [ghl], [])
        result = match_records(close, index)

        assert result.ghl_id is None
        assert result.match_basis is None


class TestNameMatchingFallback:
    def test_full_name_match_with_last_name_confirmation(self):
        close = _close_lead("lead_1", name="John Smith")
        notion = _notion_row("page_1", name="John Smith")

        index = build_record_index([close], [], [notion])
        result = match_records(close, index)

        assert result.notion_id == "page_1"
        assert result.match_basis == "name"

    def test_first_name_only_does_not_match(self):
        # A Notion row that shares only the first name must NOT link.
        close = _close_lead("lead_1", name="John Smith")
        notion = _notion_row("page_1", name="John Doe")

        index = build_record_index([close], [], [notion])
        result = match_records(close, index)

        assert result.notion_id is None


class TestAmbiguousMatching:
    def test_two_candidates_on_same_phone_flags_ambiguous(self):
        close = _close_lead("lead_1", phones=["+14801234567"], name="John Smith")
        ghl_a = _ghl_contact("ghl_a", phones=["+14801234567"], name="Person A")
        ghl_b = _ghl_contact("ghl_b", phones=["+14801234567"], name="Person B")

        index = build_record_index([close], [ghl_a, ghl_b], [])
        result = match_records(close, index)

        assert result.ambiguous is True
        # We do not arbitrarily pick one — leave the link empty so the lead
        # ends up in needs-review.
        assert result.ghl_id is None

    def test_two_notion_pages_with_same_full_name_flags_ambiguous(self):
        close = _close_lead("lead_1", name="John Smith")
        notion_a = _notion_row("page_a", name="John Smith")
        notion_b = _notion_row("page_b", name="John Smith")

        index = build_record_index([close], [], [notion_a, notion_b])
        result = match_records(close, index)

        assert result.ambiguous is True
        assert result.notion_id is None
