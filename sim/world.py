from __future__ import annotations

import random
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Archetype:
    name: str
    market_cents: int
    sigma_cents: int
    floor_cents: int
    instant_cents: int
    local_arrivals_per_day: float
    ebay_arrivals_per_day: float


@dataclass(frozen=True, slots=True)
class BuyerEvent:
    at_hours: float
    channel: str
    willingness_cents: int
    offer_cents: int
    ghost: bool
    pays: bool


ARCHETYPES = (
    Archetype("headphones", 20_500, 2_500, 17_000, 14_800, 2.0, 4.0),
    Archetype("desk_chair", 12_000, 2_000, 8_000, 7_200, 4.0, 0.5),
    Archetype("camera_lens", 45_000, 5_000, 34_000, 32_400, 0.5, 3.0),
)


def generate_market(archetype: Archetype, deadline_hours: int, seed: int) -> list[BuyerEvent]:
    rng = random.Random(seed)
    events: list[BuyerEvent] = []
    for channel, daily_rate, ghost_rate, pay_rate in (
        ("local", archetype.local_arrivals_per_day, 0.25, 0.85),
        ("ebay", archetype.ebay_arrivals_per_day, 0.05, 0.97),
    ):
        hourly_rate = daily_rate / 24
        at_hours = rng.expovariate(hourly_rate)
        while at_hours <= deadline_hours:
            willingness = max(
                archetype.floor_cents // 2,
                round(rng.gauss(archetype.market_cents, archetype.sigma_cents) / 100) * 100,
            )
            offer = round(willingness * rng.uniform(0.85, 1.0) / 100) * 100
            events.append(
                BuyerEvent(
                    at_hours=at_hours,
                    channel=channel,
                    willingness_cents=willingness,
                    offer_cents=offer,
                    ghost=rng.random() < ghost_rate,
                    pays=rng.random() < pay_rate,
                )
            )
            at_hours += rng.expovariate(hourly_rate)
    return sorted(events, key=lambda event: event.at_hours)
