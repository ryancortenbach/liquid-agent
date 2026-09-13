from __future__ import annotations

from datetime import datetime

from app.engine.actions import (
    Accept,
    Action,
    Counter,
    Expire,
    PaymentTimeout,
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
    elif isinstance(action, Accept | RouteInstant):
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
        if state.checkout is not None:
            raise InvariantViolation("I2: an open checkout already exists")
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

    if isinstance(action, PaymentTimeout):
        if state.status != ItemStatus.PENDING_PAYMENT or state.checkout is None:
            raise InvariantViolation("payment timeout requires an open checkout")
        if action.checkout_id != state.checkout.id:
            raise InvariantViolation("payment timeout targets the wrong checkout")

    if isinstance(action, Expire) and now < state.deadline_at:
        raise InvariantViolation("cannot expire an item before its deadline")
