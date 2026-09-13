from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from sqlmodel import Session, select

from app.engine.actions import (
    Accept,
    Action,
    ConfirmSale,
    Counter,
    Escalate,
    Expire,
    Hold,
    ReleaseSale,
    Reprice,
    RouteInstant,
)
from app.engine.guard import InvariantViolation, check
from app.engine.state import ItemState
from app.ids import new_id
from app.ledger import write_decision
from app.models import (
    Item,
    ItemStatus,
    Listing,
    ListingStatus,
    Offer,
    OfferStatus,
    Outbox,
    SaleClaim,
    SaleClaimStatus,
)


@dataclass(frozen=True, slots=True)
class ExecutionResult:
    applied: bool
    action_id: str
    violation: str | None = None


def _enqueue(session: Session, *, action_id: str, item_id: str, kind: str, payload: dict) -> None:
    session.add(
        Outbox(
            kind=kind,
            payload_json=payload,
            idempotency_key=f"{item_id}:{action_id}:{kind}",
        )
    )


def apply_action(
    session: Session,
    state: ItemState,
    action: Action,
    *,
    now: datetime,
    wall_at: datetime,
) -> ExecutionResult:
    action_id = new_id()
    price_before = state.current_price_cents
    price_after = price_before

    try:
        check(action, state, now)
    except InvariantViolation as exc:
        write_decision(
            session,
            item_id=state.item_id,
            sim_at=now,
            wall_at=wall_at,
            kind="system",
            action=f"rejected_{action.kind.value}",
            inputs=action.inputs,
            reason=str(exc),
            price_before=price_before,
            price_after=price_before,
        )
        session.commit()
        return ExecutionResult(applied=False, action_id=action_id, violation=str(exc))

    item = session.get(Item, state.item_id)
    if item is None:
        raise LookupError(f"item not found: {state.item_id}")

    if isinstance(action, Reprice):
        listing = session.exec(
            select(Listing).where(Listing.item_id == state.item_id, Listing.status == "live")
        ).first()
        if listing is None:
            raise LookupError(f"live listing not found: {state.item_id}")
        listing.price_cents = action.price_cents
        listing.last_reprice_at = now
        session.add(listing)
        price_after = action.price_cents
        _enqueue(
            session,
            action_id=action_id,
            item_id=state.item_id,
            kind="update_listing",
            payload={"item_id": state.item_id, "price_cents": action.price_cents},
        )
        if action.buyer_ids:
            _enqueue(
                session,
                action_id=action_id,
                item_id=state.item_id,
                kind="broadcast_offer",
                payload={
                    "item_id": state.item_id,
                    "buyer_ids": list(action.buyer_ids),
                    "price_cents": action.broadcast_price_cents,
                },
            )

    elif isinstance(action, Counter):
        offer = session.get(Offer, action.offer_id)
        if offer is None or offer.item_id != state.item_id:
            raise LookupError(f"offer not found for item: {action.offer_id}")
        offer.status = OfferStatus.COUNTERED
        session.add(offer)
        _enqueue(
            session,
            action_id=action_id,
            item_id=state.item_id,
            kind="send_counter",
            payload={"buyer_id": action.buyer_id, "price_cents": action.price_cents},
        )

    elif isinstance(action, Accept):
        offer = session.get(Offer, action.offer_id)
        if offer is None or offer.item_id != state.item_id:
            raise LookupError(f"offer not found for item: {action.offer_id}")
        offer.status = OfferStatus.ACCEPTED
        item.status = ItemStatus.SALE_PENDING
        claim = SaleClaim(
            item_id=state.item_id,
            offer_id=action.offer_id,
            channel=action.channel,
            amount_cents=action.amount_cents,
            claimed_at=now,
        )
        session.add(offer)
        session.add(item)
        session.add(claim)
        listings = session.exec(
            select(Listing).where(
                Listing.item_id == state.item_id,
                Listing.status == ListingStatus.LIVE,
            )
        ).all()
        for listing in listings:
            listing.status = ListingStatus.PAUSED
            session.add(listing)
        _enqueue(
            session,
            action_id=action_id,
            item_id=state.item_id,
            kind="accept_marketplace_offer",
            payload={
                "claim_id": claim.id,
                "buyer_id": action.buyer_id,
                "channel": action.channel,
                "amount_cents": action.amount_cents,
            },
        )
        _enqueue(
            session,
            action_id=action_id,
            item_id=state.item_id,
            kind="pause_other_listings",
            payload={"item_id": state.item_id, "winning_channel": action.channel},
        )

    elif isinstance(action, Escalate):
        item.status = ItemStatus.ESCALATED
        item.escalated_at = now
        session.add(item)
        _enqueue(
            session,
            action_id=action_id,
            item_id=state.item_id,
            kind="seller_escalation",
            payload={
                "item_id": state.item_id,
                "best_offer_cents": action.best_offer_cents,
                "floor_cents": state.floor_cents,
            },
        )

    elif isinstance(action, ConfirmSale):
        claim = session.get(SaleClaim, action.claim_id)
        if claim is None or claim.status != SaleClaimStatus.ACTIVE:
            raise LookupError(f"active sale claim not found: {action.claim_id}")
        claim.status = SaleClaimStatus.CONFIRMED
        claim.resolved_at = now
        claim.resolution_source = action.source
        claim.external_reference = action.external_reference
        item.status = ItemStatus.SOLD
        session.add(claim)
        session.add(item)
        listings = session.exec(select(Listing).where(Listing.item_id == state.item_id)).all()
        for listing in listings:
            listing.status = ListingStatus.ENDED
            session.add(listing)
        price_after = claim.amount_cents
        _enqueue(
            session,
            action_id=action_id,
            item_id=state.item_id,
            kind="end_other_listings",
            payload={"item_id": state.item_id, "sold_channel": action.channel},
        )

    elif isinstance(action, ReleaseSale):
        claim = session.get(SaleClaim, action.claim_id)
        if claim is None or claim.status != SaleClaimStatus.ACTIVE:
            raise LookupError(f"active sale claim not found: {action.claim_id}")
        claim.status = SaleClaimStatus.RELEASED
        claim.resolved_at = now
        claim.resolution_source = action.source
        item.status = ItemStatus.LIVE
        offer = session.get(Offer, claim.offer_id)
        if offer is not None:
            offer.status = OfferStatus.SUPERSEDED
            session.add(offer)
        session.add(claim)
        session.add(item)
        listings = session.exec(
            select(Listing).where(
                Listing.item_id == state.item_id,
                Listing.status == ListingStatus.PAUSED,
            )
        ).all()
        for listing in listings:
            listing.status = ListingStatus.LIVE
            session.add(listing)
        _enqueue(
            session,
            action_id=action_id,
            item_id=state.item_id,
            kind="resume_listings",
            payload={"item_id": state.item_id},
        )

    elif isinstance(action, RouteInstant):
        item.status = ItemStatus.SOLD
        session.add(item)
        listings = session.exec(select(Listing).where(Listing.item_id == state.item_id)).all()
        for listing in listings:
            listing.status = ListingStatus.ENDED
            session.add(listing)
        price_after = action.amount_cents
        _enqueue(
            session,
            action_id=action_id,
            item_id=state.item_id,
            kind="instant_exit",
            payload={"item_id": state.item_id, "amount_cents": action.amount_cents},
        )
        _enqueue(
            session,
            action_id=action_id,
            item_id=state.item_id,
            kind="end_other_listings",
            payload={"item_id": state.item_id, "sold_channel": "instant"},
        )

    elif isinstance(action, Expire):
        item.status = ItemStatus.EXPIRED
        session.add(item)

    elif not isinstance(action, Hold):
        raise TypeError(f"unsupported action: {type(action).__name__}")

    write_decision(
        session,
        item_id=state.item_id,
        sim_at=now,
        wall_at=wall_at,
        action=action.kind.value,
        inputs={**action.inputs, "action_id": action_id},
        reason=action.reason,
        price_before=price_before,
        price_after=price_after,
    )
    session.commit()
    return ExecutionResult(applied=True, action_id=action_id)
