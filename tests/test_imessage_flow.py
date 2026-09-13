from __future__ import annotations

import asyncio
from io import BytesIO
from pathlib import Path

from fastapi.testclient import TestClient
from PIL import Image
from sqlmodel import Session, select

from app.channels.chat_ai import ChatIntent, ChatInterpretation
from app.channels.imessage_bluebubbles import BlueBubblesAdapter
from app.config import Mode, Settings
from app.main import create_app
from app.models import (
    ConversationStatus,
    ConversationTurn,
    EbayConnection,
    Item,
    ItemStatus,
    PhotoStatus,
    ProductPhoto,
    SellerConversation,
    WebhookReceipt,
)


def jpeg_bytes() -> bytes:
    buffer = BytesIO()
    Image.new("RGB", (8, 6), color=(60, 80, 100)).save(buffer, format="JPEG")
    return buffer.getvalue()


def message_payload(
    *,
    guid: str,
    text: str,
    handle: str = "+14155550123",
    with_photo: bool = False,
) -> dict:
    return {
        "type": "new-message",
        "data": {
            "guid": guid,
            "text": text,
            "isFromMe": False,
            "dateCreated": 1_778_436_000_000,
            "handle": {"address": handle, "service": "iMessage"},
            "chats": [{"guid": f"iMessage;-;{handle}"}],
            "attachments": (
                [
                    {
                        "guid": "attachment-guid",
                        "mimeType": "image/jpeg",
                        "transferName": "IMG_0001.jpeg",
                    }
                ]
                if with_photo
                else []
            ),
        },
    }


class FakePhotoEditor:
    model = "fake-image-editor"

    def edit(self, source_path: Path, output_path: Path, prompt: str) -> None:
        assert source_path.read_bytes().startswith(b"\x89PNG")
        assert "Do not retouch the product itself" in prompt
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(b"\x89PNG\r\n\x1a\nenhanced")


class FakeMessageAdapter(BlueBubblesAdapter):
    def __init__(self) -> None:
        self.sent_texts: list[str] = []
        self.sent_images: list[str] = []

    async def close(self) -> None:
        return None

    async def download_attachment_bytes(self, guid: str) -> bytes:
        assert guid == "attachment-guid"
        return jpeg_bytes()

    async def send_text(self, chat_guid: str, text: str, idempotency_key: str) -> None:
        assert chat_guid.startswith("iMessage")
        assert idempotency_key
        self.sent_texts.append(text)

    async def send_image(self, chat_guid: str, path: str, idempotency_key: str) -> None:
        assert chat_guid.startswith("iMessage")
        assert Path(path).exists()
        assert idempotency_key
        self.sent_images.append(path)


class FakeEbayConnectionService:
    def __init__(self) -> None:
        self.engine = None

    def authorization_url(self, seller_id: str) -> str:
        return f"https://auth.sandbox.ebay.com/oauth2/authorize?state={seller_id}"

    def seller_id_for_state(self, state: str) -> str:
        return state

    async def complete(self, state: str, _code: str) -> EbayConnection:
        assert self.engine is not None
        with Session(self.engine) as session:
            connection = EbayConnection(
                seller_id=state,
                environment="sandbox",
                encrypted_refresh_token="encrypted-test-token",
            )
            session.add(connection)
            session.commit()
            session.refresh(connection)
            return connection

    def publisher_for(self, _seller_id: str):
        return None


class FakeChatInterpreter:
    def __init__(self, result: ChatInterpretation) -> None:
        self.result = result
        self.contexts: list[dict] = []

    async def interpret(self, *, handle: str, text: str, context: dict) -> ChatInterpretation:
        assert handle == "+14155550123"
        assert text
        self.contexts.append(context)
        return self.result


