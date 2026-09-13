from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from fastapi.testclient import TestClient
from sqlmodel import Session, select

from app.inbound.identify import (
    Candidate,
    CaptionIdentifier,
    InventoryDetection,
    InventoryItem,
    ItemIdentity,
    OpenAIIdentifier,
    interpret_confirmation,
)
from app.main import create_app
from app.models import (
    ConversationStatus,
    Item,
    LedgerEvent,
    PhotoStatus,
    ProductPhoto,
    SellerConversation,
)
from tests.test_listing_flow import (
    SELLER,
    FakeMessageAdapter,
    FakePhotoEditor,
    jpeg_bytes,
    make_settings,
    payload,
)

IDENTITY = ItemIdentity(
    title="Apple iPad Air 5th gen (M1) 64GB Wi-Fi",
    brand="Apple",
    model="A2588",
    category="tablet",
    condition_guess="B",
    confidence=0.7,
    candidates=[
        Candidate(title="Apple iPad Air 5th gen (M1) 64GB Wi-Fi", why="10.9 inch, flat edges"),
        Candidate(title="Apple iPad Air 4th gen 64GB Wi-Fi", why="identical chassis"),
    ],
    lookalike_note="air 4 and 5 look the same; settings > general > about shows the model number",
)


class FakeIdentifier:
    def __init__(self) -> None:
        self.calls = 0

    async def identify(self, content: bytes, mime_type: str, caption: str) -> ItemIdentity:
        self.calls += 1
        assert content and mime_type == "image/jpeg"
        return IDENTITY


class SequenceIdentifier:
    def __init__(self, identities: list[ItemIdentity]) -> None:
        self.identities = iter(identities)
        self.captions: list[str] = []

    async def identify(self, content: bytes, mime_type: str, caption: str) -> ItemIdentity:
        self.captions.append(caption)
        return next(self.identities)


class FakeInventoryIdentifier:
    async def identify(self, content: bytes, mime_type: str, caption: str) -> ItemIdentity:
        raise AssertionError("single-item identification should not run")

    async def detect_all(self, content: bytes, mime_type: str, caption: str) -> InventoryDetection:
        return InventoryDetection(
            items=[
                InventoryItem(
                    **IDENTITY.model_dump(),
                    box_2d=[0, 0, 1000, 500],
                ),
                InventoryItem(
                    title="Sony WH-1000XM5 headphones",
                    brand="Sony",
                    model="WH-1000XM5",
                    category="headphones",
                    condition_guess="B",
                    confidence=0.8,
                    box_2d=[0, 500, 1000, 1000],
                ),
            ]
        )


def send(client: TestClient, guid: str, text: str, *, with_photo: bool = False) -> None:
    response = client.post(
        "/webhooks/bluebubbles?secret=webhook-secret",
        json=payload(guid, text, with_photo=with_photo),
    )
    assert response.json()["status"] == "queued"


def send_photos(client: TestClient, guid: str, text: str, count: int) -> None:
    body = payload(guid, text)
    body["data"]["attachments"] = [
        {
            "guid": f"attachment-{index}",
            "mimeType": "image/jpeg",
            "transferName": f"angle-{index}.jpg",
        }
        for index in range(1, count + 1)
    ]
    response = client.post("/webhooks/bluebubbles?secret=webhook-secret", json=body)
    assert response.json()["status"] == "queued"


def test_question_and_confirmation_parsing() -> None:
    question = IDENTITY.question()
    assert question.startswith("Does this look like the Apple iPad Air 5th gen (M1) 64GB Wi-Fi?")
    assert "2) Apple iPad Air 4th gen 64GB Wi-Fi" in question
    assert interpret_confirmation("yes", IDENTITY) == ("yes", IDENTITY.title)
    assert interpret_confirmation("2", IDENTITY) == (
        "candidate",
        "Apple iPad Air 4th gen 64GB Wi-Fi",
    )
    assert interpret_confirmation("no it's the 4th gen", IDENTITY) == ("named", "the 4th gen")
    assert interpret_confirmation("   ", IDENTITY) == ("named", None)


