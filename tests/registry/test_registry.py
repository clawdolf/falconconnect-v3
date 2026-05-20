from __future__ import annotations

import asyncio
import importlib.util
import json
from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from db.database import get_session
from db.models import (
    Base,
    RegistryConsentEvent,
    RegistryContactMethod,
    RegistryExternalRecord,
    LeadHygieneReportRun,
    RegistryHousehold,
    RegistryPerson,
    RegistryRecommendation,
    RegistrySourceSnapshot,
)
from middleware.auth import require_auth
from routers.registry import router
import routers.registry as registry_router
from services import lead_hygiene_jobs as jobs
from services.lead_hygiene_jobs import JobRecord

HAS_AIOSQLITE = importlib.util.find_spec("aiosqlite") is not None


REGISTRY_TABLES = [
    RegistryHousehold.__table__,
    RegistryPerson.__table__,
    RegistryContactMethod.__table__,
    RegistrySourceSnapshot.__table__,
    RegistryExternalRecord.__table__,
    RegistryRecommendation.__table__,
    RegistryConsentEvent.__table__,
    LeadHygieneReportRun.__table__,
]


def _run(coro):
    return asyncio.run(coro)


def _make_app(session_factory, user_id: str | None = "user_3ASrwDOrSTaDxCus6f1B5lnDsgz") -> FastAPI:
    if session_factory is None:
        session_factory = _run(_session_factory())
    app = FastAPI()
    app.include_router(router, prefix="/api/admin/registry")

    async def _session_override():
        async with session_factory() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    app.dependency_overrides[get_session] = _session_override
    if user_id is not None:
        async def _auth_override():
            return {"sub": user_id, "user_id": user_id}
        app.dependency_overrides[require_auth] = _auth_override
    return app


