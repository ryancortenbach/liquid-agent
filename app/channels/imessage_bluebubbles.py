from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

import httpx

from app.channels.base import InboundAttachment, InboundMessage


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
        return InboundMessage(
            guid=guid,
            handle=handle,
            chat_guid=chats[0]["guid"],
            text=(data.get("text") or "").strip(),
            created_at=datetime.fromtimestamp(created_ms / 1000, tz=UTC),
            attachments=attachments,
            raw=payload,
        )

    async def ping(self) -> bool:
        response = await self._client.get(
            f"{self.server_url}/api/v1/ping", params={"password": self.password}
        )
        response.raise_for_status()
        return True

    async def send_text(self, chat_guid: str, text: str, idempotency_key: str) -> None:
        response = await self._client.post(
            f"{self.server_url}/api/v1/message/text",
            params={"password": self.password},
            json={
                "chatGuid": chat_guid,
                "tempGuid": idempotency_key or str(uuid4()),
                "message": text,
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
        response = await self._client.get(
            f"{self.server_url}/api/v1/attachment/{guid}/download",
            params={"password": self.password},
        )
        response.raise_for_status()
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(response.content)
        return destination
