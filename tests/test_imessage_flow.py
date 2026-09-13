from __future__ import annotations

from io import BytesIO
from pathlib import Path

from fastapi.testclient import TestClient
from PIL import Image
from sqlmodel import Session, select

from app.channels.imessage_bluebubbles import BlueBubblesAdapter
from app.config import Mode, Settings
from app.main import create_app
from app.models import Item, PhotoStatus, ProductPhoto, WebhookReceipt


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
    def authorization_url(self, seller_id: str) -> str:
        return f"https://auth.sandbox.ebay.com/oauth2/authorize?seller={seller_id}"

    def publisher_for(self, _seller_id: str):
        return None


def test_imessage_photo_preview_approval_and_deduplication(tmp_path: Path) -> None:
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


def test_imessage_connect_ebay_returns_seller_specific_link(tmp_path: Path) -> None:
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
        response = client.post(
            "/webhooks/bluebubbles?secret=webhook-secret",
            json=message_payload(guid="connect-1", text="CONNECT EBAY"),
        )

        assert response.json()["status"] == "queued"
        assert adapter.sent_texts[-1].startswith("Open this secure link")
        assert "auth.sandbox.ebay.com" in adapter.sent_texts[-1]


def test_wildcard_seller_handle_accepts_multiple_sellers(tmp_path: Path) -> None:
    adapter = FakeMessageAdapter()
    app = create_app(
        Settings(
            mode=Mode.SIM,
            database_url="sqlite:///:memory:",
            photo_storage_dir=str(tmp_path),
            bb_webhook_secret="webhook-secret",
            seller_handle="*",
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
