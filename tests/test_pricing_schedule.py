from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlmodel import Session, select

from app.db import create_db_and_tables, make_engine
from app.models import Item, ItemStatus, LedgerEvent, Seller
from app.pricing.schedule import (
    build_state,
    compute_schedule,
    describe_schedule,
    parse_horizon,
    plan_item_price,
    suggest_floor_cents,
)


def test_parse_horizon_keywords() -> None:
    assert parse_horizon("need it gone by tomorrow") == "1 day"
    assert parse_horizon("3 days is fine") == "3 days"
    assert parse_horizon("within a week") == "week"
    assert parse_horizon("a month is ok") == "month"
    assert parse_horizon("no rush, hold it") == "hold"
    assert parse_horizon("just sell it") is None


def test_suggest_floor_rounds_down_to_five_dollars() -> None:
    assert suggest_floor_cents(30_300, 21_800) == 22_500
    assert suggest_floor_cents(10_000, 2_000) == 7_500


def make_item(now: datetime) -> Item:
    return Item(
        seller_id="s",
        title="iPad Air 5",
        category="electronics",
        deadline_at=now + timedelta(hours=72),
        original_horizon_hours=72,
        floor_cents=22_000,
        floor_source="seller",
        market_value_cents=30_300,
        sigma_cents=3_500,
        instant_quote_cents=21_800,
        constraints_json={"platforms": ["ebay", "facebook"]},
    )


def test_schedule_is_monotone_and_respects_floor() -> None:
    now = datetime(2026, 9, 13, 16, 0, tzinfo=UTC)
    item = make_item(now)
    item.id = "item-1"
    state = build_state(item, now, platforms=["ebay", "facebook"], horizon_h=72)
    schedule = compute_schedule(state, "3 days")
    assert schedule.horizon_hours == 72
    assert schedule.list_price_cents >= schedule.floor_cents
    assert schedule.list_price_cents > item.market_value_cents  # asks above market when time allows
    prices = [schedule.list_price_cents, *(step.price_cents for step in schedule.steps)]
    assert prices == sorted(prices, reverse=True)
    assert all(step.price_cents >= item.floor_cents for step in schedule.steps)
    assert schedule.frontier and schedule.instant_cents == 21_800
    assert "floor $220" in describe_schedule(schedule)

    quick = compute_schedule(build_state(item, now, horizon_h=24), "1 day")
    assert quick.list_price_cents <= schedule.list_price_cents


def test_plan_item_price_persists_floor_deadline_and_ledger() -> None:
    engine = make_engine("sqlite:///:memory:")
    create_db_and_tables(engine)
    now = datetime(2026, 9, 13, 16, 0, tzinfo=UTC)
    with Session(engine) as session:
        seller = Seller(handle="+14155550123")
        session.add(seller)
        session.flush()
        item = make_item(now)
        item.seller_id = seller.id
        item.floor_cents = 0
        item.floor_source = "missing"
        item.status = ItemStatus.PRICED
        session.add(item)
        session.commit()
        item_id = item.id

    schedule = plan_item_price(
        engine=engine, item_id=item_id, horizon="week", platforms=["ebay"], now=now, wall_at=now
    )
    assert schedule.floor_cents == 22_500
    with Session(engine) as session:
        item = session.get(Item, item_id)
        assert item is not None
        assert item.floor_cents == 22_500 and item.floor_source == "derived"
        assert item.original_horizon_hours == 168
        assert item.constraints_json["horizon"] == "week"
        row = session.exec(select(LedgerEvent).where(LedgerEvent.action == "price_plan")).one()
        assert row.price_after == schedule.list_price_cents
