"""Async GHL API v2 client for read-only dashboard intel.

Uses httpx (already in requirements.txt) instead of aiohttp.
GHL v2 uses cursor-based pagination (startAfter/startAfterId), not offset.
"""

import asyncio
import logging
from typing import Any

import httpx

logger = logging.getLogger("ghl_dashboard_client")


class GHLDashboardClient:
    """Read-only async client for GHL API v2 (Services endpoint)."""

    BASE_URL = "https://services.leadconnectorhq.com"
    API_VERSION = "2021-07-28"
    RATE_LIMIT_DELAY = 0.1  # 100ms between requests = max 10 req/s

    def __init__(self, private_token: str, location_id: str):
        self.private_token = private_token
        self.location_id = location_id

    def _headers(self) -> dict:
        return {
            "Authorization": f"Bearer {self.private_token}",
            "Version": self.API_VERSION,
            "Content-Type": "application/json",
        }

    async def _get(self, endpoint: str, params: dict | None = None) -> dict | list:
        """Make authenticated GET request with rate limiting."""
        url = f"{self.BASE_URL}{endpoint}"
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.get(url, headers=self._headers(), params=params)
                if resp.status_code == 200:
                    return resp.json()
                else:
                    body = resp.text[:200]
                    logger.warning("GHL API %s returned %s: %s", endpoint, resp.status_code, body)
                    return {}
        except Exception as exc:
            logger.error("GHL API %s failed: %s", endpoint, exc)
            return {}
        finally:
            await asyncio.sleep(self.RATE_LIMIT_DELAY)

    async def get_contacts(self, limit: int = 100, start_after: int | None = None, start_after_id: str | None = None) -> dict:
        """Fetch contacts for location. Returns full response dict with contacts + meta."""
        params: dict[str, Any] = {
            "locationId": self.location_id,
            "limit": min(limit, 100),
        }
        if start_after is not None:
            params["startAfter"] = start_after
        if start_after_id is not None:
            params["startAfterId"] = start_after_id
        result = await self._get("/contacts/", params)
        return result if isinstance(result, dict) else {"contacts": [], "meta": {}}

    async def get_contacts_count(self) -> int:
        """Get total contact count without fetching all data."""
        result = await self.get_contacts(limit=1)
        return result.get("meta", {}).get("total", len(result.get("contacts", [])))

    async def get_pipelines(self) -> list[dict]:
        """Fetch all pipelines for location."""
        result = await self._get("/pipelines/", {"locationId": self.location_id})
        return result.get("pipelines", []) if isinstance(result, dict) else []

    async def get_opportunities(self, pipeline_id: str, limit: int = 100) -> list[dict]:
        """Fetch opportunities for a pipeline."""
        params = {
            "locationId": self.location_id,
            "pipelineId": pipeline_id,
            "limit": min(limit, 100),
        }
        result = await self._get("/opportunities/search", params)
        return result.get("opportunities", []) if isinstance(result, dict) else []

    async def get_conversations(self, limit: int = 100) -> list[dict]:
        """Fetch recent conversations for location."""
        params = {
            "locationId": self.location_id,
            "limit": min(limit, 100),
        }
        result = await self._get("/conversations/search", params)
        return result.get("conversations", []) if isinstance(result, dict) else []