def test_caption_identifier_uses_the_caption() -> None:
    import asyncio

    identity = asyncio.run(
        CaptionIdentifier().identify(
            b"x", "image/jpeg", "Sony WH-1000XM5 headphones, sell by sunday"
        )
    )
    assert identity.title == "Sony WH-1000XM5 headphones"
    assert identity.brand == "Sony" and identity.category == "headphones"
    assert identity.confidence == 0.5


def test_openai_identifier_sends_image_and_parses_identity() -> None:
    import asyncio

    calls: list[dict] = []

    class FakeResponses:
        async def parse(self, **kwargs):
            calls.append(kwargs)
            return SimpleNamespace(output_parsed=IDENTITY)

    identifier = OpenAIIdentifier(
        "unused-test-key",
        client=SimpleNamespace(responses=FakeResponses()),
    )
    identity = asyncio.run(identifier.identify(jpeg_bytes(), "image/jpeg", "sell this"))

    assert identity == IDENTITY
    assert calls[0]["model"] == "gpt-5.4-mini"
    assert calls[0]["store"] is False
    assert calls[0]["text_format"] is ItemIdentity
    content = calls[0]["input"][0]["content"]
    image_input = next(value for value in content if value["type"] == "input_image")
    text_input = next(value for value in content if value["type"] == "input_text")
    assert image_input["image_url"].startswith("data:image/jpeg;base64,")
    assert image_input["detail"] == "high"
    assert text_input["text"] == "Seller's caption: sell this"


def test_openai_identifier_falls_back_to_caption() -> None:
    import asyncio

    class FailingResponses:
        async def parse(self, **kwargs):
            raise RuntimeError("temporary failure")

    identifier = OpenAIIdentifier(
        "unused-test-key",
        client=SimpleNamespace(responses=FailingResponses()),
    )
    identity = asyncio.run(
        identifier.identify(jpeg_bytes(), "image/jpeg", "Sony WH-1000XM5 headphones")
    )

    assert identity.title == "Sony WH-1000XM5 headphones"
    assert identity.brand == "Sony"


def test_openai_identifier_detects_all_sellable_objects() -> None:
    import asyncio

    calls: list[dict] = []
    detection = InventoryDetection(
        items=[InventoryItem(**IDENTITY.model_dump(), box_2d=[10, 20, 500, 600])]
    )

    class FakeResponses:
        async def parse(self, **kwargs):
            calls.append(kwargs)
            return SimpleNamespace(output_parsed=detection)

    identifier = OpenAIIdentifier(
        "unused-test-key",
        client=SimpleNamespace(responses=FakeResponses()),
    )
    result = asyncio.run(identifier.detect_all(jpeg_bytes(), "image/jpeg", "sell everything here"))

    assert result.items[0].title == IDENTITY.title
    assert result.items[0].box_2d == [10, 20, 500, 600]
    assert calls[0]["text_format"] is InventoryDetection
    assert calls[0]["store"] is False
    assert "Inventory every distinct sellable item" in calls[0]["instructions"]


