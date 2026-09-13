from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from sqlalchemy import Engine
from sqlmodel import Session, select

from app.channels.base import ChannelAdapter, InboundMessage
from app.clock import Clock
from app.config import Settings
from app.intake.details import (
    QUESTION_SETS,
    IntakeDetails,
    apply_defaults,
    merge_details,
    next_question_set,
)
from app.ledger import write_decision
from app.listing.draft import CONDITION_LABEL, ListingDraft, build_listing_draft
from app.listing.handoff import build_handoffs, dollars
from app.listing.pack import replace_draft_packs
from app.market.ebay import EbayPublisher
from app.market.publish_service import EbayPublishError, publish_item_to_ebay, sandbox_listing_url
from app.models import (
    ConversationStatus,
    Item,
    ItemStatus,
    ListingPack,
    ListingPackStatus,
    PhotoStatus,
    ProductPhoto,
    ResearchResult,
    SellerConversation,
)
from app.pricing.schedule import PriceSchedule, describe_schedule, plan_item_price
from app.research.comps import research_item
from app.research.sources import CompsSource

log = logging.getLogger(__name__)

GO_WORDS = {
    "go", "publish", "list it", "post it", "do it", "go ahead", "ok go", "yes go", "ship it",
}
CANCEL_WORDS = {"cancel", "stop", "never mind", "nevermind"}
FLOW_STATES = {
    ConversationStatus.AWAITING_DETAILS,
    ConversationStatus.RESEARCHING,
    ConversationStatus.AWAITING_CONFIRMATION,
    ConversationStatus.PUBLISHING,
    ConversationStatus.LISTED,
}


@dataclass(frozen=True, slots=True)
class PlanResult:
    item_id: str
    card_text: str
    schedule: dict[str, Any]
    draft: dict[str, Any]
    research: dict[str, Any] | None
    packs: list[dict[str, Any]] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "item_id": self.item_id,
            "card_text": self.card_text,
            "schedule": self.schedule,
            "draft": self.draft,
            "research": self.research,
            "packs": self.packs,
        }


def pack_dict(pack: ListingPack) -> dict[str, Any]:
    return {
        "id": pack.id,
        "channel": pack.channel,
        "title": pack.title,
        "price_cents": pack.price_cents,
        "status": pack.status.value,
        "external_id": pack.external_id,
        "external_url": pack.external_url,
        "handoff_path": pack.handoff_path,
        "failure_reason": pack.failure_reason,
    }


