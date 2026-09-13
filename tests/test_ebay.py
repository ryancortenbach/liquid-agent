from __future__ import annotations

from datetime import UTC, datetime

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, select

from app.config import Mode, Settings
from app.main import create_app
from app.market.ebay import (
    EbayDraft,
    EbayOfferInput,
    EbayPublication,
    EbaySandboxClient,
)
from app.models import LedgerEvent, Listing, ListingStatus, PhotoRole, PhotoStatus, ProductPhoto


def sample_offer() -> EbayOfferInput:
    return EbayOfferInput(
        sku="liquid-item-1",
        title="Sony WH-1000XM5",
        description="Used Sony headphones in very good condition.",
        condition="USED_VERY_GOOD",
        aspects={"Brand": ["Sony"], "Model": ["WH-1000XM5"]},
        image_urls=["https://liquid.example/api/photos/photo-1/file"],
        category_id="112529",
        marketplace_id="EBAY_US",
        currency="USD",
        price_cents=20_500,
        merchant_location_key="home",
        payment_policy_id="payment-policy",
        return_policy_id="return-policy",
        fulfillment_policy_id="fulfillment-policy",
    )


@pytest.mark.asyncio
async def test_ebay_sandbox_inventory_offer_and_publish_calls() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path == "/identity/v1/oauth2/token":
            return httpx.Response(200, json={"access_token": "access-token", "expires_in": 7200})
        if request.url.path.startswith("/sell/inventory/v1/inventory_item/"):
            return httpx.Response(204)
        if request.url.path == "/sell/inventory/v1/offer":
            return httpx.Response(201, json={"offerId": "offer-123"})
        if request.url.path == "/sell/inventory/v1/offer/offer-123/publish":
            return httpx.Response(200, json={"listingId": "listing-456"})
        return httpx.Response(404)

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    ebay = EbaySandboxClient("client-id", "client-secret", "refresh-token", client=client)

    draft = await ebay.create_draft(sample_offer())
    publication = await ebay.publish(draft.offer_id, "EBAY_US")

    assert draft == EbayDraft(offer_id="offer-123", sku="liquid-item-1")
    assert publication == EbayPublication(offer_id="offer-123", listing_id="listing-456")
    assert [request.method for request in requests] == ["POST", "PUT", "POST", "POST"]
    inventory_payload = requests[1].read().decode()
    offer_payload = requests[2].read().decode()
    assert '"imageUrls":["https://liquid.example/api/photos/photo-1/file"]' in inventory_payload
    assert '"value":"205.00"' in offer_payload
    assert requests[3].headers["x-ebay-c-marketplace-id"] == "EBAY_US"
    await client.aclose()


class FakeEbayPublisher:
    def __init__(self) -> None:
        self.drafts: list[EbayOfferInput] = []
        self.published: list[tuple[str, str]] = []

    async def close(self) -> None:
        return None

    async def create_draft(self, offer: EbayOfferInput) -> EbayDraft:
        self.drafts.append(offer)
        return EbayDraft(offer_id="offer-123", sku=offer.sku)

    async def publish(self, offer_id: str, marketplace_id: str) -> EbayPublication:
        self.published.append((offer_id, marketplace_id))
        return EbayPublication(offer_id=offer_id, listing_id="listing-456")


def ebay_settings(tmp_path) -> Settings:
    return Settings(
        mode=Mode.SIM,
        database_url="sqlite:///:memory:",
        photo_storage_dir=str(tmp_path),
        public_base_url="https://liquid.example",
        ebay_sb_merchant_location_key="home",
        ebay_sb_payment_policy_id="payment-policy",
        ebay_sb_return_policy_id="return-policy",
        ebay_sb_fulfillment_policy_id="fulfillment-policy",
        ebay_sb_default_category_id="112529",
    )


def create_item(client: TestClient) -> str:
    response = client.post(
        "/api/items",
        json={
            "seller_handle": "+14155550123",
            "title": "Sony WH-1000XM5",
            "brand": "Sony",
            "model": "WH-1000XM5",
            "market_value_cents": 20_500,
            "sigma_cents": 2_500,
            "floor_cents": 17_000,
            "deadline_hours": 72,
        },
    )
    assert response.status_code == 201
    return response.json()["item_id"]


def test_ebay_endpoint_requires_approved_photo(tmp_path) -> None:
    publisher = FakeEbayPublisher()
    app = create_app(ebay_settings(tmp_path), ebay_publisher=publisher)
    with TestClient(app) as client:
        item_id = create_item(client)
        response = client.post(
            f"/api/items/{item_id}/publish/ebay",
            json={"seller_approved": False, "aspects": {"Brand": ["Sony"]}},
        )
        assert response.status_code == 409
        assert publisher.drafts == []


def test_ebay_draft_then_explicit_publication_is_idempotent(tmp_path) -> None:
    publisher = FakeEbayPublisher()
    app = create_app(ebay_settings(tmp_path), ebay_publisher=publisher)
    with TestClient(app) as client:
        item_id = create_item(client)
        with Session(app.state.engine) as session:
            session.add(
                ProductPhoto(
                    id="photo-approved",
                    item_id=item_id,
                    role=PhotoRole.ENHANCED,
                    status=PhotoStatus.APPROVED,
                    file_path="unused.png",
                    mime_type="image/png",
                    sha256="abc",
                    reviewed_at=datetime.now(UTC),
                )
            )
            session.commit()

        payload = {
            "seller_approved": False,
            "aspects": {"Brand": ["Sony"], "Model": ["WH-1000XM5"]},
        }
        draft = client.post(f"/api/items/{item_id}/publish/ebay", json=payload)
        assert draft.status_code == 200
        assert draft.json() == {
            "status": "draft",
            "offer_id": "offer-123",
            "seller_approved": False,
        }
        assert len(publisher.drafts) == 1
        assert publisher.drafts[0].image_urls == [
            "https://liquid.example/api/photos/photo-approved/file"
        ]

        payload["seller_approved"] = True
        live = client.post(f"/api/items/{item_id}/publish/ebay", json=payload)
        assert live.json() == {
            "status": "live",
            "listing_id": "listing-456",
            "seller_approved": True,
        }
        assert publisher.published == [("offer-123", "EBAY_US")]

        repeated = client.post(f"/api/items/{item_id}/publish/ebay", json=payload)
        assert repeated.json() == live.json()
        assert len(publisher.drafts) == 1
        assert len(publisher.published) == 1

        with Session(app.state.engine) as session:
            listing = session.exec(
                select(Listing).where(Listing.item_id == item_id, Listing.channel == "ebay")
            ).one()
            assert listing.status == ListingStatus.LIVE
            assert listing.external_id == "listing-456"
            assert session.exec(
                select(LedgerEvent).where(LedgerEvent.action == "publish_ebay")
            ).one()