def test_identify_then_confirm_then_enhance(tmp_path: Path) -> None:
    adapter = FakeMessageAdapter()
    identifier = FakeIdentifier()
    app = create_app(
        make_settings(tmp_path),
        photo_editor=FakePhotoEditor(),
        message_adapter=adapter,
        identifier=identifier,
    )
    with TestClient(app) as client:
        send(client, "m1", "sell this by sunday", with_photo=True)
        assert identifier.calls == 1
        assert adapter.sent_texts[-1].startswith("Does this look like the Apple iPad Air 5th gen")
        with Session(app.state.engine) as session:
            conversation = session.exec(select(SellerConversation)).one()
            assert conversation.status == ConversationStatus.AWAITING_IDENTITY
            item = session.exec(select(Item)).one()
            assert item.title == IDENTITY.title and item.category == "tablet"
            assert item.constraints_json["needs_identification"] is False

        send(client, "m2", "yes")  # 'yes' must confirm identity, not approve a photo
        assert any(text.startswith("I cleaned it up") for text in adapter.sent_texts)
        assert len(adapter.sent_images) == 2
        with Session(app.state.engine) as session:
            conversation = session.exec(select(SellerConversation)).one()
            assert conversation.status == ConversationStatus.AWAITING_PHOTO_REVIEW
            actions = [row.action for row in session.exec(select(LedgerEvent)).all()]
            assert actions[:3] == ["intake", "identify", "confirm_identity"]

        send(client, "m3", "APPROVE")
        assert "How would you describe the condition?" in adapter.sent_texts[-1]
        assert adapter.sent_texts[-1].startswith("Locked in.")


def test_named_correction_and_no_editor_fallback(tmp_path: Path) -> None:
    adapter = FakeMessageAdapter()
    app = create_app(
        make_settings(tmp_path), message_adapter=adapter, identifier=FakeIdentifier()
    )  # no photo editor configured
    with TestClient(app) as client:
        send(client, "m1", "", with_photo=True)
        send(client, "m2", "no, it's the ipad air 4th gen 64gb")
        assert any(text.startswith("Got it") for text in adapter.sent_texts)
        assert "How would you describe the condition?" in adapter.sent_texts[-1]
        with Session(app.state.engine) as session:
            item = session.exec(select(Item)).one()
            assert item.title == "the ipad air 4th gen 64gb"
            assert item.confidence == 1.0
            photos = session.exec(select(ProductPhoto)).all()
            assert len(photos) == 1 and photos[0].role.value == "original"
            conversation = session.exec(select(SellerConversation)).one()
            assert conversation.status == ConversationStatus.AWAITING_DETAILS


def test_multiple_photos_stay_with_one_item_and_review_together(tmp_path: Path) -> None:
    adapter = FakeMessageAdapter()
    app = create_app(
        make_settings(tmp_path),
        photo_editor=FakePhotoEditor(),
        message_adapter=adapter,
        identifier=FakeIdentifier(),
    )
    with TestClient(app) as client:
        send_photos(client, "multi-1", "sell this by sunday", 3)
        assert adapter.sent_texts[-1].endswith("(using all 3 photos)")

        send(client, "multi-2", "yes")
        assert len(adapter.sent_images) == 6
        assert "use the new ones?" in adapter.sent_texts[-1]

        send(client, "multi-3", "approve")
        with Session(app.state.engine) as session:
            assert len(session.exec(select(Item)).all()) == 1
            photos = session.exec(select(ProductPhoto)).all()
            assert len(photos) == 6
            assert sum(photo.status == PhotoStatus.APPROVED for photo in photos) == 3


def test_batch_creates_separate_items_and_accepts_numbered_correction(tmp_path: Path) -> None:
    adapter = FakeMessageAdapter()
    second = IDENTITY.model_copy(
        update={
            "title": "Sony WH-1000XM5 headphones",
            "brand": "Sony",
            "model": "WH-1000XM5",
            "category": "headphones",
        }
    )
    app = create_app(
        make_settings(tmp_path),
        photo_editor=FakePhotoEditor(),
        message_adapter=adapter,
        identifier=SequenceIdentifier([IDENTITY, second]),
    )
    with TestClient(app) as client:
        send_photos(client, "batch-1", "BATCH 2+1 sell these by sunday", 3)
        assert adapter.sent_texts[-1].startswith("I found 2 items:")
        assert "1. Apple iPad Air" in adapter.sent_texts[-1]
        assert "(2 photos)" in adapter.sent_texts[-1]
        assert "2. Sony WH-1000XM5" in adapter.sent_texts[-1]

        send(client, "batch-2", "2 is Bose QC45 headphones")
        assert "2. Bose QC45 headphones" in adapter.sent_texts[-1]
        send(client, "batch-3", "yes")
        assert len(adapter.sent_images) == 6
        send(client, "batch-4", "approve")

        with Session(app.state.engine) as session:
            items = session.exec(select(Item).order_by(Item.created_at)).all()
            assert len(items) == 2
            assert [item.title for item in items] == [IDENTITY.title, "Bose QC45 headphones"]
            assert [len(item.photo_paths) for item in items] == [4, 2]
            assert all(len(item.constraints_json["batch_item_ids"]) == 2 for item in items)