class SlowChatInterpreter:
    def __init__(self) -> None:
        self.active = 0
        self.max_active = 0

    async def interpret(self, *, handle: str, text: str, context: dict) -> ChatInterpretation:
        self.active += 1
        self.max_active = max(self.max_active, self.active)
        await asyncio.sleep(0.03)
        self.active -= 1
        return ChatInterpretation(intent=ChatIntent.REPLY, reply=f"Understood: {text}")


def test_imessage_photo_preview_approval_and_deduplication(tmp_path: Path) -> None:
    adapter = FakeMessageAdapter()
    app = create_app(
        Settings(
            mode=Mode.SIM,
            database_url="sqlite:///:memory:",
            photo_storage_dir=str(tmp_path),
            bb_webhook_secret="webhook-secret",
            seller_handle="+14155550123",
            require_ebay_onboarding=False,
            openai_api_key=None,
        ),
        photo_editor=FakePhotoEditor(),
        message_adapter=adapter,
    )

    with TestClient(app) as client:
        intake = message_payload(
            guid="message-1",
            text="Sony WH-1000XM5 headphones by Sunday 6pm, do not go under $170",
            with_photo=True,
        )
        response = client.post(
            "/webhooks/bluebubbles?secret=webhook-secret",
            json=intake,
        )
        assert response.status_code == 202
        assert response.json()["status"] == "queued"
        assert len(adapter.sent_images) == 2
        assert "Reply APPROVE or REJECT" in adapter.sent_texts[-1]

        with Session(app.state.engine) as session:
            item = session.exec(select(Item)).one()
            assert item.title == "Sony WH-1000XM5 headphones"
            assert item.floor_cents == 17_000
            enhanced = session.exec(
                select(ProductPhoto).where(ProductPhoto.status == PhotoStatus.REVIEW)
            ).one()
            enhanced_id = enhanced.id

        duplicate = client.post(
            "/webhooks/bluebubbles?secret=webhook-secret",
            json=intake,
        )
        assert duplicate.json()["status"] == "duplicate"
        assert len(adapter.sent_images) == 2

        same_content = message_payload(
            guid="message-duplicate-guid",
            text="Sony WH-1000XM5 headphones by Sunday 6pm, do not go under $170",
            with_photo=True,
        )
        duplicate = client.post(
            "/webhooks/bluebubbles?secret=webhook-secret",
            json=same_content,
        )
        assert duplicate.json() == {
            "status": "duplicate",
            "reason": "same_message_content",
        }
        assert len(adapter.sent_images) == 2

        approval = client.post(
            "/webhooks/bluebubbles?secret=webhook-secret",
            json=message_payload(guid="message-2", text="APPROVE"),
        )
        assert approval.json()["status"] == "queued"
        approved_index = next(
            index for index, text in enumerate(adapter.sent_texts) if text.startswith("Approved")
        )
        # the listing flow asks its first question right after the photo review
        assert adapter.sent_texts[approved_index + 1].startswith("two quick things")

        with Session(app.state.engine) as session:
            assert session.get(ProductPhoto, enhanced_id).status == PhotoStatus.APPROVED
            assert len(session.exec(select(WebhookReceipt)).all()) == 2


def test_imessage_webhook_rejects_bad_secret_and_other_senders(tmp_path: Path) -> None:
    adapter = FakeMessageAdapter()
    app = create_app(
        Settings(
            mode=Mode.SIM,
            database_url="sqlite:///:memory:",
            photo_storage_dir=str(tmp_path),
            bb_webhook_secret="webhook-secret",
            seller_handle="+14155550123",
            openai_api_key=None,
        ),
        photo_editor=FakePhotoEditor(),
        message_adapter=adapter,
    )
    with TestClient(app) as client:
        bad_secret = client.post(
            "/webhooks/bluebubbles?secret=wrong",
            json=message_payload(guid="message-1", text="status"),
        )
        assert bad_secret.status_code == 401

        other_sender = client.post(
            "/webhooks/bluebubbles?secret=webhook-secret",
            json=message_payload(guid="message-2", text="status", handle="+14155559999"),
        )
        assert other_sender.status_code == 202
        assert other_sender.json() == {"status": "ignored", "reason": "sender_not_allowed"}


