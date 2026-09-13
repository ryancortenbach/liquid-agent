from __future__ import annotations

from typing import Any

import httpx

from app.research.sources import CompKind, CompRecord, normalize_record

APIFY_BASE = "https://api.apify.com/v2"
SOLD_ACTOR = "blackfalcondata~ebay-sold-listings-scraper"
ACTIVE_ACTOR = "logiover~ebay-scraper"


class ApifyClient:
    def __init__(
        self,
        token: str,
        *,
        client: httpx.AsyncClient | None = None,
        timeout_seconds: float = 180,
    ) -> None:
        self.token = token
        self._client = client or httpx.AsyncClient(timeout=timeout_seconds)

    async def close(self) -> None:
        await self._client.aclose()

    async def run_actor(self, actor_id: str, run_input: dict[str, Any]) -> list[dict[str, Any]]:
        """Run an actor synchronously and return its default dataset items."""
        response = await self._client.post(
            f"{APIFY_BASE}/acts/{actor_id}/run-sync-get-dataset-items",
            params={"token": self.token, "timeout": 170, "memory": 1024},
            json=run_input,
        )
        response.raise_for_status()
        payload = response.json()
        if isinstance(payload, dict):
            payload = payload.get("items") or payload.get("data") or []
        return [row for row in payload if isinstance(row, dict)]


class ApifySoldSource:
    name = "apify:ebay-sold"

    def __init__(self, client: ApifyClient, actor_id: str = SOLD_ACTOR) -> None:
        self.client = client
        self.actor_id = actor_id

    async def search(self, query: str, *, kind: CompKind, max_results: int) -> list[CompRecord]:
        if kind != "sold":
            return []
        rows = await self.client.run_actor(
            self.actor_id,
            {"query": query, "maxResults": max_results, "includeDetails": False, "country": "US"},
        )
        records = [normalize_record(row, kind="sold", source=self.name) for row in rows]
        return [record for record in records if record is not None]


class ApifyActiveSource:
    name = "apify:ebay-active"

    def __init__(self, client: ApifyClient, actor_id: str = ACTIVE_ACTOR) -> None:
        self.client = client
        self.actor_id = actor_id

    async def search(self, query: str, *, kind: CompKind, max_results: int) -> list[CompRecord]:
        mode = "sold" if kind == "sold" else "search"
        rows = await self.client.run_actor(
            self.actor_id,
            {"mode": mode, "query": query, "maxResults": max_results, "domain": "ebay.com"},
        )
        records = [normalize_record(row, kind=kind, source=self.name) for row in rows]
        return [record for record in records if record is not None]
