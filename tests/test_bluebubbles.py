from __future__ import annotations

import httpx
import pytest

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


@pytest.mark.asyncio
async def test_register_webhook_once() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.method == "GET":
            return httpx.Response(200, json={"data": []})
        return httpx.Response(200, json={"data": {"id": 7}})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    adapter = BlueBubblesAdapter("http://localhost:1234", "secret", client=client)
    result = await adapter.register_webhook("https://example.com/webhooks/bluebubbles?secret=x")

    assert result["registered"] is True
    assert [request.method for request in requests] == ["GET", "POST"]
    assert requests[1].read() == (
        b'{"url":"https://example.com/webhooks/bluebubbles?secret=x","events":["new-message"]}'
    )
    await client.aclose()


@pytest.mark.asyncio
async def test_download_attachment_bytes() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"photo")

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    adapter = BlueBubblesAdapter("http://localhost:1234", "secret", client=client)

    assert await adapter.download_attachment_bytes("attachment-guid") == b"photo"
    await client.aclose()
