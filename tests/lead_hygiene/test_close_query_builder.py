"""Regression: Close /lead/ filter must use query=status:"...", not status_label.

Verified 2026-05-18: Close silently ignores `status_label=Voicemail` and
`status=Voicemail` on /lead/. The working pattern is the search-syntax
`query=status:"Voicemail"`. The builder must:
  * use `query=status:"X"` when only a status label is supplied
  * combine an additional caller query with the status using AND
  * preserve _limit / _skip pagination on every call
  * escape embedded double-quotes
"""

import pytest

from services.lead_hygiene_collect import _build_close_lead_params


class TestBuildCloseLeadParams:
    def test_pagination_only(self):
        params = _build_close_lead_params(limit=50, skip=100)
        assert params == {"_limit": 50, "_skip": 100}

    def test_status_only_uses_query_status_pattern(self):
        params = _build_close_lead_params(limit=100, skip=0, status_label="Voicemail")
        assert params["query"] == 'status:"Voicemail"'
        assert "status_label" not in params
        assert "status" not in params

    def test_status_with_spaces_is_quoted(self):
        params = _build_close_lead_params(
            limit=100, skip=0, status_label="Appointment Booked",
        )
        assert params["query"] == 'status:"Appointment Booked"'

    def test_extra_query_only(self):
        params = _build_close_lead_params(
            limit=10, skip=0, extra_query='lead_age:"60+ Mo"',
        )
        assert params["query"] == '(lead_age:"60+ Mo")'

    def test_status_and_extra_query_combined_with_and(self):
        params = _build_close_lead_params(
            limit=25, skip=0,
            status_label="Voicemail",
            extra_query='created < "2024-01-01"',
        )
        # Caller-supplied query is wrapped in parens to keep precedence
        # explicit when combined with status.
        assert params["query"] == '(created < "2024-01-01") AND status:"Voicemail"'

    def test_double_quote_in_status_label_is_escaped(self):
        params = _build_close_lead_params(
            limit=10, skip=0, status_label='Weird "Status"',
        )
        assert params["query"] == 'status:"Weird \\"Status\\""'

    def test_pagination_preserved_alongside_query(self):
        params = _build_close_lead_params(
            limit=42, skip=84, status_label="Voicemail",
        )
        assert params["_limit"] == 42
        assert params["_skip"] == 84
        assert params["query"] == 'status:"Voicemail"'

    def test_blank_status_label_treated_as_none(self):
        params = _build_close_lead_params(limit=10, skip=0, status_label="")
        assert "query" not in params

    def test_blank_extra_query_treated_as_none(self):
        params = _build_close_lead_params(
            limit=10, skip=0, status_label="Voicemail", extra_query="   ",
        )
        assert params["query"] == 'status:"Voicemail"'
