from __future__ import annotations

import asyncio
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


class FakeGmailConnections:
    def __init__(self) -> None:
        self.alerts: list[tuple[str, str, str]] = []

    def authorization_url(self, seller_id: str) -> str:
        return f"https://google.example.com/connect?state={seller_id}"

    async def send_alert(self, seller_id: str, subject: str, text: str) -> bool:
        self.alerts.append((seller_id, subject, text))
        return True

    async def poll_once(self) -> int:
        return 0


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
        require_ebay_onboarding=False,
        openai_api_key=None,
    )
    base.update(overrides)
    return Settings(**base)


def send(client: TestClient, guid: str, text: str, *, with_photo: bool = False) -> None:
    response = client.post(
        "/webhooks/bluebubbles?secret=webhook-secret",
        json=payload(guid, text, with_photo=with_photo),
    )
    assert response.json()["status"] == "queued", response.json()


def test_connect_email_command_sends_seller_oauth_link(tmp_path: Path) -> None:
    adapter = FakeMessageAdapter()
    gmail = FakeGmailConnections()
    app = create_app(
        make_settings(tmp_path),
        message_adapter=adapter,
        gmail_connection_service=gmail,  # type: ignore[arg-type]
    )
    with TestClient(app) as client:
        send(client, "email-1", "connect email")
    assert "https://google.example.com/connect?state=" in adapter.sent_texts[-1]
    assert "read-only inbox access" in adapter.sent_texts[-1]


def test_imessage_onboarding_to_listing_pack_without_ebay_sandbox(tmp_path: Path) -> None:
    adapter = FakeMessageAdapter()
    app = create_app(
        make_settings(tmp_path), photo_editor=FakePhotoEditor(), message_adapter=adapter
    )
    with TestClient(app) as client:
        send(client, "m1", "Apple iPad Air 5th gen 64GB wifi, sell by Sunday 6pm", with_photo=True)
        send(client, "m2", "APPROVE")
        assert adapter.sent_texts[-1].startswith("How would you describe the condition?")

        send(client, "m3", "2, comes with the box and charger, small scratch on the back")
        assert adapter.sent_texts[-1].startswith("How fast")

        send(client, "m4", "3 days, not under $220, both 94110, all")
        texts = adapter.sent_texts
        assert any(text.startswith("Perfect") for text in texts)
        card = texts[-1]
        assert card.startswith("Here's the plan")
        assert "condition: good, light wear" in card
        assert "ebay + facebook + offerup" in card
        assert "based on 10 sold" in card and "(sample data)" in card
        assert "e.g. https://www.ebay.com/itm/" in card
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
        assert adapter.sent_texts[-1].startswith("Here's the plan")
        assert "floor $250" in adapter.sent_texts[-1]

        send(client, "m6", "go")
        final = adapter.sent_texts
        assert any(text.startswith("facebook marketplace, paste") for text in final)
        assert any(text.startswith("offerup, paste") for text in final)
        assert "connect eBay before publishing" in final[-1]
        assert "Paste the messages above" in final[-1]

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
        assert adapter.sent_texts[-1].startswith("You're all set")


def test_go_publishes_to_ebay_sandbox_when_configured(tmp_path: Path) -> None:
    adapter = FakeMessageAdapter()
    publisher = FakeEbayPublisher()
    gmail = FakeGmailConnections()
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
        settings,
        photo_editor=FakePhotoEditor(),
        message_adapter=adapter,
        ebay_publisher=publisher,
        gmail_connection_service=gmail,  # type: ignore[arg-type]
    )
    with TestClient(app) as client:
        send(client, "m1", "Sony WH-1000XM5 headphones", with_photo=True)
        send(client, "m2", "APPROVE")
        send(client, "m3", "like new, just the item")
        send(client, "m4", "week, you decide, ship, ebay only")
        assert adapter.sent_texts[-1].startswith("Here's the plan")
        send(client, "m5", "go")
        assert "Your eBay listing is live: https://www.sandbox.ebay.com/itm/1100001" in (
            adapter.sent_texts[-1]
        )
        assert gmail.alerts and "https://www.sandbox.ebay.com/itm/1100001" in gmail.alerts[0][2]
        assert publisher.offers and publisher.offers[0].condition == "USED_EXCELLENT"
        assert publisher.offers[0].image_urls[0].startswith("https://demo.example.com/api/photos/")
        with Session(app.state.engine) as session:
            item = session.exec(select(Item)).one()
            assert item.status == ItemStatus.LIVE
            pack = session.exec(select(ListingPack)).one()
            assert pack.status == ListingPackStatus.PUBLISHED and pack.external_id == "1100001"


