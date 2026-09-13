from __future__ import annotations

import hashlib
import json
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

import httpx

from app.channels.base import InboundAttachment, InboundMessage


def plain_dashes(text: str) -> str:
    """Strip em and en dashes from anything Liquid sends to a seller.

    The chat model writes them unprompted, so filter at the one place every
    outgoing message passes through rather than trusting a prompt to comply.
    A dash used as a parenthetical becomes a comma; a numeric range keeps a
    plain hyphen.
    """
    cleaned = re.sub(r"\s*[\u2014\u2013]\s*", ", ", text)
    cleaned = re.sub(r"(?<=\d), (?=\d)", "-", cleaned)
    cleaned = re.sub(r",\s*,", ",", cleaned)
    cleaned = re.sub(r",\s*([.!?])", r"\1", cleaned)
    return cleaned.strip()


def inbound_fingerprint(message: InboundMessage) -> str:
    """Identify one visible message even if BlueBubbles emits more than one GUID for it."""
    payload = {
        "handle": message.handle.strip().lower(),
        "chat_guid": message.chat_guid,
        "destination_handle": (message.destination_handle or "").strip().lower(),
        "text": " ".join(message.text.split()),
        "created_second": int(message.created_at.timestamp()),
        "attachments": sorted(
            ((value.mime_type or "").lower(), (value.filename or "").lower())
            for value in message.attachments
        ),
    }
    encoded = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode()
    return hashlib.sha256(encoded).hexdigest()


GROUP_CHAT_STYLE = 43  # Messages.app chat.style: 43 = group, 45 = one-to-one


def is_group_chat(chat: dict[str, Any]) -> bool:
    """True for group threads; a reply there would go to everyone in the group."""
    if chat.get("style") == GROUP_CHAT_STYLE or chat.get("isGroup") is True:
        return True
    participants = chat.get("participants")
    if isinstance(participants, list) and len(participants) > 1:
        return True
    return ";+;" in str(chat.get("guid") or "")


class BlueBubblesAdapter:
    def __init__(
        self,
        server_url: str,
        password: str,
        *,
        timeout_seconds: float = 10,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.server_url = server_url.rstrip("/")
        self.password = password
        self._client = client or httpx.AsyncClient(timeout=timeout_seconds)
        self._owns_client = client is None

    async def close(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    @staticmethod
    def parse_chat_policy(payload: dict[str, Any]) -> tuple[str | None, bool]:
        """(destination alias, is_group) for a webhook payload, without full validation."""
        chats = (payload.get("data") or {}).get("chats") or []
        if not chats:
            return None, False
        return chats[0].get("lastAddressedHandle"), is_group_chat(chats[0])

    def parse_inbound(self, payload: dict[str, Any]) -> InboundMessage | None:
        if payload.get("type") != "new-message":
            return None
        data = payload.get("data") or {}
        if data.get("isFromMe") is True:
            return None
        handle = (data.get("handle") or {}).get("address")
        chats = data.get("chats") or []
        guid = data.get("guid")
        if not handle or not chats or not guid:
            raise ValueError("BlueBubbles message is missing guid, handle, or chat")
        created_ms = data.get("dateCreated")
        if not isinstance(created_ms, int | float):
            raise ValueError("BlueBubbles message is missing dateCreated")
        attachments = tuple(
            InboundAttachment(
                guid=attachment["guid"],
                mime_type=attachment.get("mimeType"),
                filename=attachment.get("transferName"),
            )
            for attachment in data.get("attachments") or []
            if attachment.get("guid")
        )
        chat = chats[0]
        return InboundMessage(
            guid=guid,
            handle=handle,
            chat_guid=chat["guid"],
            destination_handle=chat.get("lastAddressedHandle"),
            text=(data.get("text") or "").strip(),
            created_at=datetime.fromtimestamp(created_ms / 1000, tz=UTC),
            attachments=attachments,
            raw=payload,
            is_group=is_group_chat(chat),
        )

    async def ping(self) -> bool:
        response = await self._client.get(
            f"{self.server_url}/api/v1/ping", params={"password": self.password}
        )
        response.raise_for_status()
        return True

    async def register_webhook(self, url: str) -> dict[str, Any]:
        response = await self._client.get(
            f"{self.server_url}/api/v1/webhook",
            params={"password": self.password},
        )
        response.raise_for_status()
        existing = response.json().get("data") or []
        if any(webhook.get("url") == url for webhook in existing):
            return {"registered": False, "reason": "already_registered"}

        response = await self._client.post(
            f"{self.server_url}/api/v1/webhook",
            params={"password": self.password},
            json={"url": url, "events": ["new-message"]},
        )
        response.raise_for_status()
        return {"registered": True, "webhook": response.json().get("data")}

    async def send_text(self, chat_guid: str, text: str, idempotency_key: str) -> None:
        response = await self._client.post(
            f"{self.server_url}/api/v1/message/text",
            params={"password": self.password},
            json={
                "chatGuid": chat_guid,
                "tempGuid": idempotency_key or str(uuid4()),
                "message": plain_dashes(text),
                "method": "apple-script",
            },
        )
        response.raise_for_status()

    async def send_image(self, chat_guid: str, path: str, idempotency_key: str) -> None:
        image_path = Path(path)
        with image_path.open("rb") as image_file:
            response = await self._client.post(
                f"{self.server_url}/api/v1/message/attachment",
                params={"password": self.password},
                data={
                    "chatGuid": chat_guid,
                    "tempGuid": idempotency_key or str(uuid4()),
                    "name": image_path.name,
                },
                files={"attachment": (image_path.name, image_file)},
            )
        response.raise_for_status()

    async def download_attachment(self, guid: str, destination: Path) -> Path:
        content = await self.download_attachment_bytes(guid)
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(content)
        return destination

    async def download_attachment_bytes(self, guid: str) -> bytes:
        response = await self._client.get(
            f"{self.server_url}/api/v1/attachment/{guid}/download",
            params={"password": self.password},
        )
        response.raise_for_status()
        return response.content