def test_first_message_requires_ebay_and_blocks_photos_until_connected(tmp_path: Path) -> None:
    adapter = FakeMessageAdapter()
    app = create_app(
        Settings(
            mode=Mode.SIM,
            database_url="sqlite:///:memory:",
            photo_storage_dir=str(tmp_path),
            bb_webhook_secret="webhook-secret",
            seller_handle="+14155550123",
            openai_api_key=None,
        ),
        photo_editor=FakePhotoEditor(),
        message_adapter=adapter,
        ebay_connection_service=FakeEbayConnectionService(),
    )

    with TestClient(app) as client:
        first = client.post(
            "/webhooks/bluebubbles?secret=webhook-secret",
            json=message_payload(guid="connect-1", text="hello"),
        )
        assert first.json()["status"] == "queued"
        assert adapter.sent_texts[-1].startswith("Welcome to Liquid")
        assert "auth.sandbox.ebay.com" in adapter.sent_texts[-1]

        blocked = client.post(
            "/webhooks/bluebubbles?secret=webhook-secret",
            json=message_payload(guid="connect-2", text="sell this", with_photo=True),
        )
        assert blocked.json()["status"] == "queued"
        assert adapter.sent_texts[-1].startswith("I cannot process that photo")
        with Session(app.state.engine) as session:
            assert session.exec(select(Item)).all() == []
            conversation = session.exec(select(SellerConversation)).one()
            assert conversation.status == ConversationStatus.AWAITING_EBAY
            session.add(
                EbayConnection(
                    seller_id=conversation.seller_id,
                    environment="sandbox",
                    encrypted_refresh_token="test-token",
                )
            )
            session.commit()

        retry = client.post(
            "/webhooks/bluebubbles?secret=webhook-secret",
            json=message_payload(guid="connect-3", text="STATUS"),
        )
        assert retry.json()["status"] == "queued"
        assert adapter.sent_texts[-1].startswith("No active item")
        with Session(app.state.engine) as session:
            assert session.exec(select(SellerConversation)).one().status == ConversationStatus.READY


def test_unconnected_seller_can_retry_or_check_but_not_skip(tmp_path: Path) -> None:
    adapter = FakeMessageAdapter()
    app = create_app(
        Settings(
            mode=Mode.SIM,
            database_url="sqlite:///:memory:",
            photo_storage_dir=str(tmp_path),
            bb_webhook_secret="webhook-secret",
            seller_handle="+14155550123",
            openai_api_key=None,
        ),
        photo_editor=FakePhotoEditor(),
        message_adapter=adapter,
        ebay_connection_service=FakeEbayConnectionService(),
    )

    with TestClient(app) as client:
        for guid, text in (("edge-1", "hello"), ("edge-2", "retry"), ("edge-3", "done"),
                           ("edge-4", "skip")):
            response = client.post(
                "/webhooks/bluebubbles?secret=webhook-secret",
                json=message_payload(guid=guid, text=text),
            )
            assert response.json()["status"] == "queued"
        assert adapter.sent_texts[-3].startswith("Here is a fresh eBay connection link")
        assert adapter.sent_texts[-2].startswith("I do not see a completed eBay connection")
        assert adapter.sent_texts[-1].startswith("An eBay seller account is required")


