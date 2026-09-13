from __future__ import annotations

from io import BytesIO
from pathlib import Path

from fastapi.testclient import TestClient
from PIL import Image
from sqlmodel import Session, select

from app.channels.imessage_bluebubbles import BlueBubblesAdapter
from app.config import Mode, Settings
from app.main import create_app
from app.market.ebay import EbayDraft, EbayOfferInput, EbayPublication
from app.models import (
    ConversationStatus,
    Item,
    ItemStatus,
    LedgerEvent,
    ListingPack,
    ListingPackStatus,
    SellerConversation,
)

SELLER = "+14155550123"


def jpeg_bytes() -> bytes:
    buffer = BytesIO()
    Image.new("RGB", (8, 6), color=(60, 80, 100)).save(buffer, format="JPEG")
    return buffer.getvalue()


def payload(guid: str, text: str, *, with_photo: bool = False) -> dict:
    return {
        "type": "new-message",
        "data": {
            "guid": guid,
            "text": text,
            "isFromMe": False,
            "dateCreated": 1_778_436_000_000,
            "handle": {"address": SELLER, "service": "iMessage"},
            "chats": [{"guid": f"iMessage;-;{SELLER}"}],
            "attachments": (
                [{"guid": "attachment-guid", "mimeType": "image/jpeg", "transferName": "a.jpeg"}]
                if with_photo
                else []
            ),
        },
    }


class FakePhotoEditor:
    model = "fake-image-editor"

    def edit(self, source_path: Path, output_path: Path, prompt: str) -> None:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(b"\x89PNG\r\n\x1a\nenhanced")


class FakeMessageAdapter(BlueBubblesAdapter):
    def __init__(self) -> None:
        self.sent_texts: list[str] = []
        self.sent_images: list[str] = []

    async def close(self) -> None:
        return None

    async def download_attachment_bytes(self, guid: str) -> bytes:
        return jpeg_bytes()

    async def send_text(self, chat_guid: str, text: str, idempotency_key: str) -> None:
        self.sent_texts.append(text)

    async def send_image(self, chat_guid: str, path: str, idempotency_key: str) -> None:
        self.sent_images.append(path)


class FakeEbayPublisher:
    def __init__(self) -> None:
        self.offers: list[EbayOfferInput] = []

    async def create_draft(self, offer: EbayOfferInput) -> EbayDraft:
        self.offers.append(offer)
        return EbayDraft(offer_id="offer-1", sku=offer.sku)

    async def publish(self, offer_id: str, marketplace_id: str) -> EbayPublication:
        return EbayPublication(offer_id=offer_id, listing_id="1100001")

    async def close(self) -> None:
        return None


def make_settings(tmp_path: Path, **overrides) -> Settings:
    base = dict(
        mode=Mode.SIM,
        database_url="sqlite:///:memory:",
        photo_storage_dir=str(tmp_path / "photos"),
        handoff_dir=str(tmp_path / "handoff"),
        research_mode="fixture",
        bb_password="secret",
        bb_webhook_secret="webhook-secret",
        seller_handle=SELLER,
    )
    base.update(overrides)
    return Settings(**base)


def send(client: TestClient, guid: str, text: str, *, with_photo: bool = False) -> None:
    response = client.post(
        "/webhooks/bluebubbles?secret=webhook-secret",
        json=payload(guid, text, with_photo=with_photo),
    )
    assert response.json()["status"] == "queued", response.json()


