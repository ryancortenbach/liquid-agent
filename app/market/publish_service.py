from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from urllib.parse import urlparse

from sqlalchemy import Engine
from sqlmodel import Session, select

from app.clock import Clock
from app.config import Settings
from app.ledger import write_decision
from app.market.ebay import EbayError, EbayOfferInput, EbayPublisher
from app.models import Item, ItemStatus, Listing, ListingStatus, PhotoStatus, ProductPhoto

CONDITION_ENUM = {"A": "USED_EXCELLENT", "B": "USED_VERY_GOOD", "C": "USED_ACCEPTABLE"}


class EbayPublishError(RuntimeError):
    def __init__(self, status_code: int, detail: str) -> None:
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


@dataclass(frozen=True, slots=True)
class EbayPublishResult:
    status: str  # live | draft
    listing_id: str | None = None
    offer_id: str | None = None
    seller_approved: bool = False

    def as_dict(self) -> dict:
        if self.status == "live":
            return {
                "status": "live",
                "listing_id": self.listing_id,
                "seller_approved": True,
            }
        return {"status": "draft", "offer_id": self.offer_id, "seller_approved": False}


def sandbox_listing_url(listing_id: str) -> str:
    return f"https://www.sandbox.ebay.com/itm/{listing_id}"


async def publish_item_to_ebay(
    *,
    engine: Engine,
    settings: Settings,
    publisher: EbayPublisher | None,
    publisher_for_seller: Callable[[str], EbayPublisher | None] | None = None,
    clock: Clock,
    item_id: str,
    seller_approved: bool,
    price_cents: int | None = None,
    category_id: str | None = None,
    title: str | None = None,
    description: str | None = None,
    aspects: dict[str, list[str]] | None = None,
) -> EbayPublishResult:
    """Create (and, when approved, publish) the eBay sandbox offer for an item.

    Raises EbayPublishError with an HTTP-style status code so callers can map it.
    """
    with Session(engine) as session:
        owner = session.get(Item, item_id)
        if owner is None:
            raise EbayPublishError(404, "item not found")
        seller_id = owner.seller_id
    if publisher_for_seller is not None:
        publisher = publisher_for_seller(seller_id) or publisher
    if publisher is None:
        raise EbayPublishError(503, "connect eBay before publishing")
    required_settings = {
        "merchant location": settings.ebay_sb_merchant_location_key,
        "payment policy": settings.ebay_sb_payment_policy_id,
        "return policy": settings.ebay_sb_return_policy_id,
        "fulfillment policy": settings.ebay_sb_fulfillment_policy_id,
    }
    missing = [name for name, value in required_settings.items() if not value]
    category = category_id or settings.ebay_sb_default_category_id
    if not category:
        missing.append("category")
    if missing:
        raise EbayPublishError(503, f"eBay sandbox setup is missing: {', '.join(missing)}")
    if not aspects:
        raise EbayPublishError(422, "at least one truthful item aspect is required")
    public_url = urlparse(settings.public_base_url)
    if public_url.scheme != "https" or public_url.hostname in {"localhost", "127.0.0.1"}:
        raise EbayPublishError(503, "PUBLIC_BASE_URL must be a public HTTPS URL for eBay images")

    with Session(engine) as session:
        item = session.get(Item, item_id)
        if item is None:
            raise EbayPublishError(404, "item not found")
        approved_photos = session.exec(
            select(ProductPhoto).where(
                ProductPhoto.item_id == item_id, ProductPhoto.status == PhotoStatus.APPROVED
            )
        ).all()
        if not approved_photos:
            raise EbayPublishError(
                409, "approve at least one enhanced photo before preparing an eBay listing"
            )
        listing = session.exec(
            select(Listing).where(Listing.item_id == item_id, Listing.channel == "ebay")
        ).first()
        if listing is not None and listing.external_id and listing.status == ListingStatus.LIVE:
            return EbayPublishResult("live", listing_id=listing.external_id, seller_approved=True)
        resolved_price = price_cents or (listing.price_cents if listing else 0)
        if resolved_price <= 0:
            resolved_price = item.market_value_cents
        offer_id = (
            listing.external_id if listing and listing.status == ListingStatus.DRAFT else None
        )
        base = settings.public_base_url.rstrip("/")
        offer = EbayOfferInput(
            sku=f"liquid-{item.id}",
            title=(title or item.title)[:80],
            description=description or f"{item.title}. Seller-provided item photo.",
            condition=CONDITION_ENUM[item.condition.value],
            aspects=aspects,
            image_urls=[f"{base}/api/photos/{photo.id}/file" for photo in approved_photos],
            category_id=category or "",
            marketplace_id=settings.ebay_marketplace_id,
            currency=settings.ebay_currency,
            price_cents=resolved_price,
            merchant_location_key=settings.ebay_sb_merchant_location_key or "",
            payment_policy_id=settings.ebay_sb_payment_policy_id or "",
            return_policy_id=settings.ebay_sb_return_policy_id or "",
            fulfillment_policy_id=settings.ebay_sb_fulfillment_policy_id or "",
        )

    try:
        if offer_id is None:
            draft = await publisher.create_draft(offer)
            offer_id = draft.offer_id
            with Session(engine) as session:
                listing = session.exec(
                    select(Listing).where(Listing.item_id == item_id, Listing.channel == "ebay")
                ).first()
                if listing is None:
                    listing = Listing(item_id=item_id, channel="ebay", price_cents=resolved_price)
                listing.external_id = offer_id
                listing.price_cents = resolved_price
                listing.status = ListingStatus.DRAFT
                session.add(listing)
                session.commit()
        if not seller_approved:
            return EbayPublishResult("draft", offer_id=offer_id, seller_approved=False)
        publication = await publisher.publish(offer_id, settings.ebay_marketplace_id)
    except EbayError as exc:
        raise EbayPublishError(502, str(exc)) from exc

    with Session(engine) as session:
        item = session.get(Item, item_id)
        listing = session.exec(
            select(Listing).where(Listing.item_id == item_id, Listing.channel == "ebay")
        ).one()
        listing.external_id = publication.listing_id
        listing.status = ListingStatus.LIVE
        listing.published_at = clock.now()
        if item is not None:
            item.status = ItemStatus.LIVE
            session.add(item)
        session.add(listing)
        write_decision(
            session,
            item_id=item_id,
            sim_at=clock.now(),
            wall_at=clock.wall(),
            kind="seller",
            action="publish_ebay",
            inputs={
                "listing_id": publication.listing_id,
                "price_cents": listing.price_cents,
                "marketplace_id": settings.ebay_marketplace_id,
            },
            reason="seller approved publication to the eBay sandbox",
            price_before=None,
            price_after=listing.price_cents,
        )
        session.commit()
    return EbayPublishResult(
        "live", listing_id=publication.listing_id, offer_id=offer_id, seller_approved=True
    )
