from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from fastapi.testclient import TestClient
from sqlmodel import Session, select

from app.inbound.identify import (
    Candidate,
    CaptionIdentifier,
    ItemIdentity,
    OpenAIIdentifier,
    interpret_confirmation,
)
from app.main import create_app
from app.models import ConversationStatus, Item, LedgerEvent, ProductPhoto, SellerConversation
from tests.test_listing_flow import (
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


def send(client: TestClient, guid: str, text: str, *, with_photo: bool = False) -> None:
    response = client.post(
        "/webhooks/bluebubbles?secret=webhook-secret",
        json=payload(guid, text, with_photo=with_photo),
    )
    assert response.json()["status"] == "queued"


def test_question_and_confirmation_parsing() -> None:
    question = IDENTITY.question()
    assert question.startswith("looks like Apple iPad Air 5th gen (M1) 64GB Wi-Fi. is that right?")
    assert "2) Apple iPad Air 4th gen 64GB Wi-Fi" in question
    assert interpret_confirmation("yes", IDENTITY) == ("yes", IDENTITY.title)
    assert interpret_confirmation("2", IDENTITY) == (
        "candidate", "Apple iPad Air 4th gen 64GB Wi-Fi",
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
    assert content[0]["type"] == "input_image"
    assert content[0]["image_url"].startswith("data:image/jpeg;base64,")
    assert content[1]["text"] == "Seller's caption: sell this"


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
        assert adapter.sent_texts[-1].startswith("looks like Apple iPad Air 5th gen")
        with Session(app.state.engine) as session:
            conversation = session.exec(select(SellerConversation)).one()
            assert conversation.status == ConversationStatus.AWAITING_IDENTITY
            item = session.exec(select(Item)).one()
            assert item.title == IDENTITY.title and item.category == "tablet"
            assert item.constraints_json["needs_identification"] is False

        send(client, "m2", "yes")  # 'yes' must confirm identity, not approve a photo
        assert any(text.startswith("Original first") for text in adapter.sent_texts)
        assert len(adapter.sent_images) == 2
        with Session(app.state.engine) as session:
            conversation = session.exec(select(SellerConversation)).one()
            assert conversation.status == ConversationStatus.AWAITING_PHOTO_REVIEW
            actions = [row.action for row in session.exec(select(LedgerEvent)).all()]
            assert actions[:3] == ["intake", "identify", "confirm_identity"]

        send(client, "m3", "APPROVE")
        assert adapter.sent_texts[-1].startswith("two quick things")


def test_named_correction_and_no_editor_fallback(tmp_path: Path) -> None:
    adapter = FakeMessageAdapter()
    app = create_app(
        make_settings(tmp_path), message_adapter=adapter, identifier=FakeIdentifier()
    )  # no photo editor configured
    with TestClient(app) as client:
        send(client, "m1", "", with_photo=True)
        send(client, "m2", "no, it's the ipad air 4th gen 64gb")
        assert any("photo cleanup is off" in text for text in adapter.sent_texts)
        assert adapter.sent_texts[-1].startswith("two quick things")
        with Session(app.state.engine) as session:
            item = session.exec(select(Item)).one()
            assert item.title == "the ipad air 4th gen 64gb"
            assert item.confidence == 1.0
            photos = session.exec(select(ProductPhoto)).all()
            assert len(photos) == 1 and photos[0].role.value == "original"
            conversation = session.exec(select(SellerConversation)).one()
            assert conversation.status == ConversationStatus.AWAITING_DETAILS
