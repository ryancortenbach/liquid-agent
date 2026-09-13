from __future__ import annotations

import base64
import time

import httpx

from app.research.sources import CompKind, CompRecord

PROD_BASE = "https://api.ebay.com"
BROWSE_SCOPE = "https://api.ebay.com/oauth/api_scope"


class EbayBrowseSource:
    """Active eBay listings through the official Browse API (client-credentials token)."""

    name = "ebay:browse"

    def __init__(
        self,
        client_id: str,
        client_secret: str,
        *,
        marketplace_id: str = "EBAY_US",
        client: httpx.AsyncClient | None = None,
        base_url: str = PROD_BASE,
    ) -> None:
        self.client_id = client_id
        self.client_secret = client_secret
        self.marketplace_id = marketplace_id
        self.base_url = base_url
        self._client = client or httpx.AsyncClient(timeout=20)
        self._token: str | None = None
        self._token_expires_at: float = 0

    async def close(self) -> None:
        await self._client.aclose()

    async def _access_token(self) -> str:
        if self._token and time.time() < self._token_expires_at - 300:
            return self._token
        basic = base64.b64encode(f"{self.client_id}:{self.client_secret}".encode()).decode()
        response = await self._client.post(
            f"{self.base_url}/identity/v1/oauth2/token",
            headers={
                "Authorization": f"Basic {basic}",
                "Content-Type": "application/x-www-form-urlencoded",
            },
            data={"grant_type": "client_credentials", "scope": BROWSE_SCOPE},
        )
        response.raise_for_status()
        payload = response.json()
        self._token = payload["access_token"]
        self._token_expires_at = time.time() + float(payload.get("expires_in", 7200))
        return self._token

    async def search(self, query: str, *, kind: CompKind, max_results: int) -> list[CompRecord]:
        if kind != "active":
            return []
        token = await self._access_token()
        response = await self._client.get(
            f"{self.base_url}/buy/browse/v1/item_summary/search",
            headers={
                "Authorization": f"Bearer {token}",
                "X-EBAY-C-MARKETPLACE-ID": self.marketplace_id,
            },
            params={
                "q": query,
                "filter": "conditions:{USED},buyingOptions:{FIXED_PRICE},priceCurrency:USD",
                "limit": min(max_results, 200),
            },
        )
        response.raise_for_status()
        records: list[CompRecord] = []
        for summary in response.json().get("itemSummaries", []):
            price = summary.get("price") or {}
            try:
                price_cents = int(round(float(price.get("value", 0)) * 100))
            except (TypeError, ValueError):
                continue
            if price_cents <= 0:
                continue
            records.append(
                CompRecord(
                    title=summary.get("title", ""),
                    price_cents=price_cents,
                    kind="active",
                    source=self.name,
                    url=summary.get("itemWebUrl"),
                    condition=summary.get("condition"),
                    image_url=(summary.get("image") or {}).get("imageUrl"),
                )
            )
        return records
