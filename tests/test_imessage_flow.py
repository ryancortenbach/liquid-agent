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
    Seller,
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
    addressed_to: str | None = "ryancortenbach77@gmail.com",
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
            "chats": [
                {
                    "guid": f"iMessage;-;{handle}",
                    **({"lastAddressedHandle": addressed_to} if addressed_to is not None else {}),
                }
            ],
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
            bb_allowed_destination="ryancortenbach77@gmail.com",
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
        assert "Want to use it?" in adapter.sent_texts[-1]

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
        assert adapter.sent_texts[-2] == "You bet. I'll use those photos."
        assert adapter.sent_texts[-1].startswith("How would you describe the condition?")

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
            bb_allowed_destination="ryancortenbach77@gmail.com",
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


def test_imessage_only_routes_messages_addressed_to_the_agent_email(tmp_path: Path) -> None:
    adapter = FakeMessageAdapter()
    interpreter = FakeChatInterpreter(
        ChatInterpretation(intent=ChatIntent.REPLY, reply="This must not be sent")
    )
    app = create_app(
        Settings(
            mode=Mode.SIM,
            database_url="sqlite:///:memory:",
            photo_storage_dir=str(tmp_path),
            bb_webhook_secret="webhook-secret",
            bb_allowed_destination="ryancortenbach77@gmail.com",
            seller_handle="*",
            require_ebay_onboarding=False,
            openai_api_key=None,
        ),
        photo_editor=FakePhotoEditor(),
        message_adapter=adapter,
        chat_interpreter=interpreter,
    )
    with TestClient(app) as client:
        ignored = client.post(
            "/webhooks/bluebubbles?secret=webhook-secret",
            json=message_payload(
                guid="destination-1",
                text="Write a response for me",
                addressed_to="+17027428016",
            ),
        )
        assert ignored.json() == {"status": "ignored", "reason": "wrong_destination"}
        assert adapter.sent_texts == []
        assert interpreter.contexts == []
        with Session(app.state.engine) as session:
            assert session.exec(select(WebhookReceipt)).all() == []

        accepted = client.post(
            "/webhooks/bluebubbles?secret=webhook-secret",
            json=message_payload(
                guid="destination-2",
                text="status",
                addressed_to="RyanCortenbach77@GMAIL.COM",
            ),
        )
        assert accepted.json() == {"status": "queued"}
        assert adapter.sent_texts == [
            "Nothing's in progress right now. Send me a photo whenever you're ready."
        ]


