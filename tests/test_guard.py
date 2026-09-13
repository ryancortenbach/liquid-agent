from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest
from hypothesis import given
from hypothesis import strategies as st

from app.engine.actions import Accept, Counter, Reprice
from app.engine.guard import InvariantViolation, check
from app.engine.state import ItemState, default_channels
from app.models import ItemStatus


@given(price_cents=st.integers(min_value=0, max_value=16_999))
def test_all_below_floor_counters_are_rejected(price_cents: int) -> None:
    now = datetime(2026, 9, 13, 16, tzinfo=UTC)
    item_state = ItemState(
        item_id="item-1",
        status=ItemStatus.LIVE,
        deadline_at=now + timedelta(hours=24),
        original_horizon_hours=24,
        floor_cents=17_000,
        market_value_cents=20_500,
        sigma_cents=2_500,
        instant_quote_cents=14_800,
        current_price_cents=21_000,
        channels=default_channels(),
    )
    action = Counter(reason="property test", offer_id="o", buyer_id="b", price_cents=price_cents)
    with pytest.raises(InvariantViolation, match="I1"):
        check(action, item_state, now)


def test_accept_after_deadline_is_rejected(item_state: ItemState, now: datetime) -> None:
    state = replace(item_state, deadline_at=now)
    action = Accept(reason="late", offer_id="o", buyer_id="b", amount_cents=18_000)
    with pytest.raises(InvariantViolation, match="I3"):
        check(action, state, now)


def test_live_price_increase_is_rejected(item_state: ItemState, now: datetime) -> None:
    action = Reprice(
        reason="bad reprice",
        price_cents=item_state.current_price_cents + 100,
        broadcast_price_cents=item_state.current_price_cents,
    )
    with pytest.raises(InvariantViolation, match="I10"):
        check(action, item_state, now)


def test_terminal_sale_cannot_accept_again(item_state: ItemState, now: datetime) -> None:
    state = replace(item_state, status=ItemStatus.SOLD)
    action = Accept(reason="duplicate", offer_id="o", buyer_id="b", amount_cents=20_000)
    with pytest.raises(InvariantViolation, match="I2"):
        check(action, state, now)