def test_ebay_callback_recovers_from_decline_and_completes_on_retry(tmp_path: Path) -> None:
    adapter = FakeMessageAdapter()
    service = FakeEbayConnectionService()
    app = create_app(
        Settings(
            mode=Mode.SIM,
            database_url="sqlite:///:memory:",
            photo_storage_dir=str(tmp_path),
            bb_webhook_secret="webhook-secret",
            seller_handle="+14155550123",
            openai_api_key=None,
        ),
        photo_editor=FakePhotoEditor(),
        message_adapter=adapter,
        ebay_connection_service=service,
    )

    with TestClient(app) as client:
        service.engine = app.state.engine
        client.post(
            "/webhooks/bluebubbles?secret=webhook-secret",
            json=message_payload(guid="callback-1", text="hello"),
        )
        with Session(app.state.engine) as session:
            seller_id = session.exec(select(SellerConversation)).one().seller_id

        declined = client.get(
            "/oauth/ebay/callback",
            params={"state": seller_id, "error": "access_denied"},
        )
        assert declined.status_code == 400
        assert adapter.sent_texts[-1] == "eBay was not connected. Reply RETRY for a fresh link."

        client.post(
            "/webhooks/bluebubbles?secret=webhook-secret",
            json=message_payload(guid="callback-2", text="retry"),
        )
        assert adapter.sent_texts[-1].startswith("Here is a fresh eBay connection link")

        completed = client.get(
            "/oauth/ebay/callback",
            params={"state": seller_id, "code": "authorization-code"},
        )
        assert completed.status_code == 200
        assert adapter.sent_texts[-1].startswith("eBay connected. Setup is complete")
        with Session(app.state.engine) as session:
            assert session.exec(select(EbayConnection)).one().seller_id == seller_id
            assert session.exec(select(SellerConversation)).one().status == ConversationStatus.READY


def test_wildcard_seller_handle_accepts_multiple_sellers(tmp_path: Path) -> None:
    adapter = FakeMessageAdapter()
    app = create_app(
        Settings(
            mode=Mode.SIM,
            database_url="sqlite:///:memory:",
            photo_storage_dir=str(tmp_path),
            bb_webhook_secret="webhook-secret",
            seller_handle="*",
            require_ebay_onboarding=False,
            openai_api_key=None,
        ),
        photo_editor=FakePhotoEditor(),
        message_adapter=adapter,
    )

    with TestClient(app) as client:
        for index, handle in enumerate(("+14155550123", "+14155550456"), start=1):
            response = client.post(
                "/webhooks/bluebubbles?secret=webhook-secret",
                json=message_payload(guid=f"seller-{index}", text="STATUS", handle=handle),
            )
            assert response.json()["status"] == "queued"
        assert adapter.sent_texts == [
            "No active item. Send a product photo to start.",
            "No active item. Send a product photo to start.",
        ]


def test_start_over_cancels_active_draft_and_resets_conversation(tmp_path: Path) -> None:
    adapter = FakeMessageAdapter()
    app = create_app(
        Settings(
            mode=Mode.SIM,
            database_url="sqlite:///:memory:",
            photo_storage_dir=str(tmp_path),
            bb_webhook_secret="webhook-secret",
            seller_handle="+14155550123",
            require_ebay_onboarding=False,
            openai_api_key=None,
        ),
        photo_editor=FakePhotoEditor(),
        message_adapter=adapter,
    )

    with TestClient(app) as client:
        client.post(
            "/webhooks/bluebubbles?secret=webhook-secret",
            json=message_payload(
                guid="reset-1",
                text="Sony WH-1000XM5 headphones",
                with_photo=True,
            ),
        )
        client.post(
            "/webhooks/bluebubbles?secret=webhook-secret",
            json=message_payload(guid="reset-2", text="START OVER"),
        )
        assert adapter.sent_texts[-1].startswith("Started over")
        with Session(app.state.engine) as session:
            assert session.exec(select(Item)).one().status == ItemStatus.CANCELLED
            conversation = session.exec(select(SellerConversation)).one()
            assert conversation.status == ConversationStatus.READY
            assert conversation.active_item_id is None


