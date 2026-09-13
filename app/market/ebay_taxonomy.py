"""Pick the eBay category for an item.

Order of preference: an explicit category id, a live suggestion from the production Taxonomy API
(the sandbox returns boilerplate for suggestions, but its category ids match production), the
operator's EBAY_SB_DEFAULT_CATEGORY_ID, then a small map of leaf categories for the item kinds the
identifier emits. Publishing never stalls on "no category".
"""

from __future__ import annotations

import base64
import logging
import time
from dataclasses import dataclass

import httpx

from app.market.ebay import BASE_SCOPE

PROD_BASE = "https://api.ebay.com"
log = logging.getLogger(__name__)

# Leaf categories on EBAY_US for the identifier's category vocabulary.
FALLBACK_CATEGORY_IDS: dict[str, str] = {
    "headphones": "112529",  # Consumer Electronics > Portable Audio & Headphones > Headphones
    "tablet": "171485",  # Computers/Tablets & Networking > Tablets & eBook Readers
    "computer": "177",  # Computers/Tablets & Networking > Laptops & Netbooks > PC Laptops
    "phone": "9355",  # Cell Phones & Accessories > Cell Phones & Smartphones
    "camera": "31388",  # Cameras & Photo > Digital Cameras
}
LAST_RESORT_CATEGORY_ID = "88433"  # Everything Else > Every Other Thing


@dataclass(frozen=True, slots=True)
class CategorySuggestion:
    category_id: str
    name: str
    path: str


@dataclass(frozen=True, slots=True)
class ResolvedCategory:
    category_id: str
    source: str  # explicit | suggested | default | fallback | last_resort
    name: str | None = None


class EbayTaxonomyClient:
    """Production Taxonomy API with a client-credentials token (no seller login needed)."""

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
        self._owns_client = client is None
        self._token: str | None = None
        self._token_expires_at: float = 0
        self._tree_id: str | None = None
        self._cache: dict[str, CategorySuggestion | None] = {}

    async def close(self) -> None:
        if self._owns_client:
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
            data={"grant_type": "client_credentials", "scope": BASE_SCOPE},
        )
        response.raise_for_status()
        payload = response.json()
        self._token = payload["access_token"]
        self._token_expires_at = time.time() + float(payload.get("expires_in", 7200))
        return self._token

    async def category_tree_id(self) -> str:
        if self._tree_id:
            return self._tree_id
        token = await self._access_token()
        response = await self._client.get(
            f"{self.base_url}/commerce/taxonomy/v1/get_default_category_tree_id",
            headers={"Authorization": f"Bearer {token}"},
            params={"marketplace_id": self.marketplace_id},
        )
        response.raise_for_status()
        self._tree_id = str(response.json()["categoryTreeId"])
        return self._tree_id

    async def suggest(self, query: str) -> CategorySuggestion | None:
        key = " ".join(query.lower().split())
        if not key:
            return None
        if key in self._cache:
            return self._cache[key]
        token = await self._access_token()
        tree_id = await self.category_tree_id()
        response = await self._client.get(
            f"{self.base_url}/commerce/taxonomy/v1/category_tree/{tree_id}"
            "/get_category_suggestions",
            headers={"Authorization": f"Bearer {token}"},
            params={"q": key[:350]},
        )
        response.raise_for_status()
        suggestion: CategorySuggestion | None = None
        for entry in response.json().get("categorySuggestions") or []:
            category = entry.get("category") or {}
            category_id = category.get("categoryId")
            if not category_id:
                continue
            ancestors = [
                str(node.get("categoryName", ""))
                for node in reversed(entry.get("categoryTreeNodeAncestors") or [])
            ]
            name = str(category.get("categoryName", ""))
            suggestion = CategorySuggestion(
                category_id=str(category_id),
                name=name,
                path=" > ".join(part for part in [*ancestors, name] if part),
            )
            break
        self._cache[key] = suggestion
        return suggestion


async def resolve_category(
    *,
    explicit: str | None,
    query: str,
    item_category: str | None,
    default: str | None,
    taxonomy: EbayTaxonomyClient | None,
) -> ResolvedCategory:
    if explicit:
        return ResolvedCategory(explicit, "explicit")
    if taxonomy is not None:
        try:
            suggestion = await taxonomy.suggest(query)
        except Exception as exc:  # network or auth trouble must not block publishing
            log.warning("eBay category suggestion failed for %r: %s", query, exc)
            suggestion = None
        if suggestion is not None:
            return ResolvedCategory(suggestion.category_id, "suggested", suggestion.path)
    if default:
        return ResolvedCategory(default, "default")
    fallback = FALLBACK_CATEGORY_IDS.get((item_category or "").lower())
    if fallback:
        return ResolvedCategory(fallback, "fallback")
    return ResolvedCategory(LAST_RESORT_CATEGORY_ID, "last_resort")
