"""The Mac's iMessage account is shared: Liquid must never answer the wrong conversation."""

from __future__ import annotations

from fastapi.testclient import TestClient
from test_imessage_flow import FakeMessageAdapter, FakePhotoEditor, message_payload

from app.channels.imessage_bluebubbles import BlueBubblesAdapter, is_group_chat
from app.config import Mode, Settings
from app.main import create_app

LIQUID = "liquid@icloud.com"
PHONE = "+16505550100"


class LookupAdapter(FakeMessageAdapter):
    """Like the real adapter, resolves a chat's alias over REST when the webhook lacks it."""

    def __init__(self, destinations: dict[str, str | None], *, fail: bool = False) -> None:
        super().__init__()
        self.destinations = destinations
        self.fail = fail
        self.lookups: list[str] = []

    async def chat_destination(self, chat_guid: str) -> str | None:
        self.lookups.append(chat_guid)
        if self.fail:
            raise RuntimeError("BlueBubbles is down")
        return self.destinations.get(chat_guid)


def settings(tmp_path, **overrides) -> Settings:
    values = dict(
        messages_db_path=str(tmp_path / "no-chat.db"),
        mode=Mode.SIM,
        database_url="sqlite:///:memory:",
        photo_storage_dir=str(tmp_path),
        bb_password="bb-password",
        bb_webhook_secret="webhook-secret",
        seller_handle="*",
        bb_allowed_destination=LIQUID,
        require_ebay_onboarding=False,
        ebay_demo_mode=True,
    )
    values.update(overrides)
    return Settings(**values)


def post(client: TestClient, payload: dict) -> dict:
    response = client.post("/webhooks/bluebubbles?secret=webhook-secret", json=payload)
    assert response.status_code == 202, response.text
    return response.json()


def group_payload(guid: str, text: str) -> dict:
    payload = message_payload(guid=guid, text=text, addressed_to=LIQUID)
    payload["data"]["chats"][0].update(
        {
            "guid": "iMessage;+;chat123456789",
            "style": 43,
            "participants": [{"address": "+14155550123"}, {"address": "+14155550124"}],
        }
    )
    return payload


def test_group_chat_detection_covers_style_guid_and_participants() -> None:
    assert is_group_chat({"guid": "iMessage;+;chat1", "style": 43})
    assert is_group_chat({"guid": "iMessage;-;+1", "participants": [{}, {}]})
    assert is_group_chat({"guid": "iMessage;+;chat9"})
    assert not is_group_chat({"guid": "iMessage;-;+14155550123", "style": 45, "participants": [{}]})
    parsed = BlueBubblesAdapter("http://bb", "pw").parse_inbound(group_payload("g", "hi"))
    assert parsed is not None and parsed.is_group is True


def test_group_chats_are_ignored_by_default(tmp_path) -> None:
    adapter = FakeMessageAdapter()
    app = create_app(settings(tmp_path), photo_editor=FakePhotoEditor(), message_adapter=adapter)
    with TestClient(app) as client:
        assert post(client, group_payload("group-1", "hello")) == {
            "status": "ignored",
            "reason": "group_chat",
        }
        assert adapter.sent_texts == []
        # a direct message to the Liquid alias still works
        assert post(client, message_payload(guid="dm-1", text="hello", addressed_to=LIQUID))[
            "status"
        ] == "queued"
        assert adapter.sent_texts


def test_group_chats_can_be_allowed_explicitly(tmp_path) -> None:
    adapter = FakeMessageAdapter()
    app = create_app(
        settings(tmp_path, bb_allow_group_chats=True),
        photo_editor=FakePhotoEditor(),
        message_adapter=adapter,
    )
    with TestClient(app) as client:
        assert post(client, group_payload("group-2", "hello"))["status"] == "queued"


def test_texts_to_the_owners_phone_number_are_ignored(tmp_path) -> None:
    adapter = LookupAdapter({"iMessage;-;+14155550123": None})
    app = create_app(settings(tmp_path), photo_editor=FakePhotoEditor(), message_adapter=adapter)
    with TestClient(app) as client:
        personal = message_payload(guid="p-1", text="hey ryan", addressed_to="+16505550100")
        assert post(client, personal) == {"status": "ignored", "reason": "wrong_destination"}
        # the webhook lacked the alias and the server has none for the chat: still refused
        unknown = message_payload(guid="p-2", text="hey", addressed_to=None)
        assert post(client, unknown) == {"status": "ignored", "reason": "wrong_destination"}
        assert adapter.sent_texts == []


def test_blank_destination_fails_closed(tmp_path) -> None:
    adapter = FakeMessageAdapter()
    app = create_app(
        settings(tmp_path, bb_allowed_destination=None),
        photo_editor=FakePhotoEditor(),
        message_adapter=adapter,
    )
    with TestClient(app) as client:
        result = post(client, message_payload(guid="open-1", text="hello", addressed_to=LIQUID))
        assert result == {"status": "ignored", "reason": "destination_not_configured"}
        assert adapter.sent_texts == []


