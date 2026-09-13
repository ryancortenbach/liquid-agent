from __future__ import annotations

from app.channels.imessage_bluebubbles import BlueBubblesAdapter


def payload(*, from_me: bool = False) -> dict:
    return {
        "type": "new-message",
        "data": {
            "guid": "message-guid",
            "text": "sell this by sunday 6pm",
            "isFromMe": from_me,
            "dateCreated": 1_778_436_000_000,
            "handle": {"address": "+14155550123", "service": "iMessage"},
            "chats": [{"guid": "iMessage;-;+14155550123"}],
            "attachments": [
                {
                    "guid": "attachment-guid",
                    "mimeType": "image/jpeg",
                    "transferName": "IMG_0001.jpeg",
                }
            ],
        },
    }


def test_parse_inbound_message() -> None:
    adapter = BlueBubblesAdapter("http://localhost:1234", "secret")
    message = adapter.parse_inbound(payload())

    assert message is not None
    assert message.handle == "+14155550123"
    assert message.text == "sell this by sunday 6pm"
    assert message.attachments[0].guid == "attachment-guid"


def test_ignore_our_own_outbound_message() -> None:
    adapter = BlueBubblesAdapter("http://localhost:1234", "secret")
    assert adapter.parse_inbound(payload(from_me=True)) is None
