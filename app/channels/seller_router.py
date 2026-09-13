from __future__ import annotations

import mimetypes
import re
from collections.abc import Callable
from datetime import datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

from dateparser import parse as parse_date
from sqlalchemy import Engine
from sqlmodel import Session, select

from app.channels.base import InboundMessage
from app.channels.imessage_bluebubbles import BlueBubblesAdapter
from app.clock import Clock
from app.inbound.identify import (
    Identifier,
    ItemIdentity,
    apply_identity,
    interpret_confirmation,
)
from app.ledger import write_decision
from app.models import (
    ConditionGrade,
    ConversationStatus,
    Item,
    ItemStatus,
    PhotoRole,
    PhotoStatus,
    ProductPhoto,
    Seller,
    SellerConversation,
)
from app.photos.editor import PhotoPreset, ProductPhotoEditor
from app.photos.pipeline import PhotoPipelineError, enhance_product_photo
from app.photos.storage import PhotoStorage

APPROVE_WORDS = {"approve", "approved", "yes", "use it", "looks good"}
REJECT_WORDS = {"reject", "no", "do not use", "don't use it"}
TERMINAL_ITEM_STATUSES = {
    ItemStatus.SOLD,
    ItemStatus.DONE,
    ItemStatus.EXPIRED,
    ItemStatus.CANCELLED,
}


def canonical_handle(value: str) -> str:
    stripped = value.strip().lower()
    if "@" in stripped:
        return stripped
    digits = "".join(character for character in stripped if character.isdigit())
    return f"+{digits}" if stripped.startswith("+") else digits


def parse_floor_cents(text: str) -> int:
    patterns = (
        r"(?:minimum|min|floor)\s*(?:price\s*)?(?:is\s*)?\$?([0-9]+(?:\.[0-9]{1,2})?)",
        (
            r"(?:do not|don't|dont)\s+(?:go|sell)\s+(?:for\s+)?"
            r"(?:below|under)\s*\$?([0-9]+(?:\.[0-9]{1,2})?)"
        ),
        r"not\s+(?:below|under)\s*\$?([0-9]+(?:\.[0-9]{1,2})?)",
    )
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            return int(Decimal(match.group(1)) * 100)
    return 0


def parse_deadline(text: str, now: datetime, timezone: str) -> datetime:
    match = re.search(r"(?:by|before|deadline(?:\s+is)?)\s+(.+)", text, flags=re.IGNORECASE)
    if not match:
        return now + timedelta(hours=72)
    candidate = re.split(
        r"[,;]|(?:do not|don't|dont)\s+(?:go|sell)|(?:minimum|min|floor)\s*(?:price)?",
        match.group(1),
        maxsplit=1,
        flags=re.IGNORECASE,
    )[0].strip()
    parsed = parse_date(
        candidate,
        settings={
            "PREFER_DATES_FROM": "future",
            "RELATIVE_BASE": now.astimezone(ZoneInfo(timezone)).replace(tzinfo=None),
            "RETURN_AS_TIMEZONE_AWARE": True,
            "TIMEZONE": timezone,
        },
    )
    if parsed is None:
        return now + timedelta(hours=72)
    return parsed.astimezone(now.tzinfo)


def parse_title(text: str) -> str:
    candidate = re.split(
        r"\s+(?:by|before|deadline|minimum|min|floor|do not|don't|dont|not under|not below)\b",
        text.strip(),
        maxsplit=1,
        flags=re.IGNORECASE,
    )[0]
    candidate = re.sub(r"^(?:please\s+)?(?:sell|list)\s+", "", candidate, flags=re.IGNORECASE)
    candidate = candidate.strip(" .,:;-")
    if candidate.lower() in {"", "this", "this item", "these", "it"}:
        return "Item from iMessage"
    return candidate[:120]


