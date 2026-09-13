from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session

from app.db import create_db_and_tables, make_engine
from app.models import Buyer, Checkout, Item, ItemStatus, Seller


def test_database_rejects_two_open_checkouts_for_one_item() -> None:
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
        window_end = datetime.now(UTC) + timedelta(minutes=15)
        session.add(
            Checkout(
                item_id=item.id,
                buyer_id=first_buyer.id,
                amount_cents=14_000,
                window_ends_at=window_end,
            )
        )
        session.add(
            Checkout(
                item_id=item.id,
                buyer_id=second_buyer.id,
                amount_cents=14_500,
                window_ends_at=window_end,
            )
        )

        with pytest.raises(IntegrityError, match="UNIQUE constraint failed: checkout.item_id"):
            session.commit()
