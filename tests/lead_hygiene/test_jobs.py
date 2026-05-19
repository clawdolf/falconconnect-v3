"""Tests for the background job registry + admin endpoints.

The job registry is in-process and runs the audit on asyncio. Tests use
fixture mode (no network) and a tmp directory for the reports base so they
never touch /tmp/falconconnect/...
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError

from middleware.auth import require_auth
from routers.lead_hygiene import router
from routers.lead_hygiene import StartJobRequest, _resolve_upload_path
from services import lead_hygiene_jobs as jobs


@pytest.fixture(autouse=True)
def _isolate_reports_base(tmp_path: Path, monkeypatch):
    """Point both the registry and the router at a per-test reports base."""
    base = tmp_path / "reports"
    base.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(jobs, "REPORTS_BASE", base)
    # The router imports REPORTS_BASE by symbol — patch its DEFAULT_REPORTS_BASE
    # so the upload endpoint sandbox matches.
    from routers import lead_hygiene as router_mod
    monkeypatch.setattr(router_mod, "DEFAULT_REPORTS_BASE", base)
    monkeypatch.setattr(router_mod, "NOTION_UPLOAD_DIR", base / "_uploads")
    jobs._reset_registry_for_tests()
    yield


# ─── Request validators ──────────────────────────────────────────────


class TestStartJobRequestValidation:
    def test_defaults(self):
        req = StartJobRequest()
        assert req.limit == 200
        assert req.status_label == "Voicemail"
        assert req.include_ghl is True
        assert req.notion_upload_token is None

    def test_empty_status_label_normalises_to_none(self):
        req = StartJobRequest(status_label="")
        assert req.status_label is None

    def test_status_label_rejects_punctuation(self):
        with pytest.raises(ValidationError):
            StartJobRequest(status_label="Voicemail; DROP TABLE")
        with pytest.raises(ValidationError):
            StartJobRequest(status_label="../etc")

    def test_status_label_accepts_typical_values(self):
        for v in ("Voicemail", "Re-Engage", "Not Interested", "All"):
            req = StartJobRequest(status_label=v)
            assert req.status_label == v

    def test_status_label_overlong_rejected(self):
        with pytest.raises(ValidationError):
            StartJobRequest(status_label="a" * 100)

    def test_limit_bounds(self):
        with pytest.raises(ValidationError):
            StartJobRequest(limit=0)
        with pytest.raises(ValidationError):
            StartJobRequest(limit=100_000)
        StartJobRequest(limit=7500)  # explicit "full audit" path

    def test_upload_token_must_be_hex(self):
        with pytest.raises(ValidationError):
            StartJobRequest(notion_upload_token="not-a-hex-token")
        with pytest.raises(ValidationError):
            StartJobRequest(notion_upload_token="../escape")
        StartJobRequest(notion_upload_token="a" * 32)

    def test_legacy_request_rejects_raw_notion_path(self):
        from routers.lead_hygiene import AuditRequest
        with pytest.raises(ValidationError):
            AuditRequest(notion_csv_path="/tmp/secret/archive.csv")

    def test_extra_query_is_bounded(self):
        StartJobRequest(extra_query='created < "2024-01-01"')
        with pytest.raises(ValidationError):
            StartJobRequest(extra_query="a" * 201)
        with pytest.raises(ValidationError):
            StartJobRequest(extra_query="status:Voicemail; rm -rf /")


# ─── Report download path safety ────────────────────────────────────


class TestResolveReportPath:
    def test_invalid_job_id_rejected(self):
        with pytest.raises(ValueError):
            jobs.resolve_report_path("not-a-uuid", "csv")
        with pytest.raises(ValueError):
            jobs.resolve_report_path("../../etc/passwd", "csv")
        with pytest.raises(ValueError):
            jobs.resolve_report_path("a" * 31, "csv")  # one too short

    def test_unknown_kind_rejected(self):
        valid_id = "a" * 32
        with pytest.raises(ValueError):
            jobs.resolve_report_path(valid_id, "exe")
        with pytest.raises(ValueError):
            jobs.resolve_report_path(valid_id, "../etc/passwd")

    def test_missing_run_raises_not_found(self):
        valid_id = "b" * 32
        with pytest.raises(FileNotFoundError):
            jobs.resolve_report_path(valid_id, "csv")


# ─── End-to-end fixture run via the job registry ─────────────────────


def _run_to_completion(params: jobs.JobParams) -> jobs.JobRecord:
    """Schedule a job and await its completion in a fresh event loop."""
    async def _go() -> jobs.JobRecord:
        rec = await jobs.start_job(params)
        # _TASKS is populated synchronously by start_job
        await asyncio.wait_for(jobs._TASKS[rec.job_id], timeout=30)
        return rec
    return asyncio.run(_go())


def _make_app(user_id: str = "user_3ASrwDOrSTaDxCus6f1B5lnDsgz") -> FastAPI:
    app = FastAPI()
    app.include_router(router, prefix="/api/admin/lead-hygiene")

    async def _auth_override():
        return {"sub": user_id, "user_id": user_id}

    app.dependency_overrides[require_auth] = _auth_override
    return app


class TestFixtureBackgroundRun:
    def test_full_lifecycle_fixture(self):
        rec = _run_to_completion(jobs.JobParams(fixture_mode=True, limit=11))
        assert rec.status == "completed"
        assert rec.phase == "done"
        assert rec.error is None
        assert rec.summary is not None
        assert rec.summary["total"] == 11
        assert Path(rec.csv_path).is_file()
        assert Path(rec.json_path).is_file()
        # meta.json was written so the run survives a restart
        assert Path(rec.meta_path).is_file()

    def test_list_runs_includes_completed(self):
        rec = _run_to_completion(jobs.JobParams(fixture_mode=True))
        runs = jobs.list_runs()
        assert any(r["job_id"] == rec.job_id for r in runs)

    def test_list_runs_survives_registry_reload_from_disk(self):
        rec = _run_to_completion(jobs.JobParams(fixture_mode=True))
        jobs._reset_registry_for_tests()
        runs = jobs.list_runs()
        reloaded = next(r for r in runs if r["job_id"] == rec.job_id)
        assert reloaded["status"] == "completed"
        assert reloaded["reports"]["json"] is True
        assert reloaded["row_count"] == 11
        assert reloaded["short_job_id"] == rec.job_id[:8]

    def test_public_record_does_not_leak_upload_path(self):
        params = jobs.JobParams(fixture_mode=True, notion_csv_path="/tmp/secret/archive.csv")
        rec = _run_to_completion(params)
        public = rec.to_public()
        assert public["params"]["notion_csv_path"] is True
        assert "/tmp/secret" not in json.dumps(public)

    def test_get_run_after_registry_reset_reads_meta(self):
        rec = _run_to_completion(jobs.JobParams(fixture_mode=True))
        jobs._reset_registry_for_tests()
        # In-memory registry is gone; on-disk meta.json should still work.
        reloaded = jobs.get_run(rec.job_id)
        assert reloaded is not None
        assert reloaded.status == "completed"
        assert reloaded.summary is not None

    def test_preview_returns_projection_only(self):
        rec = _run_to_completion(jobs.JobParams(fixture_mode=True))
        preview = jobs.load_report_preview(rec.job_id, limit=5)
        assert preview["total_rows"] == 11
        assert len(preview["rows"]) == 5
        for row in preview["rows"]:
            # Only the projection fields land in preview rows.
            assert set(row.keys()) >= {
                "lead_name", "phone", "close_lead_id", "recommended_bucket",
                "risk_flags", "reason", "confidence",
            }
            # Heavy raw fields are stripped.
            assert "activity_summary" not in row
            assert "recommended_close_update" not in row

    def test_preview_filters_hard_stop_group(self):
        rec = _run_to_completion(jobs.JobParams(fixture_mode=True))
        preview = jobs.load_report_preview(rec.job_id, limit=20, category="hard-stop")
        assert preview["category"] == "hard-stop"
        assert preview["total_rows"] > 0
        assert {r["recommended_bucket"] for r in preview["rows"]} <= {
            "do-not-contact", "not-interested", "invalid",
        }

    def test_preview_filters_needs_review_group(self):
        rec = _run_to_completion(jobs.JobParams(fixture_mode=True))
        preview = jobs.load_report_preview(rec.job_id, limit=20, category="needs-review-group")
        assert preview["category"] == "needs-review-group"
        assert preview["total_rows"] > 0
        assert {r["recommended_bucket"] for r in preview["rows"]} <= {
            "needs-review", "duplicate", "missing-phone",
        }

    def test_preview_filters_exact_bucket(self):
        rec = _run_to_completion(jobs.JobParams(fixture_mode=True))
        preview = jobs.load_report_preview(rec.job_id, limit=20, category="duplicate")
        assert preview["category"] == "duplicate"
        assert preview["total_rows"] > 0
        assert {r["recommended_bucket"] for r in preview["rows"]} == {"duplicate"}

    def test_preview_unknown_category_rejected(self):
        rec = _run_to_completion(jobs.JobParams(fixture_mode=True))
        with pytest.raises(ValueError):
            jobs.load_report_preview(rec.job_id, category="not-a-category")

    def test_download_paths_resolve_after_run(self):
        rec = _run_to_completion(jobs.JobParams(fixture_mode=True))
        csv_path = jobs.resolve_report_path(rec.job_id, "csv")
        json_path = jobs.resolve_report_path(rec.job_id, "json")
        assert csv_path.is_file()
        assert json_path.is_file()
        with pytest.raises(ValueError):
            jobs.resolve_report_path(rec.job_id, "meta")
        # Sanity: stays inside the reports base
        assert str(csv_path).startswith(str(jobs.REPORTS_BASE))

    def test_failed_job_records_error(self, monkeypatch):
        # Force the underlying runner to raise so we exercise the failure path.
        def _boom(**kwargs):  # noqa: ANN001
            raise RuntimeError("synthetic failure for test")
        monkeypatch.setattr(jobs, "run_audit_from_fixtures", _boom)
        rec = _run_to_completion(jobs.JobParams(fixture_mode=True))
        assert rec.status == "failed"
        assert rec.phase == "error"
        assert rec.error is not None
        assert "synthetic failure" in rec.error

    def test_history_endpoint_does_not_expose_absolute_paths(self):
        rec = _run_to_completion(jobs.JobParams(fixture_mode=True, notion_csv_path="/tmp/secret/archive.csv"))
        client = TestClient(_make_app())

        res = client.get("/api/admin/lead-hygiene/runs?limit=100")

        assert res.status_code == 200, res.text
        assert rec.job_id in res.text
        assert str(jobs.REPORTS_BASE) not in res.text
        assert "/tmp/secret" not in res.text
        assert "lead_hygiene_report.json" not in res.text

    def test_delete_removes_local_run_and_memory_registry(self):
        rec = _run_to_completion(jobs.JobParams(fixture_mode=True))
        run_dir = Path(rec.run_dir)
        assert rec.job_id in jobs._REGISTRY

        result = jobs.delete_run(rec.job_id)

        assert result["deleted"] is True
        assert result["job_id"] == rec.job_id
        assert result["removed_files"] >= 3
        assert not run_dir.exists()
        assert rec.job_id not in jobs._REGISTRY
        assert jobs.get_run(rec.job_id) is None

    def test_delete_rejects_running_job_with_409(self):
        job_id = "c" * 32
        run_dir = jobs.REPORTS_BASE / f"run-20260518T180000Z-{job_id[:12]}"
        run_dir.mkdir(parents=True)
        rec = jobs.JobRecord(
            job_id=job_id,
            status="running",
            params={},
            started_at="2026-05-18T18:00:00+00:00",
            run_dir=str(run_dir),
        )
        jobs._REGISTRY[job_id] = rec
        client = TestClient(_make_app())

        res = client.delete(f"/api/admin/lead-hygiene/runs/{job_id}")

        assert res.status_code == 409, res.text
        assert run_dir.exists()
        assert job_id in jobs._REGISTRY

    def test_delete_rejects_invalid_job_ids(self):
        client = TestClient(_make_app())
        for bad_id in ("not-a-uuid", "../../etc/passwd", "a" * 31):
            res = client.delete(f"/api/admin/lead-hygiene/runs/{bad_id}")
            assert res.status_code in {400, 404}, res.text

    def test_delete_missing_job_returns_404(self):
        client = TestClient(_make_app())
        res = client.delete(f"/api/admin/lead-hygiene/runs/{'d' * 32}")
        assert res.status_code == 404, res.text


# ─── Notion CSV upload sandbox ───────────────────────────────────────


class TestUploadSandbox:
    def test_invalid_token_rejected(self):
        from fastapi import HTTPException
        with pytest.raises(HTTPException) as exc:
            _resolve_upload_path("not-hex")
        assert exc.value.status_code == 400

    def test_traversal_in_token_rejected(self):
        from fastapi import HTTPException
        with pytest.raises(HTTPException) as exc:
            _resolve_upload_path("../etc/passwd")
        assert exc.value.status_code == 400

    def test_missing_file_returns_404(self, tmp_path: Path, monkeypatch):
        # Use a well-formed but non-existent token.
        from fastapi import HTTPException
        with pytest.raises(HTTPException) as exc:
            _resolve_upload_path("a" * 32)
        assert exc.value.status_code == 404