def test_imessage_onboarding_to_listing_pack_without_ebay_sandbox(tmp_path: Path) -> None:
    adapter = FakeMessageAdapter()
    app = create_app(
        make_settings(tmp_path), photo_editor=FakePhotoEditor(), message_adapter=adapter
    )
    with TestClient(app) as client:
        send(client, "m1", "Apple iPad Air 5th gen 64GB wifi, sell by Sunday 6pm", with_photo=True)
        send(client, "m2", "APPROVE")
        assert adapter.sent_texts[-1].startswith("two quick things")

        send(client, "m3", "2, comes with the box and charger, small scratch on the back")
        assert adapter.sent_texts[-1].startswith("last three")

        send(client, "m4", "3 days, not under $220, both 94110, all")
        texts = adapter.sent_texts
        assert any(text.startswith("on it.") for text in texts)
        card = texts[-1]
        assert card.startswith("here's the plan")
        assert "condition: good, light wear" in card
        assert "listing on: ebay, facebook, offerup" in card
        assert "based on 10 sold" in card and "offline sample data" in card
        assert "sources: https://www.ebay.com/itm/" in card
        assert "floor $220" in card

        with Session(app.state.engine) as session:
            item = session.exec(select(Item)).one()
            assert item.floor_cents == 22_000 and item.floor_source == "seller"
            assert item.constraints_json["intake"]["horizon"] == "3 days"
            assert item.comps_n == 18
            packs = session.exec(select(ListingPack)).all()
            assert {pack.channel for pack in packs} == {"ebay", "facebook", "offerup"}
            assert all(pack.status == ListingPackStatus.DRAFT for pack in packs)
            assert "small scratch on the back" in packs[0].description
            assert "Included: the box, charger." in packs[0].description
            conversation = session.exec(select(SellerConversation)).one()
            assert conversation.status == ConversationStatus.AWAITING_CONFIRMATION

        send(client, "m5", "floor 250")
        assert adapter.sent_texts[-1].startswith("here's the plan")
        assert "floor $250" in adapter.sent_texts[-1]

        send(client, "m6", "go")
        final = adapter.sent_texts
        assert any(text.startswith("facebook marketplace, paste") for text in final)
        assert any(text.startswith("offerup, paste") for text in final)
        assert "ebay: eBay sandbox is not configured" in final[-1]
        assert "paste the messages above" in final[-1]

        with Session(app.state.engine) as session:
            packs = {pack.channel: pack for pack in session.exec(select(ListingPack)).all()}
            assert packs["ebay"].status == ListingPackStatus.FAILED
            assert packs["facebook"].status == ListingPackStatus.HANDOFF_READY
            assert packs["facebook"].handoff_path and Path(packs["facebook"].handoff_path).exists()
            assert packs["offerup"].status == ListingPackStatus.HANDOFF_READY
            conversation = session.exec(select(SellerConversation)).one()
            assert conversation.status == ConversationStatus.LISTED
            actions = [row.action for row in session.exec(select(LedgerEvent)).all()]
            assert actions.count("research") == 1
            assert actions.count("price_plan") == 2
            assert "publish" in actions

        send(client, "m7", "hello?")
        assert adapter.sent_texts[-1].startswith("it's listed")


def test_go_publishes_to_ebay_sandbox_when_configured(tmp_path: Path) -> None:
    adapter = FakeMessageAdapter()
    publisher = FakeEbayPublisher()
    settings = make_settings(
        tmp_path,
        public_base_url="https://demo.example.com",
        ebay_sb_merchant_location_key="loc-1",
        ebay_sb_payment_policy_id="pay-1",
        ebay_sb_return_policy_id="ret-1",
        ebay_sb_fulfillment_policy_id="ful-1",
        ebay_sb_default_category_id="171485",
    )
    app = create_app(
        settings, photo_editor=FakePhotoEditor(), message_adapter=adapter, ebay_publisher=publisher
    )
    with TestClient(app) as client:
        send(client, "m1", "Sony WH-1000XM5 headphones", with_photo=True)
        send(client, "m2", "APPROVE")
        send(client, "m3", "like new, just the item")
        send(client, "m4", "week, you decide, ship, ebay only")
        assert adapter.sent_texts[-1].startswith("here's the plan")
        send(client, "m5", "go")
        assert "listed on ebay (sandbox): https://www.sandbox.ebay.com/itm/1100001" in (
            adapter.sent_texts[-1]
        )
        assert publisher.offers and publisher.offers[0].condition == "USED_EXCELLENT"
        assert publisher.offers[0].image_urls[0].startswith("https://demo.example.com/api/photos/")
        with Session(app.state.engine) as session:
            item = session.exec(select(Item)).one()
            assert item.status == ItemStatus.LIVE
            pack = session.exec(select(ListingPack)).one()
            assert pack.status == ListingPackStatus.PUBLISHED and pack.external_id == "1100001"


def test_api_path_plans_and_publishes_without_imessage(tmp_path: Path) -> None:
    app = create_app(make_settings(tmp_path, seller_handle=None), photo_editor=FakePhotoEditor())
    with TestClient(app) as client:
        created = client.post(
            "/api/items",
            json={
                "seller_handle": SELLER,
                "title": "iPad Air 5th gen 64GB",
                "brand": "Apple",
                "market_value_cents": 30_000,
                "sigma_cents": 3_500,
                "floor_cents": 22_000,
                "deadline_hours": 72,
            },
        ).json()
        item_id = created["item_id"]
        details = client.post(
            f"/api/items/{item_id}/details", json={"text": "good, box included, 3 days, all"}
        ).json()
        assert details["horizon"] == "3 days" and details["platforms"] == [
            "ebay", "facebook", "offerup",
        ]
        plan = client.post(f"/api/items/{item_id}/plan-listing", json={"research": True}).json()
        assert plan["card_text"].startswith("here's the plan")
        assert plan["research"]["sold_n"] == 10
        assert len(plan["packs"]) == 3
        result = client.post(f"/api/items/{item_id}/go").json()
        assert result["outcomes"]["facebook"]["status"] == "handoff_ready"
        assert result["outcomes"]["ebay"]["status"] == "failed"
        packs = client.get(f"/api/items/{item_id}/packs").json()
        assert {pack["status"] for pack in packs} == {"failed", "handoff_ready"}
