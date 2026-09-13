from __future__ import annotations

import asyncio
import logging
from typing import Any

from sqlalchemy import Engine
from sqlmodel import Session, select

from app.channels.base import ChannelAdapter
from app.clock import Clock
from app.config import Settings
from app.db import ItemLocks
from app.models import ListingPack, ListingPackStatus
from app.pricing.repricer import RepriceOutcome, reprice_item

log = logging.getLogger(__name__)


def active_item_ids(engine: Engine) -> list[str]:
    with Session(engine) as session:
        rows = session.exec(
            select(ListingPack.item_id).where(
                ListingPack.status.in_(  # type: ignore[attr-defined]
                    [ListingPackStatus.PUBLISHED, ListingPackStatus.HANDOFF_READY]
                )
            )
        ).all()
    return list(dict.fromkeys(rows))


async def reprice_once(
    *,
    engine: Engine,
    clock: Clock,
    settings: Settings,
    item_locks: ItemLocks,
    ebay_publisher: Any | None,
    adapter: ChannelAdapter | None,
) -> list[RepriceOutcome]:
    outcomes: list[RepriceOutcome] = []
    for item_id in active_item_ids(engine):
        async with item_locks.for_item(item_id):
            try:
                outcome = await reprice_item(
                    engine=engine,
                    clock=clock,
                    settings=settings,
                    item_id=item_id,
                    ebay_publisher=ebay_publisher,
                    adapter=adapter,
                )
            except Exception as exc:  # one item must not stop the loop
                log.warning("reprice failed for %s: %s", item_id, exc)
                continue
        if outcome.applied:
            outcomes.append(outcome)
    return outcomes


async def reprice_loop(
    *,
    engine: Engine,
    clock: Clock,
    settings: Settings,
    item_locks: ItemLocks,
    ebay_publisher: Any | None,
    adapter: ChannelAdapter | None,
    stop: asyncio.Event,
) -> None:
    """Every tick, apply any markdown step whose checkpoint has passed on the demo clock."""
    while not stop.is_set():
        await reprice_once(
            engine=engine,
            clock=clock,
            settings=settings,
            item_locks=item_locks,
            ebay_publisher=ebay_publisher,
            adapter=adapter,
        )
        try:
            await asyncio.wait_for(stop.wait(), timeout=settings.tick_seconds)
        except TimeoutError:
            continue