def test_comma_separated_sender_allowlist(tmp_path) -> None:
    adapter = FakeMessageAdapter()
    app = create_app(
        settings(tmp_path, seller_handle="+14155550123, +1 (650) 555-0100"),
        photo_editor=FakePhotoEditor(),
        message_adapter=adapter,
    )
    with TestClient(app) as client:
        first = message_payload(guid="a-1", text="hello", addressed_to=LIQUID)
        second = message_payload(
            guid="a-2", text="hello", handle="+16505550100", addressed_to=LIQUID
        )
        stranger = message_payload(
            guid="a-3", text="hello", handle="+12125550199", addressed_to=LIQUID
        )
        assert post(client, first)["status"] == "queued"
        assert post(client, second)["status"] == "queued"
        assert post(client, stranger) == {"status": "ignored", "reason": "sender_not_allowed"}


def test_webhook_without_alias_is_resolved_over_rest(tmp_path) -> None:
    """BlueBubbles webhooks never carry lastAddressedHandle; the chat lookup supplies it."""
    adapter = LookupAdapter({"iMessage;-;+14155550123": LIQUID, "iMessage;-;+12125550199": PHONE})
    app = create_app(settings(tmp_path), photo_editor=FakePhotoEditor(), message_adapter=adapter)
    with TestClient(app) as client:
        liquid = message_payload(guid="rest-1", text="hello", addressed_to=None)
        assert post(client, liquid)["status"] == "queued"
        assert adapter.lookups == ["iMessage;-;+14155550123"]
        assert adapter.sent_texts

        personal = message_payload(
            guid="rest-2", text="hey", handle="+12125550199", addressed_to=None
        )
        assert post(client, personal) == {"status": "ignored", "reason": "wrong_destination"}
        assert adapter.lookups[-1] == "iMessage;-;+12125550199"


def test_destination_lookup_failure_refuses_the_message(tmp_path) -> None:
    adapter = LookupAdapter({}, fail=True)
    app = create_app(settings(tmp_path), photo_editor=FakePhotoEditor(), message_adapter=adapter)
    with TestClient(app) as client:
        result = post(client, message_payload(guid="down-1", text="hello", addressed_to=None))
        assert result == {"status": "ignored", "reason": "destination_lookup_failed"}
        assert adapter.sent_texts == []


def test_tapbacks_and_edits_are_not_seller_messages(tmp_path) -> None:
    adapter = FakeMessageAdapter()
    app = create_app(settings(tmp_path), photo_editor=FakePhotoEditor(), message_adapter=adapter)
    with TestClient(app) as client:
        payload = message_payload(guid="tapback-1", text='Loved "hello"', addressed_to=LIQUID)
        payload["data"]["associatedMessageGuid"] = "p:0/some-message"
        payload["data"]["associatedMessageType"] = 2000
        assert post(client, payload) == {"status": "ignored"}
        assert adapter.sent_texts == []


def test_exact_alias_comes_from_messages_database_when_readable(tmp_path) -> None:
    import sqlite3

    db_path = tmp_path / "chat.db"
    connection = sqlite3.connect(db_path)
    connection.execute(
        "CREATE TABLE message (guid TEXT, is_from_me INTEGER, destination_caller_id TEXT)"
    )
    connection.executemany(
        "INSERT INTO message VALUES (?, ?, ?)",
        [("db-1", 0, LIQUID), ("db-2", 0, PHONE)],
    )
    connection.commit()
    connection.close()
    # the chat-level alias says "phone" for both: only the per-message column tells them apart
    adapter = LookupAdapter({"iMessage;-;+14155550123": PHONE})
    app = create_app(
        settings(tmp_path, messages_db_path=str(db_path)),
        photo_editor=FakePhotoEditor(),
        message_adapter=adapter,
    )
    with TestClient(app) as client:
        assert app.state.messages_db is not None
        to_liquid = message_payload(guid="db-1", text="hello", addressed_to=None)
        assert post(client, to_liquid)["status"] == "queued"
        to_phone = message_payload(guid="db-2", text="hey ryan", addressed_to=None)
        assert post(client, to_phone) == {"status": "ignored", "reason": "wrong_destination"}
        assert adapter.lookups == []


def test_star_destination_accepts_any_alias(tmp_path) -> None:
    adapter = FakeMessageAdapter()
    app = create_app(
        settings(tmp_path, bb_allowed_destination="*", seller_handle="+14155550123"),
        photo_editor=FakePhotoEditor(),
        message_adapter=adapter,
    )
    with TestClient(app) as client:
        result = post(client, message_payload(guid="any-1", text="hello", addressed_to=None))
        assert result["status"] == "queued"
