from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from app.models import ItemStatus


@dataclass(frozen=True, slots=True)
class ChannelState:
    name: str
    prior_alpha: float
    prior_beta_hours: float
    elapsed_hours: float = 0
    inquiries: float = 0
    views: int = 0


@dataclass(frozen=True, slots=True)
class StandingOffer:
    id: str
    buyer_id: str
    amount_cents: int
    channel: str = "facebook"
    close_reliability: float = 0.85
    settlement_hours: float = 0.1
    answered: bool = False
    buyer_failed_close: bool = False


@dataclass(frozen=True, slots=True)
class SaleClaimState:
    id: str
    offer_id: str
    channel: str
    amount_cents: int


@dataclass(frozen=True, slots=True)
class ItemState:
    item_id: str
    status: ItemStatus
    deadline_at: datetime
    original_horizon_hours: float
    floor_cents: int
    market_value_cents: int
    sigma_cents: int
    instant_quote_cents: int
    instant_ok: bool = True
    instant_preauthorized: bool = False
    current_price_cents: int | None = None
    last_reprice_at: datetime | None = None
    escalated_at: datetime | None = None
    channels: tuple[ChannelState, ...] = field(default_factory=tuple)
    offers: tuple[StandingOffer, ...] = field(default_factory=tuple)
    active_sale_claim: SaleClaimState | None = None
    interested_buyer_ids: tuple[str, ...] = field(default_factory=tuple)


def default_channels() -> tuple[ChannelState, ...]:
    return (
        ChannelState(name="facebook", prior_alpha=2, prior_beta_hours=24),
        ChannelState(name="ebay", prior_alpha=4, prior_beta_hours=24),
    )
