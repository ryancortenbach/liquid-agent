from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

from sqlmodel import Session, select

from app.db import create_db_and_tables, make_engine
from app.models import Item, ItemStatus, LedgerEvent, ResearchResult, Seller
from app.research.comps import analyze, build_query, research_item
from app.research.sources import CompRecord, FixtureCompsSource, normalize_record


def test_normalize_record_reads_apify_shapes() -> None:
    sold = normalize_record(
        {"title": "Apple iPad Air 5th Gen 64GB", "priceText": "$310.00", "soldDate": "2026-09-01",
         "canonicalUrl": "https://www.ebay.com/itm/1"},
        kind="sold", source="apify:ebay-sold",
    )
    assert sold is not None
    assert sold.price_cents == 31_000
    assert sold.url == "https://www.ebay.com/itm/1"
    active = normalize_record(
        {"title": "iPad Air 5", "price": 349, "itemUrl": "https://www.ebay.com/itm/2",
         "itemSpecifics": [{"name": "Storage", "value": "64 GB"}]},
        kind="active", source="apify:ebay-active",
    )
    assert active is not None and active.specifics == {"Storage": "64 GB"}
    assert normalize_record({"title": "no price"}, kind="sold", source="x") is None


def test_analyze_filters_decoys_and_prefers_sold_median() -> None:
    fixture = FixtureCompsSource()
    query = "Apple iPad Air 5th Gen 64GB Wi-Fi M1"
    records = asyncio.run(fixture.search(query, kind="sold", max_results=50)) + asyncio.run(
        fixture.search(query, kind="active", max_results=50)
    )
    summary = analyze(query, records)
    assert summary.sold_n == 10  # the cracked-screen and case decoys are dropped
    assert summary.active_n == 8
    assert summary.basis == "sold"
    assert 29_000 <= summary.market_value_cents <= 32_000
    assert summary.sigma_cents >= int(summary.market_value_cents * 0.08)
    assert summary.active_median_cents is not None
    assert summary.active_median_cents > summary.market_value_cents
    assert all(source["source"] == "fixture" for source in summary.sources)
    assert 1 <= len(summary.sources) <= 6


def test_analyze_falls_back_to_provisional_when_nothing_matches() -> None:
    summary = analyze(
        "vintage lamp",
        [CompRecord(title="iPad Air", price_cents=30_000, kind="active", source="t")],
        provisional_cents=12_000,
    )
    assert summary.basis == "provisional"
    assert summary.market_value_cents == 12_000
    assert summary.sigma_cents == int(12_000 * 0.15)


def test_research_item_persists_result_and_updates_item() -> None:
    engine = make_engine("sqlite:///:memory:")
    create_db_and_tables(engine)
    now = datetime(2026, 9, 13, 16, 0, tzinfo=UTC)
    with Session(engine) as session:
        seller = Seller(handle="+14155550123")
        session.add(seller)
        session.flush()
        item = Item(
            seller_id=seller.id,
            title="iPad Air 5th gen 64GB wifi",
            brand="Apple",
            model="A2588",
            category="electronics",
            deadline_at=now + timedelta(hours=72),
            original_horizon_hours=72,
            floor_cents=22_000,
            market_value_cents=26_400,
            sigma_cents=3_000,
            status=ItemStatus.DRAFT,
            created_at=now,
        )
        session.add(item)
        session.commit()
        item_id = item.id
        assert build_query(item).startswith("Apple A2588 iPad Air")

    result = asyncio.run(
        research_item(
            engine=engine, item_id=item_id, sources=[FixtureCompsSource()], now=now, wall_at=now
        )
    )
    assert result.basis == "sold" and result.sold_n == 10
    with Session(engine) as session:
        item = session.get(Item, item_id)
        assert item is not None
        assert item.market_value_cents == result.market_value_cents
        assert item.comps_n == 18
        assert item.instant_quote_cents == round(item.market_value_cents * 0.72)
        assert item.status == ItemStatus.PRICED
        assert item.constraints_json["needs_market_data"] is False
        assert session.exec(select(ResearchResult)).one().sources_json
        ledger = session.exec(select(LedgerEvent).where(LedgerEvent.action == "research")).one()
        assert ledger.inputs_json["sold_n"] == 10
