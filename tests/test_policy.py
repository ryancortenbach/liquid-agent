from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta

from app.engine.actions import Accept, Counter, Escalate, Expire, Hold, Reprice
from app.engine.policy import decide
from app.engine.state import ItemState, SaleClaimState, StandingOffer
from app.models import ItemStatus


def test_accepts_executable_offer_in_endgame(item_state: ItemState, now: datetime) -> None:
    offer = StandingOffer(id="offer-1", buyer_id="buyer-1", amount_cents=18_700)
    state = replace(item_state, deadline_at=now + timedelta(hours=8), offers=(offer,))

    action = decide(state, now)

    assert isinstance(action, Accept)
    assert action.amount_cents == 18_700
    assert (
        action.inputs["accept_expected_value_cents"]
        >= action.inputs["continue_expected_value_cents"]
    )


def test_counters_below_floor_without_leaking_floor(item_state: ItemState, now: datetime) -> None:
    offer = StandingOffer(id="offer-1", buyer_id="buyer-1", amount_cents=15_000)
    state = replace(item_state, deadline_at=now + timedelta(hours=8), offers=(offer,))

    action = decide(state, now)

    assert isinstance(action, Counter)
    assert action.price_cents >= state.floor_cents


def test_reprices_after_material_drop_and_cooldown(item_state: ItemState, now: datetime) -> None:
    state = replace(
        item_state,
        current_price_cents=26_000,
        last_reprice_at=now - timedelta(hours=12),
    )

    action = decide(state, now)

    assert isinstance(action, Reprice)
    assert state.floor_cents <= action.price_cents < state.current_price_cents
    assert action.broadcast_price_cents >= state.floor_cents


def test_escalates_once_near_deadline(item_state: ItemState, now: datetime) -> None:
    state = replace(item_state, deadline_at=now + timedelta(hours=1))
    action = decide(state, now)
    assert isinstance(action, Escalate)

    already_escalated = replace(state, status=ItemStatus.ESCALATED, escalated_at=now)
    assert not isinstance(decide(already_escalated, now), Escalate)


def test_expires_at_deadline_without_instant_preauthorization(
    item_state: ItemState, now: datetime
) -> None:
    state = replace(item_state, deadline_at=now)
    assert isinstance(decide(state, now), Expire)


def test_holds_while_marketplace_sale_is_pending(item_state: ItemState, now: datetime) -> None:
    claim = SaleClaimState(
        id="claim-1",
        offer_id="offer-1",
        channel="ebay",
        amount_cents=18_700,
    )
    state = replace(
        item_state,
        status=ItemStatus.SALE_PENDING,
        active_sale_claim=claim,
    )
    assert isinstance(decide(state, now), Hold)
