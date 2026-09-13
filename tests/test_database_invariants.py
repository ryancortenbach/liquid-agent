from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session

from app.db import create_db_and_tables, make_engine
from app.models import Buyer, Item, ItemStatus, Offer, SaleClaim, Seller


def test_database_rejects_two_active_sale_claims_for_one_item() -> None:
    engine = make_engine("sqlite:///:memory:")
    create_db_and_tables(engine)

    with Session(engine) as session:
        seller = Seller(handle="seller")
        first_buyer = Buyer(handle="first")
        second_buyer = Buyer(handle="second")
        session.add_all([seller, first_buyer, second_buyer])
        session.flush()
        item = Item(
            seller_id=seller.id,
            title="headphones",
            deadline_at=datetime.now(UTC) + timedelta(hours=24),
            original_horizon_hours=24,
            floor_cents=10_000,
            market_value_cents=15_000,
            sigma_cents=2_000,
            status=ItemStatus.LIVE,
        )
        session.add(item)
        session.flush()
        first_offer = Offer(item_id=item.id, buyer_id=first_buyer.id, amount_cents=14_000)
        second_offer = Offer(item_id=item.id, buyer_id=second_buyer.id, amount_cents=14_500)
        session.add_all([first_offer, second_offer])
        session.flush()
        session.add(
            SaleClaim(
                item_id=item.id,
                offer_id=first_offer.id,
                channel="facebook",
                amount_cents=14_000,
            )
        )
        session.add(
            SaleClaim(
                item_id=item.id,
                offer_id=second_offer.id,
                channel="ebay",
                amount_cents=14_500,
            )
        )

        with pytest.raises(IntegrityError, match="UNIQUE constraint failed: saleclaim.item_id"):
            session.commit()
