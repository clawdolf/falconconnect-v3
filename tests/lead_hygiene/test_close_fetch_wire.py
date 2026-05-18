"""Wire-level coverage: _fetch_close_leads_live sends query=status:"…" to Close.

Mocks httpx.AsyncClient so no network traffic is generated; asserts that the
GET params actually leaving the function use the search-syntax query, never
the silently-ignored status_label= parameter.
"""

import asyncio
from types import SimpleNamespace

import pytest

import services.lead_hygiene_collect as collect


class _StubResponse:
    def __init__(self, data):
        self._data = data

    def raise_for_status(self):
        return None

    def json(self):
        return {"data": self._data}


class _StubClient:
    """Stand-in for httpx.AsyncClient. Records every GET it sees."""

    def __init__(self, *_, **__):
        self.calls: list[tuple[str, dict]] = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def get(self, url, params=None, **_kw):
        self.calls.append((url, dict(params or {})))
        # First call: lead list. Subsequent: activity list (per lead).
        if "/lead/" in url and "/activity/" not in url:
            return _StubResponse([])
        return _StubResponse([])


@pytest.fixture
def stub_client(monkeypatch):
    calls: list = []

    def _factory(*args, **kwargs):
        c = _StubClient(*args, **kwargs)
        calls.append(c)
        return c

    monkeypatch.setattr(collect.httpx, "AsyncClient", _factory)
    return calls


def test_live_fetch_sends_query_status_not_status_label(stub_client):
    asyncio.run(collect._fetch_close_leads_live(
        api_key="dummy", limit=10, status_label="Voicemail",
    ))
    assert stub_client, "AsyncClient was never constructed"
    client = stub_client[0]
    assert client.calls, "No GET issued"
    url, params = client.calls[0]
    assert url.endswith("/lead/")
    assert params.get("query") == 'status:"Voicemail"'
    assert "status_label" not in params
    assert "status" not in params
    assert params["_limit"] == 10
    assert params["_skip"] == 0


def test_live_fetch_combines_status_with_extra_query(stub_client):
    asyncio.run(collect._fetch_close_leads_live(
        api_key="dummy", limit=5, status_label="Voicemail",
        extra_query='lead_age:"60+ Mo"',
    ))
    client = stub_client[0]
    _url, params = client.calls[0]
    assert params["query"] == '(lead_age:"60+ Mo") AND status:"Voicemail"'


def test_live_fetch_with_no_status_sends_no_query(stub_client):
    asyncio.run(collect._fetch_close_leads_live(
        api_key="dummy", limit=10, status_label=None,
    ))
    client = stub_client[0]
    _url, params = client.calls[0]
    assert "query" not in params
    assert "status_label" not in params
