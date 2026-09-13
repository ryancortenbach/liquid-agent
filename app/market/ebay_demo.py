from __future__ import annotations

from hashlib import sha256

from app.market.ebay import EbayDraft, EbayOfferInput, EbayPublication


def _demo_id(prefix: str, value: str) -> str:
    digest = sha256(value.encode()).hexdigest()[:12]
    return f"{prefix}-{digest}"


class DemoEbayPublisher:
    """Local eBay substitute used while application credentials are unavailable."""

    async def create_draft(self, offer: EbayOfferInput) -> EbayDraft:
        return EbayDraft(offer_id=_demo_id("demo-offer", offer.sku), sku=offer.sku)

    async def publish(self, offer_id: str, marketplace_id: str) -> EbayPublication:
        listing_id = _demo_id("demo-listing", f"{marketplace_id}:{offer_id}")
        return EbayPublication(offer_id=offer_id, listing_id=listing_id)

    async def close(self) -> None:
        return None