class ListingFlow:
    """Everything after the seller approves the photo: details, research, plan, card, publish."""

    def __init__(
        self,
        *,
        engine: Engine,
        clock: Clock,
        settings: Settings,
        comps_sources: list[CompsSource],
        adapter: ChannelAdapter | None = None,
        ebay_publisher: EbayPublisher | None = None,
        polish: Callable[[ListingDraft], ListingDraft] | None = None,
    ) -> None:
        self.engine = engine
        self.clock = clock
        self.settings = settings
        self.comps_sources = comps_sources
        self.adapter = adapter
        self.ebay_publisher = ebay_publisher
        self.polish = polish

    # ---------- storage helpers ----------
    def _load(self, session: Session, handle: str) -> tuple[SellerConversation | None, Item | None]:
        conversation = session.exec(
            select(SellerConversation).where(SellerConversation.handle == handle)
        ).first()
        if conversation is None or conversation.active_item_id is None:
            return conversation, None
        return conversation, session.get(Item, conversation.active_item_id)

    @staticmethod
    def _details(item: Item) -> IntakeDetails:
        return IntakeDetails.from_dict(item.constraints_json.get("intake"))

    @staticmethod
    def _save_details(item: Item, details: IntakeDetails, asked: list[str]) -> None:
        item.constraints_json = {
            **item.constraints_json,
            "intake": details.as_dict(),
            "intake_asked": asked,
        }

    async def _send(self, chat_guid: str | None, text: str, key: str) -> None:
        if self.adapter is not None and chat_guid:
            await self.adapter.send_text(chat_guid, text, key)

    # ---------- conversation ----------
    async def start_details(self, *, handle: str, chat_guid: str, key: str) -> bool:
        """Ask the first question set once the photo step has handed the item over."""
        with Session(self.engine) as session:
            conversation, item = self._load(session, handle)
            if (
                conversation is None
                or item is None
                or conversation.status != ConversationStatus.AWAITING_DETAILS
                or item.constraints_json.get("intake_asked")
            ):
                return False
            self._save_details(item, self._details(item), ["condition"])
            session.add(item)
            session.commit()
        await self._send(chat_guid, QUESTION_SETS["condition"], f"{key}:q-condition")
        return True

    async def handle(self, message: InboundMessage) -> bool:
        """Return True when this flow owned the message."""
        with Session(self.engine) as session:
            conversation, item = self._load(session, message.handle)
            if conversation is None or item is None or conversation.status not in FLOW_STATES:
                return False
            status = conversation.status
            item_id = item.id
            asked = list(item.constraints_json.get("intake_asked") or [])
            details = self._details(item)
        text = message.text.strip()
        lowered = text.lower()
        chat_guid = message.chat_guid
        key = message.guid

        if status == ConversationStatus.AWAITING_DETAILS:
            if not asked:
                return await self.start_details(handle=message.handle, chat_guid=chat_guid, key=key)
            details = merge_details(details, text, answered_set=asked[-1])
            following = next_question_set(details)
            with Session(self.engine) as session:
                item = session.get(Item, item_id)
                conversation = session.exec(
                    select(SellerConversation).where(SellerConversation.handle == message.handle)
                ).one()
                if following:
                    asked.append(following)
                else:
                    apply_defaults(details)
                    conversation.status = ConversationStatus.RESEARCHING
                assert item is not None
                self._save_details(item, details, asked)
                session.add(item)
                session.add(conversation)
                session.commit()
            if following:
                await self._send(chat_guid, QUESTION_SETS[following], f"{key}:q-{following}")
                return True
            await self._send(
                chat_guid,
                f"on it. pulling sold and active listings and pricing it for {details.horizon}.",
                f"{key}:researching",
            )
            await self.plan(item_id, research=True, chat_guid=chat_guid, key=key)
            return True

        if status == ConversationStatus.RESEARCHING:
            await self._send(chat_guid, "still building the plan, one moment.", f"{key}:wait")
            return True

        if status == ConversationStatus.AWAITING_CONFIRMATION:
            if lowered in GO_WORDS:
                await self.publish(item_id, chat_guid=chat_guid, key=key)
                return True
            if lowered in CANCEL_WORDS:
                with Session(self.engine) as session:
                    conversation = session.exec(
                        select(SellerConversation).where(
                            SellerConversation.handle == message.handle
                        )
                    ).one()
                    item = session.get(Item, item_id)
                    conversation.status = ConversationStatus.READY
                    if item is not None:
                        item.status = ItemStatus.CANCELLED
                        session.add(item)
                    session.add(conversation)
                    session.commit()
                await self._send(
                    chat_guid,
                    "cancelled. send a photo whenever you want to list something.",
                    f"{key}:cancelled",
                )
                return True
            updated = merge_details(details, text, answered_set="change")
            if updated.as_dict() == {**details.as_dict(), "answered_sets": updated.answered_sets}:
                await self._send(
                    chat_guid,
                    "reply go to publish, or tell me what to change: a floor like 'floor 250', "
                    "a speed like '1 day', or where to list like 'ebay only'.",
                    f"{key}:hint",
                )
                return True
            with Session(self.engine) as session:
                item = session.get(Item, item_id)
                assert item is not None
                self._save_details(item, apply_defaults(updated), asked)
                session.add(item)
                session.commit()
            await self._send(chat_guid, "updating the plan.", f"{key}:updating")
            await self.plan(item_id, research=False, chat_guid=chat_guid, key=key)
            return True

        if status == ConversationStatus.PUBLISHING:
            await self._send(chat_guid, "publishing now, one moment.", f"{key}:publishing")
            return True

        if status == ConversationStatus.LISTED:
            if lowered == "status":
                return False
            with Session(self.engine) as session:
                packs = session.exec(
                    select(ListingPack).where(ListingPack.item_id == item_id)
                ).all()
            await self._send(chat_guid, self.listed_summary(packs), f"{key}:listed")
            return True
        return False

    # ---------- planning ----------
    async def plan(
        self, item_id: str, *, research: bool, chat_guid: str | None = None, key: str = "api"
    ) -> PlanResult:
        now = self.clock.now()
        wall = self.clock.wall()
        if research and self.comps_sources:
            await research_item(
                engine=self.engine,
                item_id=item_id,
                sources=self.comps_sources,
                now=now,
                wall_at=wall,
            )
        with Session(self.engine) as session:
            item = session.get(Item, item_id)
            if item is None:
                raise LookupError("item not found")
            details = apply_defaults(self._details(item))
            if details.floor_cents:
                item.floor_cents = details.floor_cents
                item.floor_source = "seller"
            elif not (item.floor_source == "seller" and item.floor_cents > 0):
                item.floor_source = "missing"
            item.condition = details.condition_grade
            self._save_details(item, details, list(item.constraints_json.get("intake_asked") or []))
            session.add(item)
            session.commit()
        schedule = plan_item_price(
            engine=self.engine,
            item_id=item_id,
            horizon=details.horizon or "week",
            platforms=details.platforms or ["ebay"],
            now=now,
            wall_at=wall,
        )
        with Session(self.engine) as session:
            item = session.get(Item, item_id)
            assert item is not None
            research_row = session.exec(
                select(ResearchResult)
                .where(ResearchResult.item_id == item_id)
                .order_by(ResearchResult.created_at.desc())  # type: ignore[attr-defined]
            ).first()
            specifics = research_row.specifics_json if research_row else {}
            sources = research_row.sources_json if research_row else []
            draft = build_listing_draft(item, details, specifics)
            if self.polish is not None:
                draft = self.polish(draft)
            photos = session.exec(
                select(ProductPhoto)
                .where(ProductPhoto.item_id == item_id)
                .order_by(ProductPhoto.created_at)
            ).all()
            photo_ids = [
                photo.id
                for photo in photos
                if photo.status in {PhotoStatus.APPROVED, PhotoStatus.ORIGINAL}
            ]
            packs = replace_draft_packs(
                session,
                item=item,
                draft=draft,
                schedule=schedule,
                platforms=details.platforms or ["ebay"],
                photo_ids=photo_ids,
                sources=sources,
            )
            conversation = session.exec(
                select(SellerConversation).where(SellerConversation.seller_id == item.seller_id)
            ).first()
            if conversation is not None:
                conversation.status = ConversationStatus.AWAITING_CONFIRMATION
                conversation.updated_at = now
                session.add(conversation)
            card = self.card_text(item, details, research_row, schedule, draft)
            write_decision(
                session,
                item_id=item.id,
                sim_at=now,
                wall_at=wall,
                kind="system",
                action="listing_plan",
                inputs={
                    "card": card,
                    "platforms": details.platforms,
                    "list_price_cents": schedule.list_price_cents,
                    "floor_cents": schedule.floor_cents,
                    "sources": sources,
                },
                reason="listing pack drafted from research, price plan, and seller details",
                price_before=None,
                price_after=schedule.list_price_cents,
            )
            session.commit()
            result = PlanResult(
                item_id=item_id,
                card_text=card,
                schedule=schedule.as_dict(),
                draft=draft.as_dict(),
                research=(
                    {
                        "query": research_row.query,
                        "sold_n": research_row.sold_n,
                        "active_n": research_row.active_n,
                        "sold_median_cents": research_row.sold_median_cents,
                        "active_median_cents": research_row.active_median_cents,
                        "basis": research_row.basis,
                        "sources": research_row.sources_json,
                    }
                    if research_row
                    else None
                ),
                packs=[pack_dict(pack) for pack in packs],
            )
        await self._send(chat_guid, result.card_text, f"{key}:card")
        return result

    @staticmethod
    def card_text(
        item: Item,
        details: IntakeDetails,
        research: ResearchResult | None,
        schedule: PriceSchedule,
        draft: ListingDraft,
    ) -> str:
        lines = [
            "here's the plan",
            draft.title,
            f"condition: {CONDITION_LABEL.get(details.condition or 'B', 'good')}",
            f"price: {describe_schedule(schedule)}",
            f"listing on: {', '.join(details.platforms or ['ebay'])}",
        ]
        if research is not None:
            basis = ""
            if research.basis == "provisional":
                basis = " (no matching listings found, so this is an estimate)"
            elif research.sources_json and research.sources_json[0].get("source") == "fixture":
                basis = " (offline sample data, not live listings)"
            sold = (
                f"{research.sold_n} sold (median {dollars(research.sold_median_cents)})"
                if research.sold_median_cents
                else "0 sold"
            )
            active = (
                f"{research.active_n} active (median {dollars(research.active_median_cents)})"
                if research.active_median_cents
                else "0 active"
            )
            lines.append(f"based on {sold} and {active} listings{basis}")
            urls = [source["url"] for source in research.sources_json if source.get("url")][:3]
            if urls:
                lines.append("sources: " + " ".join(urls))
        if schedule.instant_cents:
            lines.append(f"guaranteed-now reference: about {dollars(schedule.instant_cents)}")
        lines.append("reply go to publish, or tell me what to change (floor 250, 1 day, ebay only)")
        return "\n".join(lines)

    # ---------- publishing ----------
    async def publish(
        self, item_id: str, *, chat_guid: str | None = None, key: str = "api"
    ) -> dict[str, Any]:
        now = self.clock.now()
        with Session(self.engine) as session:
            item = session.get(Item, item_id)
            if item is None:
                raise LookupError("item not found")
            details = apply_defaults(self._details(item))
            packs = session.exec(
                select(ListingPack).where(
                    ListingPack.item_id == item_id, ListingPack.status == ListingPackStatus.DRAFT
                )
            ).all()
            conversation = session.exec(
                select(SellerConversation).where(SellerConversation.seller_id == item.seller_id)
            ).first()
            if conversation is not None:
                conversation.status = ConversationStatus.PUBLISHING
                session.add(conversation)
            photos = session.exec(
                select(ProductPhoto).where(
                    ProductPhoto.item_id == item_id, ProductPhoto.status == PhotoStatus.APPROVED
                )
            ).all()
            base = self.settings.public_base_url.rstrip("/")
            image_urls = [f"{base}/api/photos/{photo.id}/file" for photo in photos]
            pack_ids = [pack.id for pack in packs]
            session.commit()

        outcomes: dict[str, dict[str, Any]] = {}
        messages: list[str] = []
        ebay_live = False
        for pack_id in pack_ids:
            with Session(self.engine) as session:
                pack = session.get(ListingPack, pack_id)
                assert pack is not None
                channel = pack.channel
                draft = ListingDraft(
                    title=pack.title,
                    description=pack.description,
                    condition=pack.condition,
                    aspects={k: [v] for k, v in pack.specifics_json.items()},
                )
                price = pack.price_cents
            if channel == "ebay":
                try:
                    result = await publish_item_to_ebay(
                        engine=self.engine,
                        settings=self.settings,
                        publisher=self.ebay_publisher,
                        clock=self.clock,
                        item_id=item_id,
                        seller_approved=True,
                        price_cents=price,
                        title=draft.title,
                        description=draft.description,
                        aspects=draft.aspects,
                    )
                    listing_url = (
                        sandbox_listing_url(result.listing_id) if result.listing_id else None
                    )
                    with Session(self.engine) as session:
                        pack = session.get(ListingPack, pack_id)
                        assert pack is not None
                        pack.status = ListingPackStatus.PUBLISHED
                        pack.external_id = result.listing_id
                        pack.external_offer_id = result.offer_id
                        pack.external_url = listing_url
                        pack.published_at = now
                        session.add(pack)
                        session.commit()
                    ebay_live = True
                    outcomes["ebay"] = {"status": "live", "listing_id": result.listing_id}
                    messages.append(f"listed on ebay (sandbox): {listing_url}")
                except EbayPublishError as exc:
                    with Session(self.engine) as session:
                        pack = session.get(ListingPack, pack_id)
                        assert pack is not None
                        pack.status = ListingPackStatus.FAILED
                        pack.failure_reason = exc.detail
                        session.add(pack)
                        session.commit()
                    outcomes["ebay"] = {"status": "failed", "reason": exc.detail}
                    messages.append(
                        f"ebay: {exc.detail}. the listing pack is saved and will publish once "
                        "the sandbox is configured."
                    )
                continue
            handoffs = build_handoffs(
                handoff_root=Path(self.settings.handoff_dir),
                item_id=item_id,
                draft=draft,
                price_cents=price,
                zip_code=details.zip_code,
                image_urls=image_urls,
                platforms=[channel],
            )
            for handoff in handoffs:
                with Session(self.engine) as session:
                    pack = session.get(ListingPack, pack_id)
                    assert pack is not None
                    pack.status = ListingPackStatus.HANDOFF_READY
                    pack.handoff_path = handoff.file_path
                    session.add(pack)
                    session.commit()
                outcomes[channel] = {"status": "handoff_ready", "file": handoff.file_path}
                await self._send(chat_guid, handoff.copy_text, f"{key}:handoff-{channel}")

        with Session(self.engine) as session:
            item = session.get(Item, item_id)
            assert item is not None
            item.status = ItemStatus.LIVE if ebay_live else ItemStatus.PRICED
            session.add(item)
            conversation = session.exec(
                select(SellerConversation).where(SellerConversation.seller_id == item.seller_id)
            ).first()
            if conversation is not None:
                conversation.status = ConversationStatus.LISTED
                session.add(conversation)
            write_decision(
                session,
                item_id=item_id,
                sim_at=now,
                wall_at=self.clock.wall(),
                kind="seller",
                action="publish",
                inputs={"outcomes": outcomes},
                reason="seller replied go; published where an API exists, handed off elsewhere",
                price_before=None,
                price_after=None,
            )
            session.commit()
        if any(value["status"] == "handoff_ready" for value in outcomes.values()):
            messages.append("for facebook and offerup, paste the messages above into the apps.")
        if messages:
            await self._send(chat_guid, "\n".join(messages), f"{key}:published")
        return {"item_id": item_id, "outcomes": outcomes}

    @staticmethod
    def listed_summary(packs: list[ListingPack]) -> str:
        lines = ["it's listed. send a new photo to list something else."]
        for pack in packs:
            if pack.external_url:
                lines.append(f"{pack.channel}: {pack.external_url}")
            elif pack.status == ListingPackStatus.HANDOFF_READY:
                lines.append(f"{pack.channel}: pasted by you from the message i sent")
            elif pack.status == ListingPackStatus.FAILED:
                lines.append(f"{pack.channel}: not published ({pack.failure_reason})")
        return "\n".join(lines)
