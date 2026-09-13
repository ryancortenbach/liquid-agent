from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, ClassVar


class ActionKind(StrEnum):
    HOLD = "hold"
    REPRICE = "reprice"
    COUNTER = "counter"
    ACCEPT = "accept"
    ESCALATE = "escalate"
    ROUTE_INSTANT = "route_instant"
    EXPIRE = "expire"
    CONFIRM_SALE = "confirm_sale"
    RELEASE_SALE = "release_sale"


@dataclass(frozen=True, slots=True)
class Action:
    reason: str
    inputs: dict[str, Any] = field(default_factory=dict)
    kind: ClassVar[ActionKind]


@dataclass(frozen=True, slots=True)
class Hold(Action):
    kind: ClassVar[ActionKind] = ActionKind.HOLD


@dataclass(frozen=True, slots=True)
class Reprice(Action):
    price_cents: int = 0
    broadcast_price_cents: int = 0
    buyer_ids: tuple[str, ...] = ()
    kind: ClassVar[ActionKind] = ActionKind.REPRICE


@dataclass(frozen=True, slots=True)
class Counter(Action):
    offer_id: str = ""
    buyer_id: str = ""
    price_cents: int = 0
    kind: ClassVar[ActionKind] = ActionKind.COUNTER


@dataclass(frozen=True, slots=True)
class Accept(Action):
    offer_id: str = ""
    buyer_id: str = ""
    channel: str = ""
    amount_cents: int = 0
    kind: ClassVar[ActionKind] = ActionKind.ACCEPT


@dataclass(frozen=True, slots=True)
class Escalate(Action):
    best_offer_cents: int | None = None
    kind: ClassVar[ActionKind] = ActionKind.ESCALATE


@dataclass(frozen=True, slots=True)
class RouteInstant(Action):
    amount_cents: int = 0
    kind: ClassVar[ActionKind] = ActionKind.ROUTE_INSTANT


@dataclass(frozen=True, slots=True)
class Expire(Action):
    kind: ClassVar[ActionKind] = ActionKind.EXPIRE


@dataclass(frozen=True, slots=True)
class ConfirmSale(Action):
    claim_id: str = ""
    channel: str = ""
    external_reference: str | None = None
    source: str = ""
    kind: ClassVar[ActionKind] = ActionKind.CONFIRM_SALE


@dataclass(frozen=True, slots=True)
class ReleaseSale(Action):
    claim_id: str = ""
    source: str = ""
    kind: ClassVar[ActionKind] = ActionKind.RELEASE_SALE


PriceAction = Reprice | Counter | Accept | RouteInstant