def test_ai_chat_uses_workflow_context_and_sends_one_reply(tmp_path: Path) -> None:
    adapter = FakeMessageAdapter()
    interpreter = FakeChatInterpreter(
        ChatInterpretation(
            intent=ChatIntent.REPLY,
            reply="Send a product photo, and I will help identify and list it.",
        )
    )
    app = create_app(
        Settings(
            mode=Mode.SIM,
            database_url="sqlite:///:memory:",
            photo_storage_dir=str(tmp_path),
            bb_webhook_secret="webhook-secret",
            seller_handle="+14155550123",
            require_ebay_onboarding=False,
            openai_api_key=None,
        ),
        photo_editor=FakePhotoEditor(),
        message_adapter=adapter,
        chat_interpreter=interpreter,
    )

    with TestClient(app) as client:
        response = client.post(
            "/webhooks/bluebubbles?secret=webhook-secret",
            json=message_payload(guid="ai-1", text="What do I do with this thing?"),
        )
        assert response.json()["status"] == "queued"
        assert adapter.sent_texts == [
            "Send a product photo, and I will help identify and list it."
        ]
        assert interpreter.contexts[0]["conversation_status"] == "ready"
        assert interpreter.contexts[0]["recent_messages"][-1]["text"] == (
            "What do I do with this thing?"
        )
        with Session(app.state.engine) as session:
            turns = session.exec(
                select(ConversationTurn).order_by(ConversationTurn.created_at)
            ).all()
            assert [turn.role for turn in turns] == ["user", "assistant"]


def test_messages_from_one_seller_are_processed_serially(tmp_path: Path) -> None:
    adapter = FakeMessageAdapter()
    interpreter = SlowChatInterpreter()
    app = create_app(
        Settings(
            mode=Mode.SIM,
            database_url="sqlite:///:memory:",
            photo_storage_dir=str(tmp_path),
            bb_webhook_secret="webhook-secret",
            seller_handle="+14155550123",
            require_ebay_onboarding=False,
            openai_api_key=None,
        ),
        photo_editor=FakePhotoEditor(),
        message_adapter=adapter,
        chat_interpreter=interpreter,
    )

    with TestClient(app):
        first = adapter.parse_inbound(message_payload(guid="serial-1", text="first note"))
        second = adapter.parse_inbound(message_payload(guid="serial-2", text="second note"))
        assert first is not None and second is not None

        async def run_both() -> None:
            await asyncio.gather(
                app.state.process_bluebubbles_message(first),
                app.state.process_bluebubbles_message(second),
            )

        asyncio.run(run_both())

    assert interpreter.max_active == 1
    assert adapter.sent_texts == ["Understood: first note", "Understood: second note"]


def test_ai_status_intent_does_not_get_consumed_as_listing_details(tmp_path: Path) -> None:
    adapter = FakeMessageAdapter()
    interpreter = FakeChatInterpreter(ChatInterpretation(intent=ChatIntent.STATUS))
    app = create_app(
        Settings(
            mode=Mode.SIM,
            database_url="sqlite:///:memory:",
            photo_storage_dir=str(tmp_path),
            bb_webhook_secret="webhook-secret",
            seller_handle="+14155550123",
            require_ebay_onboarding=False,
            openai_api_key=None,
        ),
        photo_editor=FakePhotoEditor(),
        message_adapter=adapter,
        chat_interpreter=interpreter,
    )

    with TestClient(app) as client:
        client.post(
            "/webhooks/bluebubbles?secret=webhook-secret",
            json=message_payload(
                guid="ai-status-1",
                text="Sony WH-1000XM5 headphones",
                with_photo=True,
            ),
        )
        client.post(
            "/webhooks/bluebubbles?secret=webhook-secret",
            json=message_payload(guid="ai-status-2", text="approve"),
        )
        client.post(
            "/webhooks/bluebubbles?secret=webhook-secret",
            json=message_payload(guid="ai-status-3", text="Where are we with that?"),
        )

        assert "Current step: awaiting_details" in adapter.sent_texts[-1]
        with Session(app.state.engine) as session:
            conversation = session.exec(select(SellerConversation)).one()
            item = session.exec(select(Item)).one()
            assert conversation.status == ConversationStatus.AWAITING_DETAILS
            assert item.constraints_json["intake_asked"] == ["condition"]
