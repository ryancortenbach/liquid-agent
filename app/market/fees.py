from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ChannelEconomics:
    fee_rate: float
    fixed_fee_cents: int
    shipping_cents: int

    def net_cents(self, price_cents: int) -> int:
        fee = round(price_cents * self.fee_rate) + self.fixed_fee_cents
        return max(0, price_cents - fee - self.shipping_cents)


DEFAULT_ECONOMICS: dict[str, ChannelEconomics] = {
    "ebay": ChannelEconomics(fee_rate=0.1325, fixed_fee_cents=30, shipping_cents=1_200),
    "local": ChannelEconomics(fee_rate=0.029, fixed_fee_cents=30, shipping_cents=0),
    "instant": ChannelEconomics(fee_rate=0, fixed_fee_cents=0, shipping_cents=0),
}


def net_proceeds_cents(
    channel: str,
    price_cents: int,
    economics: dict[str, ChannelEconomics] | None = None,
) -> int:
    table = economics or DEFAULT_ECONOMICS
    try:
        return table[channel].net_cents(price_cents)
    except KeyError as exc:
        raise ValueError(f"unknown channel: {channel}") from exc


def instant_quote_cents(market_value_cents: int, category: str) -> int:
    electronics = {"electronics", "headphones", "camera", "camera_lens", "computer"}
    multiplier = 0.72 if category.lower() in electronics else 0.60
    return max(2_000, round(market_value_cents * multiplier))
