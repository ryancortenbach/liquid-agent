from __future__ import annotations

import asyncio
import mimetypes
import re
from collections.abc import Awaitable, Callable
from datetime import datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

from dateparser import parse as parse_date
from sqlalchemy import Engine
from sqlmodel import Session, select

from app.channels.base import InboundAttachment, InboundMessage
from app.channels.imessage_bluebubbles import BlueBubblesAdapter
from app.clock import Clock
from app.inbound.identify import (
    YES_WORDS,
    Identifier,
    InventoryDetection,
    ItemIdentity,
    apply_identity,
    crop_inventory_item,
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
from app.photos.reviewer import PhotoTruthReviewer
from app.photos.storage import PhotoStorage

APPROVE_WORDS = {"approve", "approved", "yes", "use it", "looks good"}
REJECT_WORDS = {"reject", "no", "do not use", "don't use it"}
BATCH_PATTERN = re.compile(r"^(?:batch|multiple items?)\b", flags=re.IGNORECASE)
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


def batch_photo_groups(text: str, photo_count: int) -> list[list[int]]:
    """Map attachment indexes to items. `BATCH 2+3` means two angles, then three angles."""
    if not BATCH_PATTERN.match(text.strip()) or photo_count < 2:
        return [list(range(photo_count))]
    match = re.match(r"^(?:batch|multiple items?)\s+(\d+(?:\s*\+\s*\d+)+)\b", text.strip(), re.I)
    if match:
        counts = [int(value) for value in re.split(r"\s*\+\s*", match.group(1))]
        if all(value > 0 for value in counts) and sum(counts) == photo_count:
            groups: list[list[int]] = []
            offset = 0
            for count in counts:
                groups.append(list(range(offset, offset + count)))
                offset += count
            return groups
    return [[index] for index in range(photo_count)]


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
        reviewer: PhotoTruthReviewer | None = None,
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
        self.reviewer = reviewer

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
                "Send one or more product photos with a message like: Sony WH-1000XM5 "
                "headphones, sell by Sunday 6pm, do not go under $170. Start with BATCH for "
                "multiple items. You can also reply STATUS."
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
        *,
        force_new: bool = False,
    ) -> Item:
        item = (
            session.get(Item, conversation.active_item_id)
            if conversation.active_item_id and not force_new
            else None
        )
        if (
            item is not None
            and item.status not in TERMINAL_ITEM_STATUSES
            and conversation.status != ConversationStatus.LISTED
        ):
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
        attachments = [
            value
            for value in message.attachments
            if (value.mime_type or "").startswith("image/")
            or (mimetypes.guess_type(value.filename or "")[0] or "").startswith("image/")
        ]
        if not attachments:
            await self.adapter.send_text(
                message.chat_guid,
                "Please send a HEIC, JPEG, PNG, or WebP product photo.",
                f"{message.guid}:unsupported",
            )
            return

        detector = getattr(self.identifier, "detect_all", None)
        if (
            len(attachments) == 1
            and not BATCH_PATTERN.match(message.text.strip())
            and callable(detector)
        ):
            await self._process_inventory_photo(message, attachments[0], detector)
            return

        groups = batch_photo_groups(message.text, len(attachments))
        is_batch = len(groups) > 1
        with Session(self.engine) as session:
            conversation = self._get_or_create_conversation(session, message)
            items = [
                self._get_or_create_item(
                    session,
                    conversation,
                    message.text,
                    force_new=is_batch or index > 0,
                )
                for index in range(len(groups))
            ]
            item_ids = [item.id for item in items]
            if is_batch:
                for index, item in enumerate(items):
                    item.constraints_json = {
                        **item.constraints_json,
                        "batch_item_ids": item_ids,
                        "batch_index": index,
                    }
                    session.add(item)
                conversation.active_item_id = item_ids[0]
            conversation.status = ConversationStatus.PROCESSING_PHOTO
            session.add(conversation)
            session.commit()
            conversation_id = conversation.id

        try:
            downloaded = await asyncio.gather(
                *(self.adapter.download_attachment_bytes(value.guid) for value in attachments)
            )
            media = []
            for attachment, content in zip(attachments, downloaded, strict=True):
                mime_type = attachment.mime_type or mimetypes.guess_type(
                    attachment.filename or ""
                )[0]
                if mime_type is None:
                    raise PhotoPipelineError("photo media type is missing")
                media.append((attachment, content, mime_type))
        except Exception:
            await self._fail_photo(message, conversation_id)
            return

        if self.identifier is not None:
            identity_inputs = [media[indexes[0]] for indexes in groups]
            identities = await asyncio.gather(
                *(
                    self.identifier.identify(content, mime_type, message.text)
                    for _, content, mime_type in identity_inputs
                )
            )
            with Session(self.engine) as session:
                conversation = session.get(SellerConversation, conversation_id)
                if conversation is None:
                    raise LookupError("item or conversation was lost")
                for index, item_id in enumerate(item_ids):
                    item = session.get(Item, item_id)
                    if item is None:
                        raise LookupError("item was lost")
                    identity = identities[index]
                    self._apply_identity(item, identity)
                    item_media = [media[media_index] for media_index in groups[index]]
                    item.constraints_json = {
                        **item.constraints_json,
                        "pending_attachments": [
                            {"guid": value.guid, "mime_type": mime_type}
                            for value, _, mime_type in item_media
                        ],
                    }
                    session.add(item)
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
                            "candidates": [candidate.title for candidate in identity.candidates],
                            "photo_count": len(item_media),
                            "batch_size": len(item_ids),
                        },
                        reason="asked the seller to confirm identified batch items before listing",
                        price_before=None,
                        price_after=None,
                    )
                conversation.status = ConversationStatus.AWAITING_IDENTITY
                conversation.updated_at = self.clock.now()
                session.add(conversation)
                session.commit()
            if is_batch:
                summary = "\n".join(
                    f"{index}. {identity.title} ({len(groups[index - 1])} photos)"
                    for index, identity in enumerate(identities, start=1)
                )
                question = (
                    f"I found {len(identities)} items:\n{summary}\n"
                    "Reply YES if all are right, or say something like '2 is Bose QC45'."
                )
            else:
                question = identities[0].question()
                if len(media) > 1:
                    question += f"\nI will use all {len(media)} photos as angles of this item."
            await self.adapter.send_text(message.chat_guid, question, f"{message.guid}:identify")
            return

        jobs = [
            (item_ids[item_index], media[media_index][1], media[media_index][2])
            for item_index, indexes in enumerate(groups)
            for media_index in indexes
        ]
        await self._enhance_or_store_many(message, conversation_id, jobs)

    async def _process_inventory_photo(
        self,
        message: InboundMessage,
        attachment: InboundAttachment,
        detector: Callable[[bytes, str, str], Awaitable[InventoryDetection]],
    ) -> None:
        """Split one scene into separately tracked items before any image editing."""
        with Session(self.engine) as session:
            conversation = self._get_or_create_conversation(session, message)
            first = self._get_or_create_item(session, conversation, message.text)
            conversation.status = ConversationStatus.PROCESSING_PHOTO
            session.add(conversation)
            session.commit()
            conversation_id = conversation.id
            first_item_id = first.id

        mime_type = attachment.mime_type or mimetypes.guess_type(attachment.filename or "")[0]
        try:
            if mime_type is None:
                raise PhotoPipelineError("photo media type is missing")
            content = await self.adapter.download_attachment_bytes(attachment.guid)
            detection = await detector(content, mime_type, message.text)
            identities = list(detection.items)
            if not identities:
                raise PhotoPipelineError("no sellable items were detected")
        except Exception:
            await self._fail_photo(message, conversation_id)
            return

        with Session(self.engine) as session:
            conversation = session.get(SellerConversation, conversation_id)
            first = session.get(Item, first_item_id)
            if conversation is None or first is None:
                raise LookupError("item or conversation was lost")
            items = [first]
            for _ in identities[1:]:
                items.append(
                    self._get_or_create_item(
                        session,
                        conversation,
                        message.text,
                        force_new=True,
                    )
                )
            item_ids = [item.id for item in items]
            source_path = None
            if len(items) > 1:
                source_path = self.storage.save_original(
                    f"_inventory_sources/{message.guid}", content, mime_type
                ).relative_path
            for index, (item, identity) in enumerate(zip(items, identities, strict=True)):
                self._apply_identity(item, identity)
                if len(items) > 1:
                    crop = crop_inventory_item(content, identity.box_2d)
                    pending = self.storage.save_original(
                        f"_pending/{item.id}", crop, "image/jpeg"
                    )
                    pending_attachments = [
                        {"file_path": pending.relative_path, "mime_type": "image/jpeg"}
                    ]
                else:
                    pending_attachments = [{"guid": attachment.guid, "mime_type": mime_type}]
                item.constraints_json = {
                    **item.constraints_json,
                    "pending_attachments": pending_attachments,
                    "batch_item_ids": item_ids if len(items) > 1 else [],
                    "batch_index": index,
                    "inventory_source_path": source_path,
                    "inventory_box_2d": identity.box_2d,
                }
                session.add(item)
                write_decision(
                    session,
                    item_id=item.id,
                    sim_at=self.clock.now(),
                    wall_at=self.clock.wall(),
                    kind="system",
                    action="inventory_detect",
                    inputs={
                        "title": identity.title,
                        "confidence": identity.confidence,
                        "box_2d": identity.box_2d,
                        "inventory_size": len(items),
                    },
                    reason="detected a distinct sellable object in the seller's inventory photo",
                    price_before=None,
                    price_after=None,
                )
            conversation.active_item_id = item_ids[0]
            conversation.status = ConversationStatus.AWAITING_IDENTITY
            conversation.updated_at = self.clock.now()
            session.add(conversation)
            session.commit()

        if len(identities) == 1:
            question = identities[0].question()
        else:
            summary = "\n".join(
                f"{index}. {identity.title}"
                for index, identity in enumerate(identities, start=1)
            )
            question = (
                f"I found {len(identities)} sellable items in that photo:\n{summary}\n"
                "Reply YES if that is everything. You can say 'REMOVE 3' or "
                "'2 is Bose QC45'. If I missed something, send a closer photo of it."
            )
        await self.adapter.send_text(message.chat_guid, question, f"{message.guid}:inventory")

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

    async def _load_pending_attachment(self, pending: dict) -> bytes:
        if pending.get("file_path"):
            path = self.storage.resolve(pending["file_path"])
            return await asyncio.to_thread(path.read_bytes)
        return await self.adapter.download_attachment_bytes(pending["guid"])

    async def _confirm_identity(self, message: InboundMessage) -> bool:
        """Handle the reply to "is it this?"; returns True when the message was consumed."""
        repeat_text: str | None = None
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
            item_ids = list(item.constraints_json.get("batch_item_ids") or [item.id])
            items = [session.get(Item, item_id) for item_id in item_ids]
            if any(value is None for value in items):
                raise LookupError("batch item was lost")
            batch_items = [value for value in items if value is not None]
            lowered = message.text.strip().lower().rstrip(".! ")

            if len(batch_items) > 1 and lowered not in YES_WORDS:
                removal = re.match(r"^(?:remove|skip)\s+([\d,\s]+)$", lowered)
                correction = re.match(r"^(\d+)\s+(?:is|=)\s+(.+)$", message.text.strip())
                if removal:
                    indexes = {
                        int(value)
                        for value in re.findall(r"\d+", removal.group(1))
                        if 1 <= int(value) <= len(batch_items)
                    }
                    remaining = [
                        value
                        for index, value in enumerate(batch_items, start=1)
                        if index not in indexes
                    ]
                    for index in indexes:
                        removed = batch_items[index - 1]
                        removed.status = ItemStatus.CANCELLED
                        for pending in removed.constraints_json.get("pending_attachments") or []:
                            if pending.get("file_path"):
                                self.storage.resolve(pending["file_path"]).unlink(missing_ok=True)
                        session.add(removed)
                    remaining_ids = [value.id for value in remaining]
                    for index, value in enumerate(remaining):
                        value.constraints_json = {
                            **value.constraints_json,
                            "batch_item_ids": remaining_ids,
                            "batch_index": index,
                        }
                        session.add(value)
                    if remaining:
                        conversation.active_item_id = remaining[0].id
                        batch_items = remaining
                        summary = "\n".join(
                            f"{index}. {value.title}"
                            for index, value in enumerate(remaining, start=1)
                        )
                        repeat_text = f"Removed.\n{summary}\nReply YES if that is everything."
                    else:
                        conversation.active_item_id = None
                        conversation.status = ConversationStatus.READY
                        batch_items = []
                        repeat_text = (
                            "Removed every item. Send another photo whenever you are ready."
                        )
                elif correction and 1 <= int(correction.group(1)) <= len(batch_items):
                    corrected = batch_items[int(correction.group(1)) - 1]
                    corrected.title = correction.group(2).strip()[:120]
                    corrected.confidence = 1.0
                    session.add(corrected)
                    session.commit()
                    summary = "\n".join(
                        f"{index}. {value.title}"
                        for index, value in enumerate(batch_items, start=1)
                    )
                    repeat_text = f"Updated.\n{summary}\nReply YES if all are right."
                else:
                    repeat_text = (
                        "Reply YES if every item is right, or correct one like "
                        "'2 is Bose QC45'."
                    )
            elif len(batch_items) == 1:
                identity = ItemIdentity.model_validate(item.constraints_json.get("identity") or {})
                kind, title = interpret_confirmation(message.text, identity)
                if kind == "named" and not title:
                    repeat_text = identity.question()
                elif kind != "yes" and title:
                    item.title = title[:120]
                    item.confidence = 1.0
                elif kind == "yes":
                    item.confidence = max(item.confidence, 0.95)

            if repeat_text is not None:
                session.add(item)
                session.commit()
            else:
                for value in batch_items:
                    value.confidence = max(value.confidence, 0.95)
                    session.add(value)
            conversation.status = (
                ConversationStatus.READY
                if repeat_text is not None and not batch_items
                else (
                    ConversationStatus.AWAITING_IDENTITY
                    if repeat_text is not None
                    else ConversationStatus.PROCESSING_PHOTO
                )
            )
            conversation.updated_at = self.clock.now()
            session.add(conversation)
            pending_by_item: list[tuple[str, list[dict]]] = []
            for value in batch_items:
                pending = list(value.constraints_json.get("pending_attachments") or [])
                legacy = value.constraints_json.get("pending_attachment")
                if not pending and legacy:
                    pending = [legacy]
                pending_by_item.append((value.id, pending))
                if repeat_text is None:
                    write_decision(
                        session,
                        item_id=value.id,
                        sim_at=self.clock.now(),
                        wall_at=self.clock.wall(),
                        kind="seller",
                        action="confirm_identity",
                        inputs={"reply": message.text, "title": value.title},
                        reason="seller confirmed what the item is",
                        price_before=None,
                        price_after=None,
                    )
            session.commit()
            conversation_id = conversation.id

        if repeat_text is not None:
            await self.adapter.send_text(
                message.chat_guid,
                repeat_text,
                f"{message.guid}:identify-repeat",
            )
            return True

        try:
            flattened = [
                (item_id, pending)
                for item_id, values in pending_by_item
                for pending in values
            ]
            contents = await asyncio.gather(
                *(self._load_pending_attachment(value) for _, value in flattened)
            )
            jobs = [
                (item_id, content, pending.get("mime_type") or "image/jpeg")
                for (item_id, pending), content in zip(flattened, contents, strict=True)
            ]
        except Exception:
            await self._fail_photo(message, conversation_id)
            return True
        try:
            await self._enhance_or_store_many(message, conversation_id, jobs)
        finally:
            for _, pending in flattened:
                if pending.get("file_path"):
                    self.storage.resolve(pending["file_path"]).unlink(missing_ok=True)
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

    async def _store_originals_only(
        self,
        message: InboundMessage,
        conversation_id: str,
        jobs: list[tuple[str, bytes, str]],
    ) -> None:
        """No editor configured: keep every original and continue to listing questions."""
        with Session(self.engine) as session:
            conversation = session.get(SellerConversation, conversation_id)
            if conversation is None:
                raise LookupError("conversation was lost")
            for item_id, content, mime in jobs:
                item = session.get(Item, item_id)
                if item is None:
                    raise LookupError("item was lost")
                try:
                    stored = self.storage.save_original(item.id, content, mime)
                except ValueError:
                    session.rollback()
                    await self._fail_photo(message, conversation_id)
                    return
                session.add(
                    ProductPhoto(
                        item_id=item.id,
                        role=PhotoRole.ORIGINAL,
                        status=PhotoStatus.ORIGINAL,
                        file_path=stored.relative_path,
                        mime_type=stored.mime_type,
                        sha256=stored.sha256,
                    )
                )
                item.photo_paths = [*item.photo_paths, stored.relative_path]
                session.add(item)
            conversation.status = ConversationStatus.AWAITING_DETAILS
            conversation.updated_at = self.clock.now()
            session.add(conversation)
            session.commit()
        await self.adapter.send_text(
            message.chat_guid,
            (
                "got the photo. photo cleanup is off right now, so i'll list with your original."
                if len(jobs) == 1
                else f"got {len(jobs)} photos. photo cleanup is off, so I kept every original."
            ),
            f"{message.guid}:original-only",
        )

    async def _enhance_or_store_many(
        self,
        message: InboundMessage,
        conversation_id: str,
        jobs: list[tuple[str, bytes, str]],
    ) -> None:
        if self.editor is None:
            await self._store_originals_only(message, conversation_id, jobs)
            return
        await self.adapter.send_text(
            message.chat_guid,
            f"Got {len(jobs)} photos. I am preparing truthful listing versions now.",
            f"{message.guid}:processing",
        )
        results = []
        failed = 0
        for item_id, content, mime in jobs:
            try:
                results.append(
                    await enhance_product_photo(
                        engine=self.engine,
                        item_id=item_id,
                        content=content,
                        mime_type=mime,
                        preset=PhotoPreset.STUDIO,
                        editor=self.editor,
                        storage=self.storage,
                        reviewer=self.reviewer,
                    )
                )
            except Exception:
                failed += 1
        if not results:
            with Session(self.engine) as session:
                conversation = session.get(SellerConversation, conversation_id)
                if conversation is not None:
                    conversation.status = ConversationStatus.READY
                    session.add(conversation)
                    session.commit()
            await self.adapter.send_text(
                message.chat_guid,
                "I could not enhance those photos. Try sending them again as normal photos.",
                f"{message.guid}:failed",
            )
            return

        with Session(self.engine) as session:
            conversation = session.get(SellerConversation, conversation_id)
            anchor = (
                session.get(Item, conversation.active_item_id)
                if conversation is not None and conversation.active_item_id
                else None
            )
            if conversation is None or anchor is None:
                raise LookupError("seller conversation was lost")
            pending_ids = [result.enhanced.id for result in results]
            anchor.constraints_json = {
                **anchor.constraints_json,
                "pending_photo_ids": pending_ids,
            }
            conversation.pending_photo_id = pending_ids[0]
            conversation.status = ConversationStatus.AWAITING_PHOTO_REVIEW
            conversation.updated_at = self.clock.now()
            session.add(anchor)
            session.add(conversation)
            session.commit()

        for index, result in enumerate(results, start=1):
            await self.adapter.send_text(
                message.chat_guid,
                f"Photo {index}: original, then enhanced.",
                f"{message.guid}:pair-{index}",
            )
            await self.adapter.send_image(
                message.chat_guid,
                str(self.storage.resolve(result.original.file_path)),
                f"{message.guid}:original-{index}",
            )
            await self.adapter.send_image(
                message.chat_guid,
                str(self.storage.resolve(result.enhanced.file_path)),
                f"{message.guid}:enhanced-{index}",
            )
        failed_note = f" {failed} could not be processed." if failed else ""
        await self.adapter.send_text(
            message.chat_guid,
            (
                "Original first, then the enhanced version. Reply APPROVE or REJECT."
                if len(results) == 1 and not failed
                else (
                    f"Those are {len(results)} original and enhanced pairs.{failed_note} "
                    "Reply APPROVE or REJECT for all enhanced photos."
                )
            ),
            f"{message.guid}:preview-label",
        )

    async def _review_pending(self, message: InboundMessage, *, approved: bool) -> None:
        with Session(self.engine) as session:
            conversation = self._get_or_create_conversation(session, message)
            anchor = (
                session.get(Item, conversation.active_item_id)
                if conversation.active_item_id
                else None
            )
            pending_ids = list(
                (anchor.constraints_json.get("pending_photo_ids") if anchor else None)
                or ([conversation.pending_photo_id] if conversation.pending_photo_id else [])
            )
            photos = [session.get(ProductPhoto, photo_id) for photo_id in pending_ids]
            review_photos = [
                photo
                for photo in photos
                if photo is not None and photo.status == PhotoStatus.REVIEW
            ]
            if not review_photos:
                session.commit()
                response = "There is no enhanced photo waiting for review."
            else:
                item_ids: set[str] = set()
                for photo in review_photos:
                    item = session.get(Item, photo.item_id)
                    if item is None or photo.role != PhotoRole.ENHANCED:
                        raise LookupError("pending photo item was lost")
                    item_ids.add(item.id)
                    photo.status = PhotoStatus.APPROVED if approved else PhotoStatus.REJECTED
                    photo.reviewed_at = self.clock.now()
                    if approved and photo.file_path not in item.photo_paths:
                        item.photo_paths = [*item.photo_paths, photo.file_path]
                        session.add(item)
                    session.add(photo)
                    write_decision(
                        session,
                        item_id=item.id,
                        sim_at=self.clock.now(),
                        wall_at=self.clock.wall(),
                        kind="seller",
                        action="approve_photo" if approved else "reject_photo",
                        inputs={"photo_id": photo.id, "channel": "imessage"},
                        reason="seller reviewed an AI-enhanced image in iMessage",
                        price_before=None,
                        price_after=None,
                    )
                if anchor is not None:
                    anchor.constraints_json = {
                        **anchor.constraints_json,
                        "pending_photo_ids": [],
                    }
                    session.add(anchor)
                conversation.pending_photo_id = None
                conversation.status = ConversationStatus.AWAITING_DETAILS
                session.add(conversation)
                session.commit()
                response = (
                    (
                        f"Approved {len(review_photos)} enhanced photos across "
                        f"{len(item_ids)} items. Every original stays in its listing set."
                    )
                    if approved
                    else f"Rejected {len(review_photos)} enhanced photos. I kept every original."
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
