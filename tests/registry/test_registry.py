from __future__ import annotations

import asyncio
import importlib.util
import json
from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from db.database import get_session
from db.models import (
    Base,
    RegistryConsentEvent,
    RegistryContactMethod,
    RegistryExternalRecord,
    RegistryHousehold,
    RegistryPerson,
    RegistryRecommendation,
    RegistrySourceSnapshot,
)
from middleware.auth import require_auth
from routers.registry import router
import routers.registry as registry_router
from services import lead_hygiene_jobs as jobs
from services.lead_hygiene import normalize_phone
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
]


def _run(coro):
    return asyncio.run(coro)


def _make_app(session_factory, user_id: str | None = "user_3ASrwDOrSTaDxCus6f1B5lnDsgz") -> FastAPI:
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
    assert phone_search.json()["contact_methods"][0]["normalized_value"] == normalize_phone("4805550101")

    email_search = client.get("/api/admin/registry/search?q=grace@example.com")
    assert email_search.status_code == 200
    assert email_search.json()["contact_methods"][0]["normalized_value"] == "grace@example.com"

    name_search = client.get("/api/admin/registry/search?q=Ada")
    assert name_search.status_code == 200
    assert name_search.json()["people"][0]["display_name"] == "Ada Lovelace"

    households = client.get("/api/admin/registry/households").json()
    detail = client.get(f"/api/admin/registry/households/{households[0]['id']}")
    assert detail.status_code == 200
    body = detail.json()
    assert body["people"]
    assert body["contact_methods"]
    assert body["external_records"]
    assert body["recommendations"]
    assert body["consent_events"]


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
    assert len(phone_search.json()["contact_methods"]) == 2


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