def test_long_message_and_matching_photos_create_isolated_items(tmp_path: Path) -> None:
    adapter = FakeMessageAdapter()
    second = IDENTITY.model_copy(
        update={
            "title": "Insulated water bottle",
            "brand": None,
            "model": None,
            "category": "other",
        }
    )
    identifier = SequenceIdentifier([IDENTITY, second])
    app = create_app(
        make_settings(tmp_path),
        photo_editor=FakePhotoEditor(),
        message_adapter=adapter,
        identifier=identifier,
    )
    with TestClient(app) as client:
        send_photos(
            client,
            "separate-photos-1",
            "I want to sell my AirPods and then I want to sell my water bottle",
            2,
        )

        assert identifier.captions == ["AirPods", "water bottle"]
        assert adapter.sent_texts[-1].startswith("I found 2 items:")
        with Session(app.state.engine) as session:
            items = session.exec(select(Item).order_by(Item.created_at)).all()
            assert len(items) == 2
            assert [item.constraints_json["original_caption"] for item in items] == [
                "AirPods",
                "water bottle",
            ]
            assert all(len(item.constraints_json["batch_item_ids"]) == 2 for item in items)


def test_ambiguous_photo_count_is_rejected_without_creating_items(tmp_path: Path) -> None:
    adapter = FakeMessageAdapter()
    identifier = SequenceIdentifier([IDENTITY])
    app = create_app(
        make_settings(tmp_path),
        photo_editor=FakePhotoEditor(),
        message_adapter=adapter,
        identifier=identifier,
    )
    with TestClient(app) as client:
        send_photos(
            client,
            "ambiguous-photos-1",
            "Sell my AirPods and then sell my water bottle",
            3,
        )

        assert "I won't guess which photos belong together" in adapter.sent_texts[-1]
        assert identifier.captions == []
        with Session(app.state.engine) as session:
            assert session.exec(select(Item)).all() == []


def test_one_inventory_photo_becomes_separate_confirmed_items(tmp_path: Path) -> None:
    adapter = FakeMessageAdapter()
    app = create_app(
        make_settings(tmp_path),
        photo_editor=FakePhotoEditor(),
        message_adapter=adapter,
        identifier=FakeInventoryIdentifier(),
    )
    with TestClient(app) as client:
        send(client, "inventory-1", "sell everything here by sunday", with_photo=True)
        assert adapter.sent_texts[-1].startswith("I found 2 things you could sell")
        assert "1. Apple iPad Air" in adapter.sent_texts[-1]
        assert "2. Sony WH-1000XM5" in adapter.sent_texts[-1]

        send(client, "inventory-2", "yes")
        assert len(adapter.sent_images) == 4
        send(client, "inventory-3", "approve")

        with Session(app.state.engine) as session:
            items = session.exec(select(Item).order_by(Item.created_at)).all()
            assert len(items) == 2
            assert all(item.constraints_json["inventory_source_path"] for item in items)
            assert all(len(item.photo_paths) == 2 for item in items)


