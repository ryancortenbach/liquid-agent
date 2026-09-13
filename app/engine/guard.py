from __future__ import annotations

from datetime import datetime

from app.engine.actions import (
    Accept,
    Action,
    ConfirmSale,
    Counter,
    Expire,
    ReleaseSale,
    Reprice,
    RouteInstant,
)
from app.engine.state import ItemState
from app.models import ItemStatus


class InvariantViolation(RuntimeError):
    pass


def check(action: Action, state: ItemState, now: datetime) -> None:
    price = None
    if isinstance(action, Reprice | Counter):
        price = action.price_cents
    elif isinstance(action, Accept):
        price = action.amount_cents

    if price is not None and price < state.floor_cents:
        raise InvariantViolation("I1: outbound price is below the seller floor")

    if (
        state.status
        in {
            ItemStatus.SOLD,
            ItemStatus.LABELED,
            ItemStatus.SCHEDULED,
            ItemStatus.DONE,
            ItemStatus.EXPIRED,
            ItemStatus.CANCELLED,
        }
        and not action.kind.value == "hold"
    ):
        raise InvariantViolation("I2: terminal item state cannot transition")

    if isinstance(action, Accept):
        if now >= state.deadline_at:
            raise InvariantViolation("I3: cannot accept after the deadline")
        if state.active_sale_claim is not None:
            raise InvariantViolation("I2: an active marketplace sale claim already exists")
        if state.status not in {ItemStatus.LIVE, ItemStatus.ESCALATED}:
            raise InvariantViolation("I2: item is not available for acceptance")

    if isinstance(action, Reprice):
        if (
            state.status == ItemStatus.LIVE
            and state.current_price_cents is not None
            and action.price_cents > state.current_price_cents
        ):
            raise InvariantViolation("I10: list price cannot increase while live")
        if action.broadcast_price_cents < state.floor_cents:
            raise InvariantViolation("I1: broadcast price is below the seller floor")

    if isinstance(action, RouteInstant) and (
        not state.instant_ok or not state.instant_preauthorized
    ):
        raise InvariantViolation("instant exit is not preauthorized")

    if isinstance(action, ConfirmSale):
        if state.status != ItemStatus.SALE_PENDING or state.active_sale_claim is None:
            raise InvariantViolation("sale confirmation requires an active marketplace claim")
        if action.claim_id != state.active_sale_claim.id:
            raise InvariantViolation("sale confirmation targets the wrong claim")
        if action.source not in {"marketplace_webhook", "seller_confirmation"}:
            raise InvariantViolation("sale confirmation source is not trusted")

    if isinstance(action, ReleaseSale):
        if state.status != ItemStatus.SALE_PENDING or state.active_sale_claim is None:
            raise InvariantViolation("sale release requires an active marketplace claim")
        if action.claim_id != state.active_sale_claim.id:
            raise InvariantViolation("sale release targets the wrong claim")

    if isinstance(action, Expire) and now < state.deadline_at:
        raise InvariantViolation("cannot expire an item before its deadline")
