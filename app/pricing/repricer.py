from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import Engine
from sqlmodel import Session, select

from app.channels.base import ChannelAdapter
from app.clock import Clock
from app.config import Settings
from app.ledger import write_decision
from app.listing.handoff import dollars
from app.market.ebay import EbayError
from app.models import Item, Listing, ListingPack, ListingPackStatus, SellerConversation

ACTIVE_PACK_STATUSES = {ListingPackStatus.PUBLISHED, ListingPackStatus.HANDOFF_READY}


def as_utc(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=UTC)


@dataclass(frozen=True, slots=True)
class RepriceOutcome:
    item_id: str
    applied: bool
    hours_left: float
    price_before: int | None = None
    price_after: int | None = None
    reason: str | None = None
    ebay_updated: bool = False
    ebay_error: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "item_id": self.item_id,
            "applied": self.applied,
            "hours_left": round(self.hours_left, 2),
            "price_before": self.price_before,
            "price_after": self.price_after,
            "reason": self.reason,
            "ebay_updated": self.ebay_updated,
            "ebay_error": self.ebay_error,
        }


def due_step(
    steps: list[dict[str, Any]], hours_left: float, current_price_cents: int
) -> dict[str, Any] | None:
    """Lowest scheduled price whose checkpoint has passed and that is below the current price."""
    due = [
        step
        for step in steps
        if float(step["hours_left"]) >= hours_left
        and int(step["price_cents"]) < current_price_cents
    ]
    if not due:
        return None
    return min(due, key=lambda step: int(step["price_cents"]))


async def reprice_item(
    *,
    engine: Engine,
    clock: Clock,
    settings: Settings,
    item_id: str,
    ebay_publisher: Any | None = None,
    adapter: ChannelAdapter | None = None,
) -> RepriceOutcome:
    now = clock.now()
    with Session(engine) as session:
        item = session.get(Item, item_id)
        if item is None:
            raise LookupError("item not found")
        hours_left = max(0.0, (as_utc(item.deadline_at) - as_utc(now)).total_seconds() / 3600)
        packs = [
            pack
            for pack in session.exec(
                select(ListingPack).where(ListingPack.item_id == item_id)
            ).all()
            if pack.status in ACTIVE_PACK_STATUSES
        ]
        if not packs:
            return RepriceOutcome(item_id, applied=False, hours_left=hours_left)
        current = min(pack.price_cents for pack in packs)
        step = due_step(packs[0].schedule_json, hours_left, current)
        if step is None:
            return RepriceOutcome(item_id, applied=False, hours_left=hours_left)
        target = max(int(step["price_cents"]), item.floor_cents)
        if target >= current:
            return RepriceOutcome(item_id, applied=False, hours_left=hours_left)
        ebay_pack = next((pack for pack in packs if pack.channel == "ebay"), None)
        ebay_ref = (
            (ebay_pack.external_offer_id, f"liquid-{item.id}")
            if ebay_pack and ebay_pack.status == ListingPackStatus.PUBLISHED
            else None
        )
        conversation = session.exec(
            select(SellerConversation).where(SellerConversation.seller_id == item.seller_id)
        ).first()
        chat_guid = conversation.chat_guid if conversation else None
        reason = str(step.get("reason") or "scheduled markdown")

    ebay_updated = False
    ebay_error: str | None = None
    if ebay_ref and ebay_publisher is not None and hasattr(ebay_publisher, "update_price"):
        offer_id, sku = ebay_ref
        try:
            await ebay_publisher.update_price(
                sku=sku,
                offer_id=offer_id or "",
                price_cents=target,
                currency=settings.ebay_currency,
                marketplace_id=settings.ebay_marketplace_id,
            )
            ebay_updated = True
        except EbayError as exc:
            ebay_error = str(exc)

    with Session(engine) as session:
        for pack in session.exec(select(ListingPack).where(ListingPack.item_id == item_id)).all():
            if pack.status in ACTIVE_PACK_STATUSES:
                pack.price_cents = target
                session.add(pack)
        listing = session.exec(
            select(Listing).where(Listing.item_id == item_id, Listing.channel == "ebay")
        ).first()
        if listing is not None:
            listing.price_cents = target
            listing.last_reprice_at = now
            session.add(listing)
        write_decision(
            session,
            item_id=item_id,
            sim_at=now,
            wall_at=clock.wall(),
            kind="tick",
            action="reprice",
            inputs={
                "hours_left": round(hours_left, 2),
                "step": step,
                "ebay_updated": ebay_updated,
                "ebay_error": ebay_error,
            },
            reason=reason,
            price_before=current,
            price_after=target,
        )
        session.commit()

    if adapter is not None and chat_guid:
        note = f"{hours_left:.0f}h left. dropped to {dollars(target)} from {dollars(current)}."
        if ebay_updated:
            note += " ebay is updated."
        elif ebay_error:
            note += f" ebay update failed: {ebay_error}."
        if any(pack.channel != "ebay" for pack in packs):
            note += " update the facebook/offerup posts to the new price when you can."
        await adapter.send_text(chat_guid, note, f"reprice:{item_id}:{target}")
    return RepriceOutcome(
        item_id,
        applied=True,
        hours_left=hours_left,
        price_before=current,
        price_after=target,
        reason=reason,
        ebay_updated=ebay_updated,
        ebay_error=ebay_error,
    )
