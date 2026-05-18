"""Tests for the CSV/JSON report writer."""

import csv
import json
from pathlib import Path

import pytest

from services.lead_hygiene import write_report, ReportRow, REPORT_COLUMNS


def _row(**overrides) -> ReportRow:
    base = dict(
        lead_name="John Smith",
        phone="+14801234567",
        email="john@example.com",
        close_lead_id="lead_1",
        ghl_contact_id="ghl_1",
        notion_page_id="page_1",
        close_status="New Lead",
        cadence_stage="1. r0-pending",
        ghl_tags=["rvm-staging"],
        notion_status=None,
        notion_opportunity_stage=None,
        last_outbound_touch=None,
        last_inbound_touch=None,
        last_automation_touch=None,
        last_appointment=None,
        activity_summary="0 calls, 0 sms, 0 notes",
        risk_flags=["missing_phone"],
        recommended_bucket="needs-review",
        recommended_ghl_tags=[],
        recommended_close_update=None,
        confidence=0.5,
        reason="No signals to bucket.",
    )
    base.update(overrides)
    return ReportRow(**base)


class TestWriteReport:
    def test_writes_csv_with_all_required_columns(self, tmp_path: Path):
        rows = [_row()]
        out = write_report(rows, tmp_path)

        with out["csv_path"].open() as fh:
            reader = csv.DictReader(fh)
            header = reader.fieldnames
            assert header == REPORT_COLUMNS
            records = list(reader)
            assert len(records) == 1
            assert records[0]["lead_name"] == "John Smith"
            # Lists are serialised as a deterministic representation.
            assert "rvm-staging" in records[0]["ghl_tags"]
            assert "missing_phone" in records[0]["risk_flags"]

    def test_writes_json_with_summary_counts(self, tmp_path: Path):
        rows = [
            _row(recommended_bucket="needs-review"),
            _row(recommended_bucket="not-interested"),
            _row(recommended_bucket="not-interested"),
            _row(recommended_bucket="reengage-ready"),
        ]
        out = write_report(rows, tmp_path)

        data = json.loads(out["json_path"].read_text())
        assert "rows" in data
        assert len(data["rows"]) == 4
        assert "summary" in data
        assert data["summary"]["total"] == 4
        assert data["summary"]["by_bucket"]["not-interested"] == 2
        assert data["summary"]["by_bucket"]["needs-review"] == 1
        assert data["summary"]["by_bucket"]["reengage-ready"] == 1

    def test_summary_counts_returned_in_result(self, tmp_path: Path):
        rows = [
            _row(recommended_bucket="do-not-contact"),
            _row(recommended_bucket="do-not-contact"),
        ]
        out = write_report(rows, tmp_path)
        assert out["summary"]["by_bucket"]["do-not-contact"] == 2
        assert out["summary"]["total"] == 2

    def test_handles_empty_rows(self, tmp_path: Path):
        out = write_report([], tmp_path)
        assert out["summary"]["total"] == 0
        assert out["csv_path"].exists()
        assert out["json_path"].exists()
