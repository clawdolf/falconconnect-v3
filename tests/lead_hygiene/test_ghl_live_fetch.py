import asyncio

from services import lead_hygiene_collect as collect


class _FakeResponse:
    def __init__(self, status_code, payload=None):
        self.status_code = status_code
        self._payload = payload or {}
        self.text = str(self._payload)

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code < 400:
            return
        import httpx

        request = httpx.Request("GET", "https://services.leadconnectorhq.com/contacts/bad")
        response = httpx.Response(self.status_code, request=request, json=self._payload)
        raise httpx.HTTPStatusError("boom", request=request, response=response)


class _FakeAsyncClient:
    def __init__(self, *args, **kwargs):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def get(self, url):
        if url.endswith("/bad-ghl-id"):
            return _FakeResponse(400, {"message": "invalid contact id"})
        return _FakeResponse(200, {"contact": {"id": "good-ghl-id", "tags": ["rvm-staging"]}})


def test_ghl_contact_400_is_treated_as_missing_contact(monkeypatch):
    monkeypatch.setattr(collect.httpx, "AsyncClient", _FakeAsyncClient)

    result = asyncio.run(collect._fetch_ghl_contact_live("key", "bad-ghl-id"))

    assert result is None


def test_ghl_contact_200_returns_contact(monkeypatch):
    monkeypatch.setattr(collect.httpx, "AsyncClient", _FakeAsyncClient)

    result = asyncio.run(collect._fetch_ghl_contact_live("key", "good-ghl-id"))

    assert result == {"id": "good-ghl-id", "tags": ["rvm-staging"]}
