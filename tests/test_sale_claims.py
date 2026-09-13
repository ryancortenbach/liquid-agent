from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlmodel import Session, select

from app.db import create_db_and_tables, make_engine
from app.engine.actions import Accept, ConfirmSale, ReleaseSale
from app.engine.executor import apply_action
from app.engine.load_state import load_state
from app.engine.state import ItemState, StandingOffer, default_channels
from app.models import (
    Buyer,
    Item,
    ItemStatus,
    Listing,
    ListingStatus,
    Offer,
    Outbox,
    SaleClaim,
    SaleClaimStatus,
    Seller,
)


def setup_sale() -> tuple:
    engine = make_engine("sqlite:///:memory:")
    create_db_and_tables(engine)
    now = datetime(2026, 9, 13, 16, tzinfo=UTC)
    with Session(engine) as session:
        seller = Seller(handle="seller")
        buyer = Buyer(handle="marketplace-buyer", channel="ebay", close_reliability=0.97)
        session.add_all([seller, buyer])
        session.flush()
        item = Item(
            seller_id=seller.id,
            title="Sony WH-1000XM5",
            deadline_at=now + timedelta(hours=24),
            original_horizon_hours=24,
            floor_cents=17_000,
            market_value_cents=20_500,
            sigma_cents=2_500,
            status=ItemStatus.LIVE,
        )
        session.add(item)
        session.flush()
        session.add_all(
            [
                Listing(
                    item_id=item.id,
                    channel="ebay",
                    price_cents=21_000,
                    status=ListingStatus.LIVE,
                ),
                Listing(
                    item_id=item.id,
                    channel="facebook",
                    price_cents=21_000,
                    status=ListingStatus.LIVE,
                ),
            ]
        )
        offer = Offer(item_id=item.id, buyer_id=buyer.id, amount_cents=19_800)
        session.add(offer)
        session.commit()
        return engine, now, item.id, buyer.id, offer.id


def test_accept_pauses_every_channel_and_creates_one_claim() -> None:
    engine, now, item_id, buyer_id, offer_id = setup_sale()
    state = ItemState(
        item_id=item_id,
        status=ItemStatus.LIVE,
        deadline_at=now + timedelta(hours=24),
        original_horizon_hours=24,
        floor_cents=17_000,
        market_value_cents=20_500,
        sigma_cents=2_500,
        instant_quote_cents=14_800,
        current_price_cents=21_000,
        channels=default_channels(),
        offers=(
            StandingOffer(
                id=offer_id,
                buyer_id=buyer_id,
                amount_cents=19_800,
                channel="ebay",
            ),
        ),
    )
    action = Accept(
        reason="best marketplace offer",
        offer_id=offer_id,
        buyer_id=buyer_id,
        channel="ebay",
        amount_cents=19_800,
    )

    with Session(engine) as session:
        result = apply_action(session, state, action, now=now, wall_at=now)
        assert result.applied is True
        assert session.get(Item, item_id).status == ItemStatus.SALE_PENDING
        assert {row.status for row in session.exec(select(Listing)).all()} == {ListingStatus.PAUSED}
        claims = session.exec(select(SaleClaim)).all()
        assert len(claims) == 1
        assert claims[0].status == SaleClaimStatus.ACTIVE
        assert {row.kind for row in session.exec(select(Outbox)).all()} == {
            "accept_marketplace_offer",
            "pause_other_listings",
        }


def test_verified_marketplace_sale_ends_all_listings() -> None:
    engine, now, item_id, buyer_id, offer_id = setup_sale()
    initial = ItemState(
        item_id=item_id,
        status=ItemStatus.LIVE,
        deadline_at=now + timedelta(hours=24),
        original_horizon_hours=24,
        floor_cents=17_000,
        market_value_cents=20_500,
        sigma_cents=2_500,
        instant_quote_cents=14_800,
        current_price_cents=21_000,
        channels=default_channels(),
    )
    accept = Accept(
        reason="best marketplace offer",
        offer_id=offer_id,
        buyer_id=buyer_id,
        channel="ebay",
        amount_cents=19_800,
    )
    with Session(engine) as session:
        apply_action(session, initial, accept, now=now, wall_at=now)
        pending = load_state(session, item_id)
        confirmation = ConfirmSale(
            reason="eBay order event confirmed the sale",
            claim_id=pending.active_sale_claim.id,
            channel="ebay",
            external_reference="order-123",
            source="marketplace_webhook",
        )
        result = apply_action(
            session,
            pending,
            confirmation,
            now=now + timedelta(minutes=1),
            wall_at=now,
        )
        assert result.applied is True
        assert session.get(Item, item_id).status == ItemStatus.SOLD
        assert {row.status for row in session.exec(select(Listing)).all()} == {ListingStatus.ENDED}


def test_failed_marketplace_close_releases_claim_and_resumes_listings() -> None:
    engine, now, item_id, buyer_id, offer_id = setup_sale()
    initial = ItemState(
        item_id=item_id,
        status=ItemStatus.LIVE,
        deadline_at=now + timedelta(hours=24),
        original_horizon_hours=24,
        floor_cents=17_000,
        market_value_cents=20_500,
        sigma_cents=2_500,
        instant_quote_cents=14_800,
        current_price_cents=21_000,
        channels=default_channels(),
    )
    with Session(engine) as session:
        apply_action(
            session,
            initial,
            Accept(
                reason="best marketplace offer",
                offer_id=offer_id,
                buyer_id=buyer_id,
                channel="ebay",
                amount_cents=19_800,
            ),
            now=now,
            wall_at=now,
        )
        pending = load_state(session, item_id)
        result = apply_action(
            session,
            pending,
            ReleaseSale(
                reason="marketplace buyer withdrew",
                claim_id=pending.active_sale_claim.id,
                source="marketplace_webhook",
            ),
            now=now + timedelta(minutes=1),
            wall_at=now,
        )
        assert result.applied is True
        assert session.get(Item, item_id).status == ItemStatus.LIVE
        assert {row.status for row in session.exec(select(Listing)).all()} == {ListingStatus.LIVE}