class SellerMessageRouter:
    def __init__(
        self,
        *,
        engine: Engine,
        clock: Clock,
        adapter: BlueBubblesAdapter,
        editor: ProductPhotoEditor | None,
        storage: PhotoStorage,
        seller_handle: str,
        timezone: str,
        ebay_authorization_url: Callable[[str], str] | None = None,
        identifier: Identifier | None = None,
    ) -> None:
        self.engine = engine
        self.clock = clock
        self.adapter = adapter
        self.editor = editor
        self.storage = storage
        self.seller_handle = (
            None if seller_handle.strip() == "*" else canonical_handle(seller_handle)
        )
        self.timezone = timezone
        self.ebay_authorization_url = ebay_authorization_url
        self.identifier = identifier

    def accepts(self, message: InboundMessage) -> bool:
        return self.seller_handle is None or canonical_handle(message.handle) == self.seller_handle

    async def route(self, message: InboundMessage) -> None:
        if not self.accepts(message):
            return
        lowered = message.text.strip().lower()
        if lowered == "connect ebay":
            await self._connect_ebay(message)
            return
        if not message.attachments and await self._confirm_identity(message):
            return
        if lowered in APPROVE_WORDS:
            await self._review_pending(message, approved=True)
            return
        if lowered in REJECT_WORDS:
            await self._review_pending(message, approved=False)
            return
        if lowered == "status":
            await self._send_status(message)
            return
        if message.attachments:
            await self._process_photo(message)
            return
        await self.adapter.send_text(
            message.chat_guid,
            (
                "Send a product photo with a message like: Sony WH-1000XM5 headphones, "
                "sell by Sunday 6pm, do not go under $170. You can also reply STATUS."
            ),
            f"{message.guid}:help",
        )

    async def _connect_ebay(self, message: InboundMessage) -> None:
        if self.ebay_authorization_url is None:
            response = "eBay connection is not configured yet."
        else:
            with Session(self.engine) as session:
                conversation = self._get_or_create_conversation(session, message)
                seller_id = conversation.seller_id
                session.commit()
            response = (
                "Open this secure link and approve access on eBay. "
                f"The link expires in 10 minutes: {self.ebay_authorization_url(seller_id)}"
            )
        await self.adapter.send_text(
            message.chat_guid,
            response,
            f"{message.guid}:connect-ebay",
        )

    def _get_or_create_conversation(
        self,
        session: Session,
        message: InboundMessage,
    ) -> SellerConversation:
        seller = session.exec(select(Seller).where(Seller.handle == message.handle)).first()
        if seller is None:
            seller = Seller(handle=message.handle, tz=self.timezone)
            session.add(seller)
            session.flush()
        conversation = session.exec(
            select(SellerConversation).where(SellerConversation.seller_id == seller.id)
        ).first()
        if conversation is None:
            conversation = SellerConversation(
                seller_id=seller.id,
                handle=message.handle,
                chat_guid=message.chat_guid,
            )
            session.add(conversation)
            session.flush()
        else:
            conversation.chat_guid = message.chat_guid
        conversation.updated_at = self.clock.now()
        session.add(conversation)
        return conversation

    def _get_or_create_item(
        self,
        session: Session,
        conversation: SellerConversation,
        text: str,
    ) -> Item:
        item = (
            session.get(Item, conversation.active_item_id) if conversation.active_item_id else None
        )
        if item is not None and item.status not in TERMINAL_ITEM_STATUSES:
            return item
        now = self.clock.now()
        floor_cents = parse_floor_cents(text)
        deadline_at = parse_deadline(text, now, self.timezone)
        horizon = max((deadline_at - now).total_seconds() / 3600, 1)
        provisional_value = max(int(floor_cents * 1.2), 10_000)
        item = Item(
            seller_id=conversation.seller_id,
            title=parse_title(text),
            category="other",
            condition=ConditionGrade.B,
            confidence=0,
            deadline_at=deadline_at,
            original_horizon_hours=horizon,
            floor_cents=floor_cents,
            floor_source="seller" if floor_cents else "missing",
            constraints_json={
                "source": "imessage",
                "original_caption": text,
                "needs_identification": parse_title(text) == "Item from iMessage",
                "needs_market_data": True,
            },
            market_value_cents=provisional_value,
            sigma_cents=max(int(provisional_value * 0.12), 1),
            status=ItemStatus.DRAFT,
            created_at=now,
        )
        session.add(item)
        session.flush()
        conversation.active_item_id = item.id
        write_decision(
            session,
            item_id=item.id,
            sim_at=now,
            wall_at=self.clock.wall(),
            kind="seller",
            action="intake",
            inputs={"caption": text, "channel": "imessage"},
            reason="created a seller draft from an iMessage photo",
            price_before=None,
            price_after=None,
        )
        return item

    async def _process_photo(self, message: InboundMessage) -> None:
        attachment = next(
            (
                value
                for value in message.attachments
                if (value.mime_type or "").startswith("image/")
                or mimetypes.guess_type(value.filename or "")[0] is not None
            ),
            None,
        )
        if attachment is None:
            await self.adapter.send_text(
                message.chat_guid,
                "Please send a HEIC, JPEG, PNG, or WebP product photo.",
                f"{message.guid}:unsupported",
            )
            return

        with Session(self.engine) as session:
            conversation = self._get_or_create_conversation(session, message)
            item = self._get_or_create_item(session, conversation, message.text)
            conversation.status = ConversationStatus.PROCESSING_PHOTO
            session.add(conversation)
            session.commit()
            item_id = item.id
            conversation_id = conversation.id

        mime_type = attachment.mime_type or mimetypes.guess_type(attachment.filename or "")[0]
        try:
            content = await self.adapter.download_attachment_bytes(attachment.guid)
            if mime_type is None:
                raise PhotoPipelineError("photo media type is missing")
        except Exception:
            await self._fail_photo(message, conversation_id)
            return

        if self.identifier is not None:
            identity = await self.identifier.identify(content, mime_type, message.text)
            with Session(self.engine) as session:
                item = session.get(Item, item_id)
                conversation = session.get(SellerConversation, conversation_id)
                if item is None or conversation is None:
                    raise LookupError("item or conversation was lost")
                self._apply_identity(item, identity)
                item.constraints_json = {
                    **item.constraints_json,
                    "pending_attachment": {"guid": attachment.guid, "mime_type": mime_type},
                }
                conversation.status = ConversationStatus.AWAITING_IDENTITY
                conversation.updated_at = self.clock.now()
                session.add(item)
                session.add(conversation)
                write_decision(
                    session,
                    item_id=item.id,
                    sim_at=self.clock.now(),
                    wall_at=self.clock.wall(),
                    kind="system",
                    action="identify",
                    inputs={
                        "title": identity.title,
                        "confidence": identity.confidence,
                        "candidates": [c.title for c in identity.candidates],
                    },
                    reason="asked the seller to confirm the identified item before listing",
                    price_before=None,
                    price_after=None,
                )
                session.commit()
            await self.adapter.send_text(
                message.chat_guid, identity.question(), f"{message.guid}:identify"
            )
            return

        await self._enhance_or_store(message, item_id, conversation_id, content, mime_type)

    @staticmethod
    def _apply_identity(item: Item, identity: ItemIdentity) -> None:
        caption_title = item.constraints_json.get("original_caption", "")
        if identity.confidence >= 0.6 or parse_title(caption_title) == "Item from iMessage":
            item.title = identity.title[:120]
        item.brand = identity.brand or item.brand
        item.model = identity.model or item.model
        if identity.category != "other" or item.category == "other":
            item.category = identity.category
        if identity.condition_guess in {"A", "B", "C"}:
            item.condition = ConditionGrade(identity.condition_guess)
        item.confidence = identity.confidence
        item.constraints_json = apply_identity(item.constraints_json, identity)

    async def _confirm_identity(self, message: InboundMessage) -> bool:
        """Handle the reply to "is it this?"; returns True when the message was consumed."""
        with Session(self.engine) as session:
            conversation = session.exec(
                select(SellerConversation).where(SellerConversation.handle == message.handle)
            ).first()
            if (
                conversation is None
                or conversation.status != ConversationStatus.AWAITING_IDENTITY
                or conversation.active_item_id is None
            ):
                return False
            item = session.get(Item, conversation.active_item_id)
            if item is None:
                return False
            identity = ItemIdentity.model_validate(item.constraints_json.get("identity") or {})
            kind, title = interpret_confirmation(message.text, identity)
            if kind == "named" and not title:
                await self.adapter.send_text(
                    message.chat_guid,
                    identity.question(),
                    f"{message.guid}:identify-repeat",
                )
                return True
            if kind != "yes" and title:
                item.title = title[:120]
                item.confidence = 1.0
            elif kind == "yes":
                item.confidence = max(item.confidence, 0.95)
            pending = item.constraints_json.get("pending_attachment") or {}
            conversation.status = ConversationStatus.PROCESSING_PHOTO
            conversation.updated_at = self.clock.now()
            session.add(item)
            session.add(conversation)
            write_decision(
                session,
                item_id=item.id,
                sim_at=self.clock.now(),
                wall_at=self.clock.wall(),
                kind="seller",
                action="confirm_identity",
                inputs={"reply": message.text, "title": item.title},
                reason="seller confirmed what the item is",
                price_before=None,
                price_after=None,
            )
            session.commit()
            item_id = item.id
            conversation_id = conversation.id

        try:
            content = await self.adapter.download_attachment_bytes(pending["guid"])
            mime_type = pending.get("mime_type") or "image/jpeg"
        except Exception:
            await self._fail_photo(message, conversation_id)
            return True
        await self._enhance_or_store(message, item_id, conversation_id, content, mime_type)
        return True

    async def _fail_photo(self, message: InboundMessage, conversation_id: str) -> None:
        with Session(self.engine) as session:
            conversation = session.get(SellerConversation, conversation_id)
            if conversation is not None:
                conversation.status = ConversationStatus.READY
                session.add(conversation)
                session.commit()
        await self.adapter.send_text(
            message.chat_guid,
            "I could not process that photo. Try sending it again as a normal photo.",
            f"{message.guid}:failed",
        )

    async def _store_original_only(
        self, message: InboundMessage, item_id: str, conversation_id: str, content: bytes, mime: str
    ) -> None:
        """No image editor configured: keep the original and continue to the listing questions."""
        with Session(self.engine) as session:
            item = session.get(Item, item_id)
            conversation = session.get(SellerConversation, conversation_id)
            if item is None or conversation is None:
                raise LookupError("item or conversation was lost")
            try:
                stored = self.storage.save_original(item.id, content, mime)
            except ValueError:
                session.rollback()
                await self._fail_photo(message, conversation_id)
                return
            original = ProductPhoto(
                item_id=item.id,
                role=PhotoRole.ORIGINAL,
                status=PhotoStatus.ORIGINAL,
                file_path=stored.relative_path,
                mime_type=stored.mime_type,
                sha256=stored.sha256,
            )
            session.add(original)
            item.photo_paths = [*item.photo_paths, stored.relative_path]
            conversation.status = ConversationStatus.AWAITING_DETAILS
            conversation.updated_at = self.clock.now()
            session.add(item)
            session.add(conversation)
            session.commit()
        await self.adapter.send_text(
            message.chat_guid,
            "got the photo. photo cleanup is off right now, so i'll list with your original.",
            f"{message.guid}:original-only",
        )

    async def _enhance_or_store(
        self, message: InboundMessage, item_id: str, conversation_id: str, content: bytes, mime: str
    ) -> None:
        if self.editor is None:
            await self._store_original_only(message, item_id, conversation_id, content, mime)
            return
        await self.adapter.send_text(
            message.chat_guid,
            "Got it. I am preparing a cleaner, truthful listing photo now.",
            f"{message.guid}:processing",
        )
        try:
            result = await enhance_product_photo(
                engine=self.engine,
                item_id=item_id,
                content=content,
                mime_type=mime,
                preset=PhotoPreset.STUDIO,
                editor=self.editor,
                storage=self.storage,
            )
        except Exception:
            with Session(self.engine) as session:
                conversation = session.get(SellerConversation, conversation_id)
                if conversation is not None:
                    conversation.status = ConversationStatus.READY
                    session.add(conversation)
                    session.commit()
            await self.adapter.send_text(
                message.chat_guid,
                "I could not enhance that photo. Try sending it again as a normal photo.",
                f"{message.guid}:failed",
            )
            return

        with Session(self.engine) as session:
            conversation = session.get(SellerConversation, conversation_id)
            if conversation is None:
                raise LookupError("seller conversation was lost")
            conversation.pending_photo_id = result.enhanced.id
            conversation.status = ConversationStatus.AWAITING_PHOTO_REVIEW
            conversation.updated_at = self.clock.now()
            session.add(conversation)
            session.commit()

        await self.adapter.send_text(
            message.chat_guid,
            "Original first, then the enhanced version. Reply APPROVE or REJECT.",
            f"{message.guid}:preview-label",
        )
        await self.adapter.send_image(
            message.chat_guid,
            str(self.storage.resolve(result.original.file_path)),
            f"{message.guid}:original",
        )
        await self.adapter.send_image(
            message.chat_guid,
            str(self.storage.resolve(result.enhanced.file_path)),
            f"{message.guid}:enhanced",
        )

    async def _review_pending(self, message: InboundMessage, *, approved: bool) -> None:
        with Session(self.engine) as session:
            conversation = self._get_or_create_conversation(session, message)
            photo = (
                session.get(ProductPhoto, conversation.pending_photo_id)
                if conversation.pending_photo_id
                else None
            )
            if photo is None or photo.status != PhotoStatus.REVIEW:
                session.commit()
                response = "There is no enhanced photo waiting for review."
            else:
                item = session.get(Item, photo.item_id)
                if item is None or photo.role != PhotoRole.ENHANCED:
                    raise LookupError("pending photo item was lost")
                photo.status = PhotoStatus.APPROVED if approved else PhotoStatus.REJECTED
                photo.reviewed_at = self.clock.now()
                if approved and photo.file_path not in item.photo_paths:
                    item.photo_paths = [*item.photo_paths, photo.file_path]
                    session.add(item)
                conversation.pending_photo_id = None
                conversation.status = ConversationStatus.AWAITING_DETAILS
                session.add(photo)
                session.add(conversation)
                write_decision(
                    session,
                    item_id=item.id,
                    sim_at=self.clock.now(),
                    wall_at=self.clock.wall(),
                    kind="seller",
                    action="approve_photo" if approved else "reject_photo",
                    inputs={"photo_id": photo.id, "channel": "imessage"},
                    reason="seller reviewed the AI-enhanced image in iMessage",
                    price_before=None,
                    price_after=None,
                )
                session.commit()
                response = (
                    "Approved. The original stays in the listing set too."
                    if approved
                    else (
                        "Rejected. I will not use that enhanced image. Send another photo to retry."
                    )
                )
        await self.adapter.send_text(
            message.chat_guid,
            response,
            f"{message.guid}:review-response",
        )

    async def _send_status(self, message: InboundMessage) -> None:
        with Session(self.engine) as session:
            conversation = session.exec(
                select(SellerConversation).where(SellerConversation.handle == message.handle)
            ).first()
            if conversation is None or conversation.active_item_id is None:
                response = "No active item. Send a product photo to start."
            else:
                item = session.get(Item, conversation.active_item_id)
                if item is None:
                    response = "No active item. Send a product photo to start."
                else:
                    response = (
                        f"{item.title}: {item.status.value}. "
                        f"Photo step: {conversation.status.value}."
                    )
        await self.adapter.send_text(
            message.chat_guid,
            response,
            f"{message.guid}:status",
        )