def test_inventory_checklist_can_remove_an_unwanted_item(tmp_path: Path) -> None:
    adapter = FakeMessageAdapter()
    app = create_app(
        make_settings(tmp_path),
        photo_editor=FakePhotoEditor(),
        message_adapter=adapter,
        identifier=FakeInventoryIdentifier(),
    )
    with TestClient(app) as client:
        send(client, "remove-1", "sell the things on this table", with_photo=True)
        send(client, "remove-2", "remove 2")
        assert "removed." in adapter.sent_texts[-1]
        assert "Sony" not in adapter.sent_texts[-1]
        send(client, "remove-3", "yes")
        assert len(adapter.sent_images) == 2

        with Session(app.state.engine) as session:
            items = session.exec(select(Item).order_by(Item.created_at)).all()
            assert len(items) == 2
            assert items[1].status.value == "cancelled"


def test_openai_identifier_parses_and_normalizes(tmp_path: Path) -> None:
    import asyncio

    from app.inbound.identify import OpenAIIdentifier

    class FakeParsed:
        output_parsed = ItemIdentity(
            title="Apple iPad Air (5th generation) 64GB",
            brand="Apple",
            category="Tablet",
            condition_guess="good",
            confidence=0.68,
        )

    class FakeResponses:
        def __init__(self) -> None:
            self.calls: list[dict] = []

        async def parse(self, **kwargs):
            self.calls.append(kwargs)
            return FakeParsed()

    class FakeClient:
        responses = FakeResponses()

    from io import BytesIO

    from PIL import Image

    buffer = BytesIO()
    Image.new("RGB", (40, 30), (10, 20, 30)).save(buffer, format="JPEG")
    identifier = OpenAIIdentifier("key", model="gpt-5.1", client=FakeClient())
    identity = asyncio.run(identifier.identify(buffer.getvalue(), "image/jpeg", "ipad"))
    assert identity.category == "tablet" and identity.condition_guess == "B"
    call = FakeClient.responses.calls[0]
    assert call["model"] == "gpt-5.1" and call["reasoning"] == {"effort": "low"}
    assert call["store"] is False
    assert call["input"][0]["content"][1]["image_url"].startswith("data:image/jpeg;base64,")
    assert call["text_format"] is ItemIdentity

    class BrokenClient:
        class responses:  # noqa: N801
            @staticmethod
            async def parse(**kwargs):
                raise RuntimeError("boom")

    fallback = OpenAIIdentifier("key", client=BrokenClient())
    identity = asyncio.run(
        fallback.identify(buffer.getvalue(), "image/jpeg", "Sony WH-1000XM5 headphones")
    )
    assert identity.title == "Sony WH-1000XM5 headphones" and identity.confidence == 0.5


def test_identify_endpoint_returns_identity_and_applies_to_item(tmp_path: Path) -> None:
    from io import BytesIO

    from PIL import Image

    app = create_app(make_settings(tmp_path, seller_handle=None), identifier=FakeIdentifier())
    with TestClient(app) as client:
        buffer = BytesIO()
        Image.new("RGB", (16, 12), (1, 2, 3)).save(buffer, format="JPEG")
        response = client.post(
            "/api/identify",
            files={"upload": ("ipad.jpg", buffer.getvalue(), "image/jpeg")},
            data={"caption": "my ipad"},
        )
        assert response.status_code == 200
        body = response.json()
        assert body["title"] == IDENTITY.title and body["question"].startswith(
            "Does this look like"
        )

        item_id = client.post(
            "/api/items",
            json={
                "seller_handle": SELLER,
                "title": "Item from iMessage",
                "market_value_cents": 30_000,
                "sigma_cents": 3_500,
                "floor_cents": 22_000,
                "deadline_hours": 72,
            },
        ).json()["item_id"]
        applied = client.post(
            "/api/identify",
            files={"upload": ("ipad.jpg", buffer.getvalue(), "image/jpeg")},
            data={"caption": "", "item_id": item_id},
        ).json()
        assert applied["title_applied"] == IDENTITY.title
        with Session(app.state.engine) as session:
            item = session.get(Item, item_id)
            assert item is not None and item.category == "tablet"
            assert session.exec(select(LedgerEvent).where(LedgerEvent.action == "identify")).one()