async def _session_factory():
    engine = create_async_engine(
        "sqlite+aiosqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all, tables=REGISTRY_TABLES)
    return async_sessionmaker(engine, expire_on_commit=False)


def _install_report(
    tmp_path: Path,
    monkeypatch,
    rows: list[dict] | None = None,
    *,
    job_id: str = "a" * 32,
    status: str = "completed",
    write_json: bool = True,
) -> str:
    run_dir = tmp_path / "reports" / f"run-20260518T180000Z-{job_id[:12]}"
    run_dir.mkdir(parents=True)
    rows = rows or [
        {
            "lead_name": "Ada Lovelace",
            "phone": "(480) 555-0101",
            "email": "ada@example.com",
            "close_lead_id": "lead_close_1",
            "ghl_contact_id": "ghl_1",
            "notion_page_id": "notion_1",
            "recommended_bucket": "needs-review",
            "risk_flags": ["duplicate_phone"],
            "reason": "Possible duplicate across systems.",
            "confidence": 0.91,
            "recommended_close_update": "review status",
            "recommended_ghl_tags": ["review"],
        },
        {
            "lead_name": "Grace Hopper",
            "phone": "4805550102",
            "email": "grace@example.com",
            "close_lead_id": "lead_close_2",
            "ghl_contact_id": "",
            "notion_page_id": "",
            "recommended_bucket": "do-not-contact",
            "risk_flags": ["hard_stop"],
            "reason": "Do not contact evidence found.",
            "confidence": 0.98,
        },
    ]
    if write_json:
        (run_dir / "lead_hygiene_report.json").write_text(json.dumps({"rows": rows, "summary": {"total": len(rows)}}))
    rec = JobRecord(
        job_id=job_id,
        status=status,
        params={"fixture_mode": True, "include_ghl": True, "notion_csv_path": None},
        started_at=datetime.now(timezone.utc).isoformat(),
        run_dir=str(run_dir),
        json_path=str(run_dir / "lead_hygiene_report.json") if write_json else None,
        summary={"total": len(rows)},
    )
    (run_dir / "meta.json").write_text(json.dumps(rec.__dict__, default=str))
    monkeypatch.setattr(jobs, "REPORTS_BASE", tmp_path / "reports")
    jobs._reset_registry_for_tests()
    return job_id


def test_lead_hygiene_reports_list_importable_without_paths(tmp_path, monkeypatch):
    if not HAS_AIOSQLITE:
        import pytest
        pytest.skip("aiosqlite is not installed in this local environment")
    monkeypatch.setenv("CLERK_ADMIN_USER_ID", "user_3ASrwDOrSTaDxCus6f1B5lnDsgz")
    job_id = _install_report(tmp_path, monkeypatch)
    client = TestClient(_make_app(session_factory=None))

    res = client.get("/api/admin/registry/lead-hygiene-reports")
    assert res.status_code == 200, res.text
    body = res.json()
    assert len(body) == 1
    report = body[0]
    assert report["job_id"] == job_id
    assert report["short_job_id"] == "aaaaaaaa..."
    assert report["has_json_report"] is True
    assert report["importable"] is True
    assert report["rows_seen"] == 2
    assert "Completed" in report["label"]
    assert "2 rows" in report["label"]
    assert str(tmp_path) not in res.text
    assert "lead_hygiene_report.json" not in res.text


def test_lead_hygiene_reports_marks_completed_missing_json_not_importable(tmp_path, monkeypatch):
    if not HAS_AIOSQLITE:
        import pytest
        pytest.skip("aiosqlite is not installed in this local environment")
    monkeypatch.setenv("CLERK_ADMIN_USER_ID", "user_3ASrwDOrSTaDxCus6f1B5lnDsgz")
    job_id = _install_report(tmp_path, monkeypatch, job_id="b" * 32, write_json=False)
    client = TestClient(_make_app(session_factory=None))

    res = client.get("/api/admin/registry/lead-hygiene-reports")
    assert res.status_code == 200, res.text
    report = res.json()[0]
    assert report["job_id"] == job_id
    assert report["status"] == "completed"
    assert report["has_json_report"] is False
    assert report["importable"] is False


def test_lead_hygiene_reports_excludes_deleted_run(tmp_path, monkeypatch):
    if not HAS_AIOSQLITE:
        import pytest
        pytest.skip("aiosqlite is not installed in this local environment")
    monkeypatch.setenv("CLERK_ADMIN_USER_ID", "user_3ASrwDOrSTaDxCus6f1B5lnDsgz")
    job_id = _install_report(tmp_path, monkeypatch, job_id="c" * 32)
    client = TestClient(_make_app(session_factory=None))

    before = client.get("/api/admin/registry/lead-hygiene-reports")
    assert before.status_code == 200, before.text
    assert [report["job_id"] for report in before.json()] == [job_id]

    result = jobs.delete_run(job_id)
    assert result["deleted"] is True

    after = client.get("/api/admin/registry/lead-hygiene-reports")
    assert after.status_code == 200, after.text
    assert after.json() == []


def test_admin_guard_rejects_non_admin(monkeypatch):
    if not HAS_AIOSQLITE:
        import pytest
        pytest.skip("aiosqlite is not installed in this local environment")
    monkeypatch.setenv("CLERK_ADMIN_USER_ID", "admin_user")
    sf = _run(_session_factory())
    client = TestClient(_make_app(sf, user_id="other_user"))
    res = client.get("/api/admin/registry/summary")
    assert res.status_code == 403


def test_import_is_idempotent_and_search_detail_work(tmp_path, monkeypatch):
    if not HAS_AIOSQLITE:
        import pytest
        pytest.skip("aiosqlite is not installed in this local environment")
    monkeypatch.setenv("CLERK_ADMIN_USER_ID", "user_3ASrwDOrSTaDxCus6f1B5lnDsgz")
    job_id = _install_report(tmp_path, monkeypatch)
    sf = _run(_session_factory())
    client = TestClient(_make_app(sf))

    first = client.post(f"/api/admin/registry/imports/lead-hygiene/{job_id}")
    assert first.status_code == 200, first.text
    assert first.json()["rows_seen"] == 2
    assert first.json()["households_created"] == 2
    assert first.json()["recommendations_created"] == 2

    second = client.post(f"/api/admin/registry/imports/lead-hygiene/{job_id}")
    assert second.status_code == 200, second.text
    assert second.json()["households_created"] == 0
    assert second.json()["contact_methods_created"] == 0
    assert second.json()["recommendations_created"] == 0

    phone_search = client.get("/api/admin/registry/search?q=4805550101")
    assert phone_search.status_code == 200
    phone_body = phone_search.json()
    assert phone_body["contact_methods"] == []
    assert phone_body["external_records"] == []
    assert phone_body["households"][0]["primary_phone"].startswith("***-***-")
    assert "4805550101" not in json.dumps(phone_body)

    email_search = client.get("/api/admin/registry/search?q=grace@example.com")
    assert email_search.status_code == 200
    email_body = email_search.json()
    assert email_body["contact_methods"] == []
    assert email_body["external_records"] == []
    assert "grace@example.com" not in json.dumps(email_body)

    name_search = client.get("/api/admin/registry/search?q=Ada")
    assert name_search.status_code == 200
    assert name_search.json()["people"][0]["display_name"] == "Ada Lovelace"

    households = client.get("/api/admin/registry/households").json()
    assert households[0]["people_count"] >= 1
    assert households[0]["contact_method_count"] >= 1
    assert households[0]["primary_phone"].startswith("***-***-")
    assert "@" in households[0]["primary_email"]
    assert "ada@example.com" not in json.dumps(households)
    detail = client.get(f"/api/admin/registry/households/{households[0]['id']}")
    assert detail.status_code == 200
    body = detail.json()
    assert body["people"]
    assert body["contact_methods"]
    assert body["external_records"]
    assert body["recommendations"]
    assert body["consent_events"]
    assert any(contact["normalized_value"].endswith(("0101", "0102")) for contact in body["contact_methods"])


def test_sankey_empty_graph(monkeypatch):
    if not HAS_AIOSQLITE:
        import pytest
        pytest.skip("aiosqlite is not installed in this local environment")
    monkeypatch.setenv("CLERK_ADMIN_USER_ID", "user_3ASrwDOrSTaDxCus6f1B5lnDsgz")
    sf = _run(_session_factory())
    client = TestClient(_make_app(sf))

    res = client.get("/api/admin/registry/sankey")
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["nodes"] == []
    assert body["links"] == []
    assert body["totals"]["households"] == 0
    assert body["level"] == "household"
    assert body["coverage_universe"] == 0
    assert body["source_coverage"] == [
        {"source": "close", "label": "Close", "total": 0, "matched": 0, "missing": 0, "match_pct": 0.0},
        {"source": "ghl", "label": "GHL", "total": 0, "matched": 0, "missing": 0, "match_pct": 0.0},
        {"source": "notion", "label": "Notion", "total": 0, "matched": 0, "missing": 0, "match_pct": 0.0},
        {"source": "lead_hygiene", "label": "Lead Hygiene", "total": 0, "matched": 0, "missing": 0, "match_pct": 0.0},
    ]


def test_sankey_fixture_counts_and_no_raw_pii(tmp_path, monkeypatch):
    if not HAS_AIOSQLITE:
        import pytest
        pytest.skip("aiosqlite is not installed in this local environment")
    monkeypatch.setenv("CLERK_ADMIN_USER_ID", "user_3ASrwDOrSTaDxCus6f1B5lnDsgz")
    job_id = _install_report(tmp_path, monkeypatch)
    sf = _run(_session_factory())
    client = TestClient(_make_app(sf))
    assert client.post(f"/api/admin/registry/imports/lead-hygiene/{job_id}").status_code == 200

    res = client.get("/api/admin/registry/sankey")
    assert res.status_code == 200, res.text
    body = res.json()
    labels = {node["label"]: node["count"] for node in body["nodes"]}
    assert body["totals"]["households"] == 2
    assert labels["Close"] == 2
    assert labels["GHL"] == 1
    assert labels["Notion"] == 1
    assert labels["Lead Hygiene"] == 2
    coverage = {row["source"]: row for row in body["source_coverage"]}
    assert body["coverage_universe"] == 2
    assert coverage["close"] == {"source": "close", "label": "Close", "total": 2, "matched": 2, "missing": 0, "match_pct": 100.0}
    assert coverage["ghl"] == {"source": "ghl", "label": "GHL", "total": 2, "matched": 1, "missing": 1, "match_pct": 50.0}
    assert coverage["notion"] == {"source": "notion", "label": "Notion", "total": 2, "matched": 1, "missing": 1, "match_pct": 50.0}
    assert coverage["lead_hygiene"] == {"source": "lead_hygiene", "label": "Lead Hygiene", "total": 2, "matched": 2, "missing": 0, "match_pct": 100.0}
    assert labels["High"] >= 1
    assert labels["Medium"] >= 1
    assert labels["Needs review"] >= 1
    assert labels["Do not contact"] >= 1
    risk_to_bucket_total = sum(
        link["value"] for link in body["links"]
        if link["source"].startswith("risk:") and link["target"].startswith("bucket:")
    )
    bucket_to_state_total = sum(
        link["value"] for link in body["links"]
        if link["source"].startswith("bucket:") and link["target"].startswith("state:")
    )
    assert risk_to_bucket_total == body["totals"]["households"]
    assert bucket_to_state_total == body["totals"]["households"]
    payload_text = json.dumps(body)
    forbidden = [
        "Ada",
        "Grace",
        "4805550101",
        "4805550102",
        "ada@example.com",
        "grace@example.com",
        "lead_close_1",
        "ghl_1",
        "notion_1",
    ]
    assert not any(value in payload_text for value in forbidden)


def test_sankey_source_coverage_counts_households_not_records(tmp_path, monkeypatch):
    if not HAS_AIOSQLITE:
        import pytest
        pytest.skip("aiosqlite is not installed in this local environment")
    monkeypatch.setenv("CLERK_ADMIN_USER_ID", "user_3ASrwDOrSTaDxCus6f1B5lnDsgz")
    job_id = _install_report(tmp_path, monkeypatch)
    sf = _run(_session_factory())
    client = TestClient(_make_app(sf))
    assert client.post(f"/api/admin/registry/imports/lead-hygiene/{job_id}").status_code == 200

    async def _add_duplicate_close_record():
        async with sf() as session:
            household = await session.scalar(
                select(RegistryHousehold).where(RegistryHousehold.display_name == "Ada Lovelace")
            )
            session.add(
                RegistryExternalRecord(
                    household_id=household.id,
                    source="close",
                    external_type="lead",
                    external_id="lead_close_extra",
                    match_basis="test",
                )
            )
            await session.commit()

    _run(_add_duplicate_close_record())

    res = client.get("/api/admin/registry/sankey")
    assert res.status_code == 200, res.text
    coverage = {row["source"]: row for row in res.json()["source_coverage"]}
    assert coverage["close"]["total"] == 2
    assert coverage["close"]["matched"] == 2
    assert coverage["close"]["missing"] == 0


def test_household_rollups_and_filters(tmp_path, monkeypatch):
    if not HAS_AIOSQLITE:
        import pytest
        pytest.skip("aiosqlite is not installed in this local environment")
    monkeypatch.setenv("CLERK_ADMIN_USER_ID", "user_3ASrwDOrSTaDxCus6f1B5lnDsgz")
    job_id = _install_report(tmp_path, monkeypatch)
    sf = _run(_session_factory())
    client = TestClient(_make_app(sf))
    assert client.post(f"/api/admin/registry/imports/lead-hygiene/{job_id}").status_code == 200

    households = client.get("/api/admin/registry/households?sort=risk").json()
    assert len(households) == 2
    grace = next(item for item in households if item["display_name"] == "Grace Hopper")
    ada = next(item for item in households if item["display_name"] == "Ada Lovelace")
    assert grace["people_count"] == 1
    assert grace["phone_count"] == 1
    assert grace["email_count"] == 1
    assert grace["recommendation_count"] == 1
    assert grace["high_risk_recommendation_count"] == 1
    assert grace["hard_stop_count"] == 1
    assert grace["bucket_counts"]["do-not-contact"] == 1
    assert "close" in grace["sources"]
    assert "lead_hygiene" in grace["sources"]
    assert ada["source_count"] >= 3

    high = client.get("/api/admin/registry/households?risk=high").json()
    assert [item["display_name"] for item in high] == ["Grace Hopper"]
    close = client.get("/api/admin/registry/households?source=close").json()
    assert {item["display_name"] for item in close} == {"Ada Lovelace", "Grace Hopper"}
    bucket = client.get("/api/admin/registry/households?bucket=needs-review").json()
    assert [item["display_name"] for item in bucket] == ["Ada Lovelace"]
    conflict = client.get("/api/admin/registry/households?has_conflict=true").json()
    assert [item["display_name"] for item in conflict] == ["Grace Hopper"]


def test_duplicate_phone_different_last_names_do_not_merge(tmp_path, monkeypatch):
    if not HAS_AIOSQLITE:
        import pytest
        pytest.skip("aiosqlite is not installed in this local environment")
    monkeypatch.setenv("CLERK_ADMIN_USER_ID", "user_3ASrwDOrSTaDxCus6f1B5lnDsgz")
    rows = [
        {
            "lead_name": "Ada Lovelace",
            "phone": "(480) 555-0101",
            "email": "ada@example.com",
            "close_lead_id": "lead_close_1",
            "recommended_bucket": "duplicate",
            "risk_flags": ["duplicate_phone"],
            "reason": "Phone appears on multiple Close leads.",
            "confidence": 0.82,
        },
        {
            "lead_name": "Grace Hopper",
            "phone": "(480) 555-0101",
            "email": "grace@example.com",
            "close_lead_id": "lead_close_2",
            "recommended_bucket": "duplicate",
            "risk_flags": ["duplicate_phone"],
            "reason": "Phone appears on multiple Close leads.",
            "confidence": 0.79,
        },
    ]
    job_id = _install_report(tmp_path, monkeypatch, rows=rows)
    sf = _run(_session_factory())
    client = TestClient(_make_app(sf))

    res = client.post(f"/api/admin/registry/imports/lead-hygiene/{job_id}")
    assert res.status_code == 200, res.text
    assert res.json()["households_created"] == 2

    households = client.get("/api/admin/registry/households").json()
    assert len(households) == 2
    assert {item["display_name"] for item in households} == {"Ada Lovelace", "Grace Hopper"}

    phone_search = client.get("/api/admin/registry/search?q=4805550101")
    assert phone_search.status_code == 200
    phone_body = phone_search.json()
    assert phone_body["contact_methods"] == []
    assert phone_body["external_records"] == []
    assert {item["display_name"] for item in phone_body["households"]} == {"Ada Lovelace", "Grace Hopper"}
    assert "4805550101" not in json.dumps(phone_body)


def test_connections_masks_secrets(monkeypatch):
    if not HAS_AIOSQLITE:
        import pytest
        pytest.skip("aiosqlite is not installed in this local environment")
    monkeypatch.setenv("CLERK_ADMIN_USER_ID", "user_3ASrwDOrSTaDxCus6f1B5lnDsgz")
    monkeypatch.setenv("CLOSE_API_KEY", "close_secret_value")
    monkeypatch.setenv("GHL_API_KEY", "ghl_secret_value")
    sf = _run(_session_factory())
    client = TestClient(_make_app(sf))

    res = client.get("/api/admin/registry/connections")
    assert res.status_code == 200
    text = res.text
    assert "close_secret_value" not in text
    assert "ghl_secret_value" not in text
    assert {item["secret"] for item in res.json()} == {"masked"}


def test_registry_code_has_read_only_boundary():
    source = Path("services/registry/service.py").read_text()
    forbidden = [".post(", ".put(", ".patch(", ".delete(", "add_tag", "remove_tag", "status_update"]
    assert not any(token in source for token in forbidden)
    assert "close_client" not in source
    assert "ghl_dashboard_client" not in source
    assert "services.notion" not in source


def test_disabled_registry_returns_503(monkeypatch):
    monkeypatch.setenv("CLERK_ADMIN_USER_ID", "user_3ASrwDOrSTaDxCus6f1B5lnDsgz")
    monkeypatch.setattr(registry_router, "REGISTRY_V1_ENABLED", False)
    client = TestClient(_make_app(session_factory=None))

    res = client.get("/api/admin/registry/connections")
    assert res.status_code == 503


def test_source_import_shell_returns_501(monkeypatch):
    monkeypatch.setenv("CLERK_ADMIN_USER_ID", "user_3ASrwDOrSTaDxCus6f1B5lnDsgz")
    client = TestClient(_make_app(session_factory=None))

    res = client.post("/api/admin/registry/imports/source/close")
    assert res.status_code == 501

    unknown = client.post("/api/admin/registry/imports/source/salesforce")
    assert unknown.status_code == 404
