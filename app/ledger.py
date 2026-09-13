from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlmodel import Session

from app.models import LedgerEvent


def write_decision(
    session: Session,
    *,
    item_id: str,
    sim_at: datetime,
    wall_at: datetime,
    action: str,
    inputs: dict[str, Any],
    reason: str,
    price_before: int | None,
    price_after: int | None,
    kind: str = "tick",
) -> LedgerEvent:
    row = LedgerEvent(
        item_id=item_id,
        sim_at=sim_at,
        wall_at=wall_at,
        kind=kind,
        action=action,
        inputs_json=inputs,
        reason=reason,
        price_before=price_before,
        price_after=price_after,
    )
    session.add(row)
    return row
