"""Tests for normalization helpers in services.lead_hygiene."""

import pytest

from services.lead_hygiene import (
    normalize_phone,
    normalize_email,
    normalize_name,
    name_parts,
)


class TestNormalizePhone:
    def test_us_10_digit_gets_plus_1(self):
        assert normalize_phone("4801234567") == "+14801234567"

    def test_us_11_digit_with_leading_1(self):
        assert normalize_phone("14801234567") == "+14801234567"

    def test_already_formatted_plus_1(self):
        assert normalize_phone("+14801234567") == "+14801234567"

    def test_strips_parens_dashes_spaces(self):
        assert normalize_phone("(480) 123-4567") == "+14801234567"
        assert normalize_phone("480.123.4567") == "+14801234567"
        assert normalize_phone("480 123 4567") == "+14801234567"

    def test_none_returns_empty(self):
        assert normalize_phone(None) == ""

    def test_empty_returns_empty(self):
        assert normalize_phone("") == ""

    def test_literal_none_string_returns_empty(self):
        assert normalize_phone("None") == ""
        assert normalize_phone("none") == ""

    def test_too_short_returns_empty(self):
        assert normalize_phone("12345") == ""

    def test_numeric_int_input(self):
        assert normalize_phone(4801234567) == "+14801234567"


class TestNormalizeEmail:
    def test_lowercases(self):
        assert normalize_email("Foo@Bar.COM") == "foo@bar.com"

    def test_strips_whitespace(self):
        assert normalize_email("  foo@bar.com  ") == "foo@bar.com"

    def test_dummy_emails_treated_as_empty(self):
        # FC has historically used noemail@*.com placeholders during imports.
        # These should not be used for matching.
        assert normalize_email("noemail@falconfinancial.org") == ""
        assert normalize_email("none@none.com") == ""
        assert normalize_email("no-email@example.com") == ""

    def test_invalid_returns_empty(self):
        assert normalize_email("not-an-email") == ""
        assert normalize_email("@no-local.com") == ""
        assert normalize_email("missing-at.com") == ""

    def test_none_returns_empty(self):
        assert normalize_email(None) == ""
        assert normalize_email("") == ""


class TestNormalizeName:
    def test_strips_and_titlecases(self):
        assert normalize_name("  john SMITH  ") == "John Smith"

    def test_collapses_whitespace(self):
        assert normalize_name("john    smith") == "John Smith"

    def test_strips_decoration(self):
        assert normalize_name("John SMITH (deceased)") == "John Smith"
        assert normalize_name("John SMITH - DNC") == "John Smith"

    def test_handles_hyphenated_last_name(self):
        assert normalize_name("Mary Smith-Jones") == "Mary Smith-Jones"

    def test_none_returns_empty(self):
        assert normalize_name(None) == ""
        assert normalize_name("") == ""


class TestNameParts:
    def test_simple(self):
        first, last = name_parts("John Smith")
        assert first == "John"
        assert last == "Smith"

    def test_single_token_returns_empty_last(self):
        first, last = name_parts("Madonna")
        assert first == "Madonna"
        assert last == ""

    def test_multi_token_last_is_last_token(self):
        first, last = name_parts("Mary Anne Smith")
        assert first == "Mary Anne"
        assert last == "Smith"

    def test_normalises_before_split(self):
        first, last = name_parts("  JOHN smith  ")
        assert first == "John"
        assert last == "Smith"