def test_first_message_requires_ebay_and_blocks_photos_until_connected(tmp_path: Path) -> None:
    adapter = FakeMessageAdapter()
    app = create_app(
        Settings(
            mode=Mode.SIM,
            database_url="sqlite:///:memory:",
            photo_storage_dir=str(tmp_path),
            bb_webhook_secret="webhook-secret",
            bb_allowed_destination="ryancortenbach77@gmail.com",
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
        assert adapter.sent_texts[-1].startswith("Hey, what's up? Let's connect your eBay")
        assert "auth.sandbox.ebay.com" in adapter.sent_texts[-1]

        blocked = client.post(
            "/webhooks/bluebubbles?secret=webhook-secret",
            json=message_payload(guid="connect-2", text="sell this", with_photo=True),
        )
        assert blocked.json()["status"] == "queued"
        assert adapter.sent_texts[-1].startswith("I've got the photo")
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
        assert adapter.sent_texts[-1].startswith("Nothing's in progress")
        with Session(app.state.engine) as session:
            assert session.exec(select(SellerConversation)).one().status == ConversationStatus.READY


def test_ebay_demo_mode_auto_onboards_without_credentials(tmp_path: Path) -> None:
    adapter = FakeMessageAdapter()
    app = create_app(
        Settings(
            mode=Mode.SIM,
            database_url="sqlite:///:memory:",
            photo_storage_dir=str(tmp_path),
            bb_webhook_secret="webhook-secret",
            bb_allowed_destination="ryancortenbach77@gmail.com",
            seller_handle="+14155550123",
            ebay_demo_mode=True,
            openai_api_key=None,
        ),
        photo_editor=FakePhotoEditor(),
        message_adapter=adapter,
    )

    with TestClient(app) as client:
        first = client.post(
            "/webhooks/bluebubbles?secret=webhook-secret",
            json=message_payload(guid="demo-connect-1", text="hello"),
        )
        assert first.json()["status"] == "queued"
        assert adapter.sent_texts == [
            "Hey, what's up? You're all set with eBay for this demo. "
            "Send me a photo whenever you're ready."
        ]
        with Session(app.state.engine) as session:
            connection = session.exec(select(EbayConnection)).one()
            assert connection.environment == "demo"
            assert session.exec(select(SellerConversation)).one().status == ConversationStatus.READY

        connected = client.post(
            "/webhooks/bluebubbles?secret=webhook-secret",
            json=message_payload(guid="demo-connect-2", text="connect ebay"),
        )
        assert connected.json()["status"] == "queued"
        assert adapter.sent_texts[-1].startswith("You're all set with eBay")


def test_unconnected_seller_can_retry_or_check_but_not_skip(tmp_path: Path) -> None:
    adapter = FakeMessageAdapter()
    app = create_app(
        Settings(
            mode=Mode.SIM,
            database_url="sqlite:///:memory:",
            photo_storage_dir=str(tmp_path),
            bb_webhook_secret="webhook-secret",
            bb_allowed_destination="ryancortenbach77@gmail.com",
            seller_handle="+14155550123",
            openai_api_key=None,
        ),
        photo_editor=FakePhotoEditor(),
        message_adapter=adapter,
        ebay_connection_service=FakeEbayConnectionService(),
    )

    with TestClient(app) as client:
        for guid, text in (
            ("edge-1", "hello"),
            ("edge-2", "retry"),
            ("edge-3", "done"),
            ("edge-4", "skip"),
        ):
            response = client.post(
                "/webhooks/bluebubbles?secret=webhook-secret",
                json=message_payload(guid=guid, text=text),
            )
            assert response.json()["status"] == "queued"
        assert adapter.sent_texts[-3].startswith("No problem. Here's a fresh")
        assert adapter.sent_texts[-2].startswith("You're not connected yet")
        assert adapter.sent_texts[-1].startswith("We can't skip this one")


def test_shared_ebay_publisher_does_not_bypass_seller_onboarding(tmp_path: Path) -> None:
    adapter = FakeMessageAdapter()
    app = create_app(
        Settings(
            mode=Mode.SIM,
            database_url="sqlite:///:memory:",
            photo_storage_dir=str(tmp_path),
            bb_webhook_secret="webhook-secret",
            bb_allowed_destination="ryancortenbach77@gmail.com",
            seller_handle="+14155550123",
            openai_api_key=None,
        ),
        photo_editor=FakePhotoEditor(),
        message_adapter=adapter,
        ebay_connection_service=FakeEbayConnectionService(),
        ebay_publisher=object(),  # type: ignore[arg-type]
    )

    with TestClient(app) as client:
        response = client.post(
            "/webhooks/bluebubbles?secret=webhook-secret",
            json=message_payload(guid="shared-ebay-1", text="hello"),
        )

        assert response.json()["status"] == "queued"
        assert adapter.sent_texts[-1].startswith("Hey, what's up? Let's connect your eBay")


def test_ebay_callback_recovers_from_decline_and_completes_on_retry(tmp_path: Path) -> None:
    adapter = FakeMessageAdapter()
    service = FakeEbayConnectionService()
    app = create_app(
        Settings(
            mode=Mode.SIM,
            database_url="sqlite:///:memory:",
            photo_storage_dir=str(tmp_path),
            bb_webhook_secret="webhook-secret",
            bb_allowed_destination="ryancortenbach77@gmail.com",
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
        assert adapter.sent_texts[-1] == (
            "No problem, eBay didn't connect. Reply RETRY for a fresh link."
        )

        client.post(
            "/webhooks/bluebubbles?secret=webhook-secret",
            json=message_payload(guid="callback-2", text="retry"),
        )
        assert adapter.sent_texts[-1].startswith("No problem. Here's a fresh")

        completed = client.get(
            "/oauth/ebay/callback",
            params={"state": seller_id, "code": "authorization-code"},
        )
        assert completed.status_code == 200
        assert adapter.sent_texts[-1].startswith("You're connected to eBay")
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
            bb_allowed_destination="ryancortenbach77@gmail.com",
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
            "Nothing's in progress right now. Send me a photo whenever you're ready.",
            "Nothing's in progress right now. Send me a photo whenever you're ready.",
        ]
        with Session(app.state.engine) as session:
            assert len(session.exec(select(Seller)).all()) == 2
            assert len(session.exec(select(SellerConversation)).all()) == 2


def test_start_over_cancels_active_draft_and_resets_conversation(tmp_path: Path) -> None:
    adapter = FakeMessageAdapter()
    app = create_app(
        Settings(
            mode=Mode.SIM,
            database_url="sqlite:///:memory:",
            photo_storage_dir=str(tmp_path),
            bb_webhook_secret="webhook-secret",
            bb_allowed_destination="ryancortenbach77@gmail.com",
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
        assert adapter.sent_texts[-1].startswith("All set. We're starting fresh")
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
            bb_allowed_destination="ryancortenbach77@gmail.com",
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
        assert adapter.sent_texts == ["Send a product photo, and I will help identify and list it."]
        assert interpreter.contexts[0]["conversation_status"] == "ready"
        assert interpreter.contexts[0]["recent_messages"][-1]["text"] == (
            "What do I do with this thing?"
        )
        with Session(app.state.engine) as session:
            turns = session.exec(
                select(ConversationTurn).order_by(ConversationTurn.created_at)
            ).all()
            assert [turn.role for turn in turns] == ["user", "assistant"]


def test_long_multi_item_message_bypasses_ai_and_requests_separate_photos(
    tmp_path: Path,
) -> None:
    adapter = FakeMessageAdapter()
    interpreter = FakeChatInterpreter(
        ChatInterpretation(intent=ChatIntent.REPLY, reply="This should not be sent.")
    )
    app = create_app(
        Settings(
            mode=Mode.SIM,
            database_url="sqlite:///:memory:",
            photo_storage_dir=str(tmp_path),
            bb_webhook_secret="webhook-secret",
            bb_allowed_destination="ryancortenbach77@gmail.com",
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
            json=message_payload(
                guid="separate-text-1",
                text=("I want to sell my AirPods and then I want to sell my water bottle"),
            ),
        )

        assert response.json()["status"] == "queued"
        assert interpreter.contexts == []
        assert adapter.sent_texts == [
            "I caught 2 separate items and won't combine them:\n"
            "1. AirPods\n"
            "2. water bottle\n"
            "Send one photo per item, or attach everything with a BATCH label."
        ]
        with Session(app.state.engine) as session:
            assert session.exec(select(Item)).all() == []


def test_messages_from_one_seller_are_processed_serially(tmp_path: Path) -> None:
    adapter = FakeMessageAdapter()
    interpreter = SlowChatInterpreter()
    app = create_app(
        Settings(
            mode=Mode.SIM,
            database_url="sqlite:///:memory:",
            photo_storage_dir=str(tmp_path),
            bb_webhook_secret="webhook-secret",
            bb_allowed_destination="ryancortenbach77@gmail.com",
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
            bb_allowed_destination="ryancortenbach77@gmail.com",
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

        assert "waiting on your last answer" in adapter.sent_texts[-1]
        with Session(app.state.engine) as session:
            conversation = session.exec(select(SellerConversation)).one()
            item = session.exec(select(Item)).one()
            assert conversation.status == ConversationStatus.AWAITING_DETAILS
            assert item.constraints_json["intake_asked"] == ["condition"]


def test_imessage_refuses_everything_when_no_destination_is_configured(tmp_path: Path) -> None:
    """An unset BB_ALLOWED_DESTINATION must block inbound, never open it to every text."""
    adapter = FakeMessageAdapter()
    interpreter = FakeChatInterpreter(
        ChatInterpretation(intent=ChatIntent.REPLY, reply="This must not be sent")
    )
    app = create_app(
        Settings(
            mode=Mode.SIM,
            database_url="sqlite:///:memory:",
            photo_storage_dir=str(tmp_path),
            bb_webhook_secret="webhook-secret",
            bb_allowed_destination=None,
            seller_handle="*",
            require_ebay_onboarding=False,
            openai_api_key=None,
        ),
        photo_editor=FakePhotoEditor(),
        message_adapter=adapter,
        chat_interpreter=interpreter,
    )
    with TestClient(app) as client:
        for addressed_to in ("+17027428016", "ryancortenbach77@gmail.com", None):
            response = client.post(
                "/webhooks/bluebubbles?secret=webhook-secret",
                json=message_payload(
                    guid=f"unconfigured-{addressed_to}",
                    text="Write a response for me",
                    addressed_to=addressed_to,
                ),
            )
            assert response.json() == {
                "status": "ignored",
                "reason": "destination_not_configured",
            }
        assert adapter.sent_texts == []
        assert interpreter.contexts == []
        with Session(app.state.engine) as session:
            assert session.exec(select(WebhookReceipt)).all() == []


def test_imessage_blank_destination_setting_is_treated_as_unconfigured(tmp_path: Path) -> None:
    """Whitespace in the env file must not be read as a permissive wildcard."""
    adapter = FakeMessageAdapter()
    app = create_app(
        Settings(
            mode=Mode.SIM,
            database_url="sqlite:///:memory:",
            photo_storage_dir=str(tmp_path),
            bb_webhook_secret="webhook-secret",
            bb_allowed_destination="   ",
            seller_handle="*",
            require_ebay_onboarding=False,
            openai_api_key=None,
        ),
        photo_editor=FakePhotoEditor(),
        message_adapter=adapter,
    )
    with TestClient(app) as client:
        response = client.post(
            "/webhooks/bluebubbles?secret=webhook-secret",
            json=message_payload(
                guid="blank-destination",
                text="status",
                addressed_to="ryancortenbach77@gmail.com",
            ),
        )
        assert response.json() == {
            "status": "ignored",
            "reason": "destination_not_configured",
        }
        assert adapter.sent_texts == []


def test_destination_wildcard_accepts_any_address_but_still_checks_the_sender(
    tmp_path: Path,
) -> None:
    """BlueBubbles cannot report the destination, so "*" leans on the sender allowlist."""
    adapter = FakeMessageAdapter()
    app = create_app(
        Settings(
            mode=Mode.SIM,
            database_url="sqlite:///:memory:",
            photo_storage_dir=str(tmp_path),
            bb_webhook_secret="webhook-secret",
            bb_allowed_destination="*",
            seller_handle="+14155550123",
            require_ebay_onboarding=False,
            openai_api_key=None,
        ),
        photo_editor=FakePhotoEditor(),
        message_adapter=adapter,
    )
    with TestClient(app) as client:
        allowed = client.post(
            "/webhooks/bluebubbles?secret=webhook-secret",
            json=message_payload(
                guid="wildcard-1",
                text="status",
                handle="+14155550123",
                addressed_to="+17027428016",
            ),
        )
        assert allowed.json() == {"status": "queued"}

        stranger = client.post(
            "/webhooks/bluebubbles?secret=webhook-secret",
            json=message_payload(
                guid="wildcard-2",
                text="status",
                handle="+12125550147",
                addressed_to="+17027428016",
            ),
        )
        assert stranger.json() == {"status": "ignored", "reason": "sender_not_allowed"}
