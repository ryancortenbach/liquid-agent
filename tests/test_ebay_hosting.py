from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from fastapi.testclient import TestClient
from sqlmodel import Session

from app.config import Mode, Settings
from app.main import create_app
from app.market.ebay import EbayDraft, EbayOfferInput, EbayPublication
from app.models import PhotoRole, PhotoStatus, ProductPhoto

JPEG = b"\xff\xd8\xff\xe0" + b"liquid-test-jpeg" * 8


class HostingPublisher:
    """A fake sandbox client that can host pictures, like the real EbaySandboxClient."""

    def __init__(self) -> None:
        self.uploads: list[tuple[str, str, bytes]] = []
        self.drafts: list[EbayOfferInput] = []

    async def upload_picture(
        self, content: bytes, *, filename: str, mime_type: str, picture_name: str | None = None
    ) -> str:
        self.uploads.append((filename, mime_type, content))
        return f"https://i.sandbox.ebayimg.com/{filename}"

    async def create_draft(self, offer: EbayOfferInput) -> EbayDraft:
        self.drafts.append(offer)
        return EbayDraft(offer_id="offer-1", sku=offer.sku)

    async def publish(self, offer_id: str, marketplace_id: str) -> EbayPublication:
        return EbayPublication(offer_id=offer_id, listing_id="listing-1")

    async def close(self) -> None:
        return None


class PlainPublisher(HostingPublisher):
    upload_picture = None  # type: ignore[assignment]


def local_settings(tmp_path: Path) -> Settings:
    return Settings(
        mode=Mode.SIM,
        database_url="sqlite:///:memory:",
        photo_storage_dir=str(tmp_path / "photos"),
        public_base_url="http://localhost:8000",
        ebay_sb_merchant_location_key="home",
        ebay_sb_payment_policy_id="payment-policy",
        ebay_sb_return_policy_id="return-policy",
        ebay_sb_fulfillment_policy_id="fulfillment-policy",
        require_ebay_onboarding=False,
    )


def item_with_approved_photo(client: TestClient, app, tmp_path: Path, sha: str) -> tuple[str, str]:
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
    item_id = response.json()["item_id"]
    photo_dir = tmp_path / "photos" / item_id
    photo_dir.mkdir(parents=True)
    (photo_dir / "enhanced.jpg").write_bytes(JPEG)
    photo_id = f"photo-{sha}"
    with Session(app.state.engine) as session:
        session.add(
            ProductPhoto(
                id=photo_id,
                item_id=item_id,
                role=PhotoRole.ENHANCED,
                status=PhotoStatus.APPROVED,
                file_path=f"{item_id}/enhanced.jpg",
                mime_type="image/jpeg",
                sha256=sha,
                reviewed_at=datetime.now(UTC),
            )
        )
        session.commit()
    return item_id, photo_id


def test_localhost_base_url_hosts_photos_on_ebay_instead_of_failing(tmp_path) -> None:
    publisher = HostingPublisher()
    app = create_app(local_settings(tmp_path), ebay_publisher=publisher)
    with TestClient(app) as client:
        item_id, photo_id = item_with_approved_photo(client, app, tmp_path, "sha-hosting-1")
        response = client.post(
            f"/api/items/{item_id}/publish/ebay",
            json={"seller_approved": False, "aspects": {"Brand": ["Sony"]}},
        )
        assert response.status_code == 200, response.text
        assert response.json()["status"] == "draft"
        assert publisher.uploads == [(f"{photo_id}.jpg", "image/jpeg", JPEG)]
        assert publisher.drafts[0].image_urls == [f"https://i.sandbox.ebayimg.com/{photo_id}.jpg"]
        assert publisher.drafts[0].category_id  # never empty: suggestion, default, or fallback

        # A second attempt re-uses the hosted URL rather than uploading again.
        again = client.post(
            f"/api/items/{item_id}/publish/ebay",
            json={"seller_approved": False, "aspects": {"Brand": ["Sony"]}},
        )
        assert again.status_code == 200
        assert len(publisher.uploads) == 1


def test_localhost_base_url_without_picture_hosting_is_refused(tmp_path) -> None:
    publisher = PlainPublisher()
    app = create_app(local_settings(tmp_path), ebay_publisher=publisher)
    with TestClient(app) as client:
        item_id, _ = item_with_approved_photo(client, app, tmp_path, "sha-hosting-2")
        response = client.post(
            f"/api/items/{item_id}/publish/ebay",
            json={"seller_approved": False, "aspects": {"Brand": ["Sony"]}},
        )
        assert response.status_code == 503
        assert "PUBLIC_BASE_URL" in response.json()["detail"]
        assert publisher.drafts == []
