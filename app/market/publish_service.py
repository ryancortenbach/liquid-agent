from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from urllib.parse import urlparse

from sqlalchemy import Engine
from sqlmodel import Session, select

from app.clock import Clock
from app.config import Settings
from app.ledger import write_decision
from app.market.ebay import EbayError, EbayOfferInput, EbayPublisher
from app.market.ebay_taxonomy import EbayTaxonomyClient, resolve_category
from app.models import Item, ItemStatus, Listing, ListingStatus, PhotoStatus, ProductPhoto
from app.photos.storage import PhotoStorage

CONDITION_ENUM = {"A": "USED_EXCELLENT", "B": "USED_VERY_GOOD", "C": "USED_ACCEPTABLE"}

# Photos already hosted on eBay Picture Services this process, by content hash. EPS keeps an
# unused picture for 30 days, far longer than any listing session.
_HOSTED_PICTURES: dict[str, str] = {}


def public_image_base(settings: Settings) -> str | None:
    """The base URL eBay could fetch photos from, or None when this machine is not reachable."""
    public_url = urlparse(settings.public_base_url)
    if public_url.scheme != "https" or public_url.hostname in {"localhost", "127.0.0.1"}:
        return None
    return settings.public_base_url.rstrip("/")


async def host_photos_on_ebay(
    uploader: Callable[..., Awaitable[str]],
    storage: PhotoStorage,
    photos: list[tuple[str, str, str, str]],
) -> list[str]:
    """Upload approved photos to eBay and return their hosted URLs (cached by content hash)."""
    urls: list[str] = []
    for photo_id, file_path, mime_type, sha256 in photos:
        cached = _HOSTED_PICTURES.get(sha256)
        if cached:
            urls.append(cached)
            continue
        path = storage.resolve(file_path)
        content = path.read_bytes()
        extension = path.suffix.lstrip(".") or "jpg"
        url = await uploader(
            content,
            filename=f"{photo_id}.{extension}",
            mime_type=mime_type,
            picture_name=f"liquid-{photo_id}",
        )
        _HOSTED_PICTURES[sha256] = url
        urls.append(url)
    return urls


class EbayPublishError(RuntimeError):
    def __init__(self, status_code: int, detail: str) -> None:
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


@dataclass(frozen=True, slots=True)
class EbayPublishResult:
    status: str  # live | draft | demo
    listing_id: str | None = None
    offer_id: str | None = None
    seller_approved: bool = False

    def as_dict(self) -> dict:
        if self.status in {"live", "demo"}:
            return {
                "status": self.status,
                "listing_id": self.listing_id,
                "seller_approved": True,
            }
        return {"status": "draft", "offer_id": self.offer_id, "seller_approved": False}


def sandbox_listing_url(listing_id: str) -> str:
    return f"https://www.sandbox.ebay.com/itm/{listing_id}"


def ebay_listing_url(listing_id: str, environment: str) -> str:
    if environment == "sandbox":
        return sandbox_listing_url(listing_id)
    return f"https://www.ebay.com/itm/{listing_id}"


def demo_listing_url(listing_id: str, public_base_url: str) -> str:
    return f"{public_base_url.rstrip('/')}/demo/ebay/listings/{listing_id}"


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
    taxonomy: EbayTaxonomyClient | None = None,
    photo_storage: PhotoStorage | None = None,
) -> EbayPublishResult:
    """Create (and, when approved, publish) the eBay sandbox offer for an item.

    Photos are served from PUBLIC_BASE_URL when that is a public HTTPS address; otherwise they are
    uploaded to eBay Picture Services through the publisher, so no tunnel is required. The category
    comes from the caller, a live Taxonomy suggestion, the configured default, or a fallback.
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
    if not settings.ebay_demo_mode:
        required_settings = {
            "merchant location": settings.ebay_sb_merchant_location_key,
            "payment policy": settings.ebay_sb_payment_policy_id,
            "return policy": settings.ebay_sb_return_policy_id,
            "fulfillment policy": settings.ebay_sb_fulfillment_policy_id,
        }
        missing = [name for name, value in required_settings.items() if not value]
        if missing:
            raise EbayPublishError(503, f"eBay sandbox setup is missing: {', '.join(missing)}")
    if not aspects:
        raise EbayPublishError(422, "at least one truthful item aspect is required")
    image_base = (
        settings.public_base_url.rstrip("/")
        if settings.ebay_demo_mode
        else public_image_base(settings)
    )
    if image_base is None and not callable(getattr(publisher, "upload_picture", None)):
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
            status = "demo" if settings.ebay_demo_mode else "live"
            return EbayPublishResult(status, listing_id=listing.external_id, seller_approved=True)
        resolved_price = price_cents or (listing.price_cents if listing else 0)
        if resolved_price <= 0:
            resolved_price = item.market_value_cents
        offer_id = (
            listing.external_id if listing and listing.status == ListingStatus.DRAFT else None
        )
        item_title = item.title
        item_condition = CONDITION_ENUM[item.condition.value]
        item_category = str(getattr(item, "category", "") or "")
        photo_refs = [
            (photo.id, photo.file_path, photo.mime_type, photo.sha256)
            for photo in approved_photos
        ]

    try:
        if offer_id is None:
            category = await resolve_category(
                explicit=category_id,
                query=title or item_title,
                item_category=item_category,
                default=settings.ebay_sb_default_category_id,
                taxonomy=taxonomy,
            )
            if image_base is not None:
                image_urls = [f"{image_base}/api/photos/{ref[0]}/file" for ref in photo_refs]
            else:
                storage = photo_storage or PhotoStorage(settings.photo_storage_dir)
                try:
                    image_urls = await host_photos_on_ebay(
                        publisher.upload_picture,  # type: ignore[attr-defined]
                        storage,
                        photo_refs,
                    )
                except (OSError, ValueError) as exc:
                    raise EbayPublishError(409, f"approved photo file unavailable: {exc}") from exc
            offer = EbayOfferInput(
                sku=f"liquid-{item_id}",
                title=(title or item_title)[:80],
                description=description or f"{item_title}. Seller-provided item photo.",
                condition=item_condition,
                aspects=aspects,
                image_urls=image_urls,
                category_id=category.category_id,
                marketplace_id=settings.ebay_marketplace_id,
                currency=settings.ebay_currency,
                price_cents=resolved_price,
                merchant_location_key=settings.ebay_sb_merchant_location_key or "",
                payment_policy_id=settings.ebay_sb_payment_policy_id or "",
                return_policy_id=settings.ebay_sb_return_policy_id or "",
                fulfillment_policy_id=settings.ebay_sb_fulfillment_policy_id or "",
            )
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
            reason=(
                "seller approved a simulated eBay publication"
                if settings.ebay_demo_mode
                else "seller approved publication to the eBay sandbox"
            ),
            price_before=None,
            price_after=listing.price_cents,
        )
        session.commit()
    return EbayPublishResult(
        "demo" if settings.ebay_demo_mode else "live",
        listing_id=publication.listing_id,
        offer_id=offer_id,
        seller_approved=True,
    )
