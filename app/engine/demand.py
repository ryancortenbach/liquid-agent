from __future__ import annotations

import math
from dataclasses import dataclass

from app.engine.state import ChannelState, ItemState, StandingOffer
from app.market.fees import net_proceeds_cents

VIEW_WEIGHT = 0.05


@dataclass(frozen=True, slots=True)
class PriceCandidate:
    price_cents: int
    expected_value_cents: float
    sale_probability: float


def candidate_prices(state: ItemState) -> range:
    ceiling = max(state.floor_cents, math.floor(state.market_value_cents * 1.3 / 100) * 100)
    return range(state.floor_cents, ceiling + 1, 100)


def willingness_to_pay_probability(price_cents: int, market_cents: int, sigma_cents: int) -> float:
    if sigma_cents <= 0:
        raise ValueError("sigma must be positive")
    z = (price_cents - market_cents) / sigma_cents
    return 0.5 * math.erfc(z / math.sqrt(2))


def arrival_rate_per_hour(channel: ChannelState) -> float:
    observations = channel.inquiries + VIEW_WEIGHT * channel.views
    return (channel.prior_alpha + observations) / (channel.prior_beta_hours + channel.elapsed_hours)


def sale_rate_per_hour(state: ItemState, price_cents: int, channel: ChannelState) -> float:
    return arrival_rate_per_hour(channel) * willingness_to_pay_probability(
        price_cents, state.market_value_cents, state.sigma_cents
    )


def sale_probability(state: ItemState, price_cents: int, hours: float) -> float:
    if hours <= 0:
        return 0
    total_rate = sum(sale_rate_per_hour(state, price_cents, channel) for channel in state.channels)
    return 1 - math.exp(-hours * total_rate)


def weighted_net_cents(state: ItemState, price_cents: int) -> float:
    rates = [
        (channel.name, sale_rate_per_hour(state, price_cents, channel))
        for channel in state.channels
    ]
    total_rate = sum(rate for _, rate in rates)
    if total_rate <= 0:
        return 0
    return sum(net_proceeds_cents(name, price_cents) * rate for name, rate in rates) / total_rate


def expected_value_cents(state: ItemState, price_cents: int, hours: float) -> float:
    probability = sale_probability(state, price_cents, hours)
    salvage = state.instant_quote_cents if state.instant_ok else 0
    return probability * weighted_net_cents(state, price_cents) + (1 - probability) * salvage


def rank_prices(state: ItemState, hours: float) -> list[PriceCandidate]:
    candidates = [
        PriceCandidate(
            price_cents=price,
            expected_value_cents=expected_value_cents(state, price, hours),
            sale_probability=sale_probability(state, price, hours),
        )
        for price in candidate_prices(state)
    ]
    return sorted(
        candidates, key=lambda row: (row.expected_value_cents, row.price_cents), reverse=True
    )


def optimal_price(state: ItemState, hours: float) -> PriceCandidate:
    return rank_prices(state, hours)[0]


def accept_expected_value_cents(state: ItemState, offer: StandingOffer, hours: float) -> float:
    remaining = max(0, hours - offer.settlement_hours)
    if remaining > 0:
        continuation = optimal_price(state, remaining).expected_value_cents
    else:
        continuation = state.instant_quote_cents if state.instant_ok else 0
    accepted_net = net_proceeds_cents(offer.channel, offer.amount_cents)
    return offer.close_reliability * accepted_net + (1 - offer.close_reliability) * continuation
