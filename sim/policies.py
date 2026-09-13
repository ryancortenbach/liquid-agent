from __future__ import annotations

from enum import StrEnum

from sim.world import Archetype


class PolicyName(StrEnum):
    AGENT = "agent"
    STATIC_LIST = "static_list"
    STATIC_90 = "static_90"
    LINEAR_MARKDOWN = "linear_markdown"
    ORACLE = "oracle"


def baseline_price_cents(
    policy: PolicyName,
    archetype: Archetype,
    elapsed_hours: float,
    deadline_hours: int,
) -> int:
    if policy == PolicyName.STATIC_LIST:
        return archetype.market_cents
    if policy == PolicyName.STATIC_90:
        return max(archetype.floor_cents, round(archetype.market_cents * 0.9 / 100) * 100)
    if policy == PolicyName.LINEAR_MARKDOWN:
        progress = min(1, max(0, elapsed_hours / deadline_hours))
        raw = archetype.market_cents - progress * (archetype.market_cents - archetype.floor_cents)
        return max(archetype.floor_cents, round(raw / 100) * 100)
    raise ValueError(f"{policy} does not use a baseline price")
