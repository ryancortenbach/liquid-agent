from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import Engine
from sqlmodel import Session

from app.engine.demand import optimal_price
from app.engine.frontier import compute_frontier
from app.engine.state import ChannelState, ItemState
from app.ledger import write_decision
from app.models import Item, ItemStatus

HORIZON_HOURS: dict[str, int] = {
    "1 day": 24,
    "3 days": 72,
    "week": 168,
    "month": 720,
    "hold": 8760,
}
DEFAULT_HORIZON = "week"
CHANNEL_PRIORS: dict[str, tuple[float, float]] = {
    "ebay": (4, 24),
    "facebook": (2, 24),
    "offerup": (1, 24),
    "craigslist": (1, 24),
}
STEP_FRACTIONS = (0.66, 0.33, 0.12)


def parse_horizon(text: str) -> str | None:
    lowered = text.lower()
    if re.search(r"\b(no rush|whenever|hold|keep it up|a year|year)\b", lowered):
        return "hold"
    if re.search(r"\b(month|30 days|4 weeks)\b", lowered):
        return "month"
    if re.search(r"\b(week|7 days|weekend)\b", lowered):
        return "week"
    if re.search(r"\b(3 days|three days|few days|72)\b", lowered):
        return "3 days"
    if re.search(r"\b(1 day|one day|today|tomorrow|24 hours|asap|fast|quick)\b", lowered):
        return "1 day"
    return None


def horizon_hours(label: str) -> int:
    return HORIZON_HOURS.get(label, HORIZON_HOURS[DEFAULT_HORIZON])


def channels_for(platforms: list[str] | tuple[str, ...]) -> tuple[ChannelState, ...]:
    chosen = [name for name in platforms if name in CHANNEL_PRIORS] or ["ebay"]
    return tuple(
        ChannelState(name=name, prior_alpha=CHANNEL_PRIORS[name][0],
                     prior_beta_hours=CHANNEL_PRIORS[name][1])
        for name in chosen
    )


def suggest_floor_cents(market_value_cents: int, instant_quote_cents: int) -> int:
    candidate = max(instant_quote_cents, int(market_value_cents * 0.75))
    return max(500, (candidate // 500) * 500)


@dataclass(frozen=True, slots=True)
class PriceStep:
    hours_left: int
    price_cents: int
    reason: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "hours_left": self.hours_left,
            "price_cents": self.price_cents,
            "reason": self.reason,
        }


@dataclass(frozen=True, slots=True)
class PriceSchedule:
    horizon: str
    horizon_hours: int
    list_price_cents: int
    floor_cents: int
    expected_value_cents: int
    sale_probability: float
    steps: tuple[PriceStep, ...]
    frontier: list[dict[str, Any]] = field(default_factory=list)
    instant_cents: int | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "horizon": self.horizon,
            "horizon_hours": self.horizon_hours,
            "list_price_cents": self.list_price_cents,
            "floor_cents": self.floor_cents,
            "expected_value_cents": self.expected_value_cents,
            "sale_probability": round(self.sale_probability, 3),
            "steps": [step.as_dict() for step in self.steps],
            "frontier": self.frontier,
            "instant_cents": self.instant_cents,
        }


def build_state(
    item: Item, now: datetime, *, platforms: list[str] | None = None, horizon_h: int | None = None
) -> ItemState:
    hours = horizon_h or max(1.0, (item.deadline_at - now).total_seconds() / 3600)
    constraints = item.constraints_json or {}
    return ItemState(
        item_id=item.id,
        status=ItemStatus.LIVE,
        deadline_at=now + timedelta(hours=hours),
        original_horizon_hours=hours,
        floor_cents=item.floor_cents,
        market_value_cents=item.market_value_cents,
        sigma_cents=item.sigma_cents,
        instant_quote_cents=item.instant_quote_cents,
        instant_ok=bool(constraints.get("instant_ok", True)),
        channels=channels_for(platforms or constraints.get("platforms") or ["ebay"]),
    )


def compute_schedule(state: ItemState, horizon: str) -> PriceSchedule:
    hours = horizon_hours(horizon)
    opening = optimal_price(state, hours)
    steps: list[PriceStep] = []
    last = opening.price_cents
    for fraction in STEP_FRACTIONS:
        remaining = max(1, int(hours * fraction))
        candidate = optimal_price(state, remaining)
        price = min(last, max(state.floor_cents, candidate.price_cents))
        if price < last:
            steps.append(
                PriceStep(
                    hours_left=remaining,
                    price_cents=price,
                    reason=(
                        f"{remaining}h left: re-solved value "
                        f"{candidate.expected_value_cents:.0f}c, "
                        f"sale chance {candidate.sale_probability:.0%}"
                    ),
                )
            )
            last = price
    frontier = compute_frontier(state)
    return PriceSchedule(
        horizon=horizon,
        horizon_hours=hours,
        list_price_cents=max(opening.price_cents, state.floor_cents),
        floor_cents=state.floor_cents,
        expected_value_cents=int(round(opening.expected_value_cents)),
        sale_probability=opening.sale_probability,
        steps=tuple(steps),
        frontier=[
            {"hours": point.hours, "price_cents": point.price_cents,
             "probability": round(point.probability, 3)}
            for point in frontier.points
        ],
        instant_cents=frontier.instant_cents,
    )


def plan_item_price(
    *,
    engine: Engine,
    item_id: str,
    horizon: str,
    platforms: list[str],
    now: datetime,
    wall_at: datetime,
) -> PriceSchedule:
    with Session(engine) as session:
        item = session.get(Item, item_id)
        if item is None:
            raise LookupError("item not found")
        if item.floor_cents <= 0 or item.floor_source in {"missing", "derived"}:
            item.floor_cents = suggest_floor_cents(
                item.market_value_cents, item.instant_quote_cents
            )
            item.floor_source = "derived"
        hours = horizon_hours(horizon)
        item.deadline_at = now + timedelta(hours=hours)
        item.original_horizon_hours = hours
        item.constraints_json = {
            **item.constraints_json,
            "horizon": horizon,
            "platforms": platforms,
        }
        state = build_state(item, now, platforms=platforms, horizon_h=hours)
        schedule = compute_schedule(state, horizon)
        write_decision(
            session,
            item_id=item.id,
            sim_at=now,
            wall_at=wall_at,
            kind="system",
            action="price_plan",
            inputs=schedule.as_dict()
            | {"market_value_cents": item.market_value_cents, "sigma_cents": item.sigma_cents},
            reason=(
                f"{horizon} horizon: list at {schedule.list_price_cents}c, "
                f"floor {schedule.floor_cents}c, {len(schedule.steps)} markdown steps"
            ),
            price_before=None,
            price_after=schedule.list_price_cents,
        )
        session.add(item)
        session.commit()
        return schedule


def describe_schedule(schedule: PriceSchedule) -> str:
    dollars = lambda cents: f"${cents / 100:,.0f}"  # noqa: E731
    parts = [f"list at {dollars(schedule.list_price_cents)}"]
    for step in schedule.steps:
        parts.append(f"{dollars(step.price_cents)} with {step.hours_left}h left")
    parts.append(f"floor {dollars(schedule.floor_cents)}")
    return ", ".join(parts)
