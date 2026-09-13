from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol


@dataclass(frozen=True, slots=True)
class InboundAttachment:
    guid: str
    mime_type: str | None
    filename: str | None


@dataclass(frozen=True, slots=True)
class InboundMessage:
    guid: str
    handle: str
    chat_guid: str
    destination_handle: str | None
    text: str
    created_at: datetime
    attachments: tuple[InboundAttachment, ...]
    raw: dict[str, Any]


class ChannelAdapter(Protocol):
    async def send_text(self, chat_guid: str, text: str, idempotency_key: str) -> None: ...

    async def send_image(self, chat_guid: str, path: str, idempotency_key: str) -> None: ...

    def parse_inbound(self, payload: dict[str, Any]) -> InboundMessage | None: ...