def test_ebay_demo_mode_publishes_working_preview_without_credentials(tmp_path: Path) -> None:
    adapter = FakeMessageAdapter()
    settings = make_settings(
        tmp_path,
        public_base_url="https://demo.example.com",
        ebay_demo_mode=True,
    )
    app = create_app(settings, photo_editor=FakePhotoEditor(), message_adapter=adapter)

    with TestClient(app) as client:
        send(client, "demo-1", "Sony WH-1000XM5 headphones", with_photo=True)
        send(client, "demo-2", "approve")
        send(client, "demo-3", "like new, just the item")
        send(client, "demo-4", "week, you decide, ship, ebay only")
        before_publish = len(adapter.sent_texts)
        send(client, "demo-5", "yes")

        assert adapter.sent_texts[before_publish] == "You bet. I'm building the mock listing now."
        final = adapter.sent_texts[-1]
        assert "eBay demo preview is ready: https://demo.example.com/demo/ebay/listings/" in final
        with Session(app.state.engine) as session:
            pack = session.exec(select(ListingPack)).one()
            assert pack.status == ListingPackStatus.PUBLISHED
            assert pack.external_id and pack.external_id.startswith("demo-listing-")
            preview_path = pack.external_url.removeprefix("https://demo.example.com")
        preview = client.get(preview_path)
        assert preview.status_code == 200
        assert "Demo listing. This item has not been published to eBay." in preview.text
        assert "Sony WH-1000XM5 headphones" in preview.text


def test_demo_yes_is_acknowledged_before_waiting_for_the_seller_lock(tmp_path: Path) -> None:
    adapter = FakeMessageAdapter()
    app = create_app(
        make_settings(
            tmp_path,
            public_base_url="https://demo.example.com",
            ebay_demo_mode=True,
        ),
        photo_editor=FakePhotoEditor(),
        message_adapter=adapter,
    )

    with TestClient(app) as client:
        send(client, "ack-1", "Sony WH-1000XM5 headphones", with_photo=True)
        send(client, "ack-2", "approve")
        send(client, "ack-3", "like new, just the item")
        send(client, "ack-4", "week, you decide, ship, ebay only")
        message = adapter.parse_inbound(payload("ack-5", "yes"))
        assert message is not None
        adapter.sent_texts.clear()

        async def run_while_locked() -> None:
            lock = app.state.message_locks[SELLER]
            await lock.acquire()
            task = asyncio.create_task(app.state.process_bluebubbles_message(message))
            await asyncio.sleep(0)
            assert adapter.sent_texts == ["You bet. I'm building the mock listing now."]
            assert not task.done()
            lock.release()
            await task

        asyncio.run(run_while_locked())

    assert "eBay demo preview is ready" in adapter.sent_texts[-1]


def test_publishing_advances_to_next_batch_item(tmp_path: Path) -> None:
    adapter = FakeMessageAdapter()
    app = create_app(
        make_settings(tmp_path), photo_editor=FakePhotoEditor(), message_adapter=adapter
    )
    with TestClient(app) as client:
        send(client, "b1", "Sony WH-1000XM5 headphones", with_photo=True)
        send(client, "b2", "approve")
        send(client, "b3", "good, just the item")
        send(client, "b4", "3 days, $170 floor, ship, facebook only")

        with Session(app.state.engine) as session:
            first = session.exec(select(Item)).one()
            second = Item(
                seller_id=first.seller_id,
                title="Bose QC45 headphones",
                category="headphones",
                condition=first.condition,
                confidence=0.95,
                deadline_at=first.deadline_at,
                original_horizon_hours=first.original_horizon_hours,
                floor_cents=12_000,
                floor_source="seller",
                constraints_json={"batch_index": 1},
                market_value_cents=16_000,
                sigma_cents=2_000,
                status=ItemStatus.DRAFT,
            )
            session.add(second)
            session.flush()
            batch_ids = [first.id, second.id]
            first.constraints_json = {
                **first.constraints_json,
                "batch_item_ids": batch_ids,
                "batch_index": 0,
            }
            second.constraints_json = {
                **second.constraints_json,
                "batch_item_ids": batch_ids,
            }
            session.add(first)
            session.add(second)
            session.commit()
            second_id = second.id

        send(client, "b5", "go")
        assert any(
            "Next up (2 of 2): Bose QC45 headphones" in text
            for text in adapter.sent_texts
        )
        assert adapter.sent_texts[-1].startswith("How would you describe the condition?")
        with Session(app.state.engine) as session:
            conversation = session.exec(select(SellerConversation)).one()
            assert conversation.active_item_id == second_id
            assert conversation.status == ConversationStatus.AWAITING_DETAILS


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
            "ebay",
            "facebook",
            "offerup",
        ]
        plan = client.post(f"/api/items/{item_id}/plan-listing", json={"research": True}).json()
        assert plan["card_text"].startswith("Here's the plan")
        assert plan["research"]["sold_n"] == 10
        assert len(plan["packs"]) == 3
        result = client.post(f"/api/items/{item_id}/go").json()
        assert result["outcomes"]["facebook"]["status"] == "handoff_ready"
        assert result["outcomes"]["ebay"]["status"] == "failed"
        packs = client.get(f"/api/items/{item_id}/packs").json()
        assert {pack["status"] for pack in packs} == {"failed", "handoff_ready"}
