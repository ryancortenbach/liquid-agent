from __future__ import annotations

from app.engine.demand import (
    arrival_rate_per_hour,
    optimal_price,
    sale_probability,
    willingness_to_pay_probability,
)
from app.engine.frontier import compute_frontier
from app.engine.state import ChannelState, ItemState


def test_willingness_to_pay_falls_as_price_rises() -> None:
    low = willingness_to_pay_probability(18_000, 20_500, 2_500)
    high = willingness_to_pay_probability(23_000, 20_500, 2_500)
    assert low > high


def test_no_inquiries_lower_the_arrival_posterior() -> None:
    prior = ChannelState("local", prior_alpha=2, prior_beta_hours=24)
    quiet_day = ChannelState("local", prior_alpha=2, prior_beta_hours=24, elapsed_hours=24)
    assert arrival_rate_per_hour(quiet_day) < arrival_rate_per_hour(prior)


def test_views_contribute_fractional_demand() -> None:
    quiet = ChannelState("local", prior_alpha=2, prior_beta_hours=24, elapsed_hours=24)
    viewed = ChannelState(
        "local",
        prior_alpha=2,
        prior_beta_hours=24,
        elapsed_hours=24,
        views=20,
    )
    assert arrival_rate_per_hour(viewed) > arrival_rate_per_hour(quiet)


def test_horizon_increases_sale_probability(item_state: ItemState) -> None:
    short = sale_probability(item_state, 21_000, 12)
    long = sale_probability(item_state, 21_000, 72)
    assert 0 < short < long < 1


def test_optimal_price_and_frontier_respect_bounds(item_state: ItemState) -> None:
    optimal = optimal_price(item_state, 72)
    frontier = compute_frontier(item_state)

    assert item_state.floor_cents <= optimal.price_cents <= item_state.market_value_cents * 1.3
    assert frontier.instant_cents == item_state.instant_quote_cents
    assert len(frontier.points) == 3
    for point in frontier.points:
        if point.price_cents is not None:
            assert point.price_cents >= item_state.floor_cents
            assert point.probability >= 0.85
