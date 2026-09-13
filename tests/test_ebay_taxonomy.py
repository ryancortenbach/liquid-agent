from __future__ import annotations

import httpx
import pytest

from app.market.ebay_taxonomy import (
    LAST_RESORT_CATEGORY_ID,
    CategorySuggestion,
    EbayTaxonomyClient,
    resolve_category,
)

SUGGESTIONS = {
    "categorySuggestions": [
        {
            "category": {"categoryId": "112529", "categoryName": "Headphones"},
            "categoryTreeNodeLevel": 3,
            "categoryTreeNodeAncestors": [
                {"categoryId": "15052", "categoryName": "Portable Audio & Headphones"},
                {"categoryId": "293", "categoryName": "Consumer Electronics"},
            ],
        },
        {"category": {"categoryId": "999", "categoryName": "Other"}},
    ]
}


@pytest.mark.asyncio
async def test_suggest_returns_the_top_leaf_with_its_path() -> None:
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.path)
        if request.url.path == "/identity/v1/oauth2/token":
            assert b"client_credentials" in request.read()
            return httpx.Response(200, json={"access_token": "app-token", "expires_in": 7200})
        if request.url.path == "/commerce/taxonomy/v1/get_default_category_tree_id":
            assert request.url.params["marketplace_id"] == "EBAY_US"
            return httpx.Response(200, json={"categoryTreeId": "0", "categoryTreeVersion": "1"})
        if request.url.path == "/commerce/taxonomy/v1/category_tree/0/get_category_suggestions":
            assert request.url.params["q"] == "sony wh-1000xm5 headphones"
            return httpx.Response(200, json=SUGGESTIONS)
        return httpx.Response(404)

    taxonomy = EbayTaxonomyClient(
        "id", "secret", client=httpx.AsyncClient(transport=httpx.MockTransport(handler))
    )
    first = await taxonomy.suggest("Sony  WH-1000XM5 headphones")
    second = await taxonomy.suggest("sony wh-1000xm5 headphones")
    await taxonomy.close()

    assert first == CategorySuggestion(
        "112529", "Headphones", "Consumer Electronics > Portable Audio & Headphones > Headphones"
    )
    assert second == first
    assert calls.count("/commerce/taxonomy/v1/category_tree/0/get_category_suggestions") == 1


class StubTaxonomy:
    def __init__(self, result: CategorySuggestion | None = None, *, fail: bool = False) -> None:
        self.result = result
        self.fail = fail

    async def suggest(self, query: str) -> CategorySuggestion | None:
        if self.fail:
            raise RuntimeError("network down")
        return self.result


@pytest.mark.asyncio
async def test_resolve_category_prefers_explicit_then_suggestion_then_default() -> None:
    suggested = StubTaxonomy(CategorySuggestion("31388", "Digital Cameras", "Cameras > Digital"))
    explicit = await resolve_category(
        explicit="123", query="x", item_category="camera", default="9", taxonomy=suggested
    )
    assert (explicit.category_id, explicit.source) == ("123", "explicit")

    live = await resolve_category(
        explicit=None, query="Canon EOS", item_category="camera", default="9", taxonomy=suggested
    )
    assert (live.category_id, live.source, live.name) == ("31388", "suggested", "Cameras > Digital")

    default = await resolve_category(
        explicit=None, query="Canon EOS", item_category="camera", default="9",
        taxonomy=StubTaxonomy(fail=True),
    )
    assert (default.category_id, default.source) == ("9", "default")

    fallback = await resolve_category(
        explicit=None, query="Canon EOS", item_category="Camera", default=None, taxonomy=None
    )
    assert (fallback.category_id, fallback.source) == ("31388", "fallback")

    last = await resolve_category(
        explicit=None, query="mystery", item_category="furniture", default=None, taxonomy=None
    )
    assert (last.category_id, last.source) == (LAST_RESORT_CATEGORY_ID, "last_resort")
