from __future__ import annotations

from dataclasses import dataclass

from app.engine.demand import candidate_prices, sale_probability
from app.engine.state import ItemState


@dataclass(frozen=True, slots=True)
class FrontierPoint:
    hours: int
    price_cents: int | None
    probability: float


@dataclass(frozen=True, slots=True)
class LiquidityFrontier:
    instant_cents: int | None
    points: tuple[FrontierPoint, ...]


def compute_frontier(
    state: ItemState,
    horizons: tuple[int, ...] = (24, 72, 168),
    confidence: float = 0.85,
) -> LiquidityFrontier:
    points: list[FrontierPoint] = []
    prices = list(candidate_prices(state))
    for hours in horizons:
        qualifying = [
            (price, sale_probability(state, price, hours))
            for price in prices
            if sale_probability(state, price, hours) >= confidence
        ]
        if qualifying:
            price, probability = qualifying[-1]
            points.append(FrontierPoint(hours, price, probability))
        else:
            floor_probability = sale_probability(state, state.floor_cents, hours)
            points.append(FrontierPoint(hours, None, floor_probability))
    return LiquidityFrontier(
        instant_cents=state.instant_quote_cents if state.instant_ok else None,
        points=tuple(points),
    )
