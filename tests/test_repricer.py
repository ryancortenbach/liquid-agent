from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient
from sqlmodel import Session, select

from app.config import Mode, Settings
from app.main import create_app
from app.market.ebay import EbayDraft, EbayOfferInput, EbayPublication
from app.models import LedgerEvent, ListingPack, ListingPackStatus
from app.pricing.repricer import due_step


class FakeEbay:
    def __init__(self) -> None:
        self.price_updates: list[dict] = []

    async def create_draft(self, offer: EbayOfferInput) -> EbayDraft:
        return EbayDraft(offer_id="offer-9", sku=offer.sku)

    async def publish(self, offer_id: str, marketplace_id: str) -> EbayPublication:
        return EbayPublication(offer_id=offer_id, listing_id="2200002")

    async def update_price(self, **kwargs) -> None:
        self.price_updates.append(kwargs)

    async def close(self) -> None:
        return None


def test_due_step_picks_lowest_passed_checkpoint() -> None:
    steps = [
        {"hours_left": 47, "price_cents": 33_000, "reason": "a"},
        {"hours_left": 23, "price_cents": 31_000, "reason": "b"},
        {"hours_left": 8, "price_cents": 29_000, "reason": "c"},
    ]
    assert due_step(steps, 60, 35_000) is None
    assert due_step(steps, 40, 35_000)["price_cents"] == 33_000
    assert due_step(steps, 10, 33_000)["price_cents"] == 31_000
    assert due_step(steps, 10, 31_000) is None


def test_reprice_follows_schedule_and_updates_ebay(tmp_path: Path) -> None:
    ebay = FakeEbay()
    app = create_app(
        Settings(
            mode=Mode.SIM,
            database_url="sqlite:///:memory:",
            photo_storage_dir=str(tmp_path / "photos"),
            handoff_dir=str(tmp_path / "handoff"),
            research_mode="fixture",
            public_base_url="https://demo.example.com",
            ebay_sb_merchant_location_key="loc",
            ebay_sb_payment_policy_id="pay",
            ebay_sb_return_policy_id="ret",
            ebay_sb_fulfillment_policy_id="ful",
            ebay_sb_default_category_id="171485",
        ),
        ebay_publisher=ebay,
    )
    with TestClient(app) as client:
        item_id = client.post(
            "/api/items",
            json={
                "seller_handle": "+14155550123",
                "title": "iPad Air 5th gen 64GB",
                "brand": "Apple",
                "market_value_cents": 30_000,
                "sigma_cents": 3_500,
                "floor_cents": 22_000,
                "deadline_hours": 72,
            },
        ).json()["item_id"]
        # an approved photo is required for eBay; use the enhancement endpoint with a fake editor
        # (not configured here), so approve an original through the flow's API path instead:
        client.post(f"/api/items/{item_id}/details", json={"text": "good, 3 days, ebay only"})
        plan = client.post(f"/api/items/{item_id}/plan-listing", json={"research": True}).json()
        steps = plan["schedule"]["steps"]
        assert steps and steps[0]["price_cents"] < plan["schedule"]["list_price_cents"]

        # no approved photo yet -> eBay refuses, pack fails, nothing to reprice
        result = client.post(f"/api/items/{item_id}/go").json()
        assert result["outcomes"]["ebay"]["status"] == "failed"
        assert client.post(f"/api/items/{item_id}/reprice").json()["applied"] is False

        # mark the pack published by hand to exercise the schedule (photo approval is Ryan's flow)
        with Session(app.state.engine) as session:
            pack = session.exec(select(ListingPack)).one()
            pack.status = ListingPackStatus.PUBLISHED
            pack.external_id = "2200002"
            pack.external_offer_id = "offer-9"
            session.add(pack)
            session.commit()
            list_price = pack.price_cents

        assert client.post(f"/api/items/{item_id}/reprice").json()["applied"] is False
        skipped = client.post("/api/clock/skip", json={"hours": 30})
        assert skipped.status_code == 200
        first = client.post(f"/api/items/{item_id}/reprice").json()
        assert first["applied"] is True
        assert first["price_before"] == list_price
        assert first["price_after"] == steps[0]["price_cents"]
        assert first["ebay_updated"] is True
        assert ebay.price_updates[-1]["offer_id"] == "offer-9"
        assert ebay.price_updates[-1]["price_cents"] == steps[0]["price_cents"]
        assert client.post(f"/api/items/{item_id}/reprice").json()["applied"] is False

        client.post("/api/clock/skip", json={"hours": 25})
        second = client.post(f"/api/items/{item_id}/reprice").json()
        assert second["applied"] is True and second["price_after"] < first["price_after"]
        assert second["price_after"] >= 22_000

        with Session(app.state.engine) as session:
            reprices = session.exec(
                select(LedgerEvent).where(LedgerEvent.action == "reprice")
            ).all()
            assert len(reprices) == 2 and reprices[0].price_before == list_price
            assert session.exec(select(ListingPack)).one().price_cents == second["price_after"]


def test_reprice_once_applies_to_every_active_item(tmp_path: Path) -> None:
    import asyncio

    from app.pricing.loop import active_item_ids, reprice_once

    app = create_app(
        Settings(
            mode=Mode.SIM,
            database_url="sqlite:///:memory:",
            photo_storage_dir=str(tmp_path / "photos"),
            handoff_dir=str(tmp_path / "handoff"),
            research_mode="fixture",
            reprice_loop=False,
        )
    )
    with TestClient(app) as client:
        item_id = client.post(
            "/api/items",
            json={
                "seller_handle": "+14155550123",
                "title": "iPad Air 5th gen 64GB",
                "brand": "Apple",
                "market_value_cents": 30_000,
                "sigma_cents": 3_500,
                "floor_cents": 22_000,
                "deadline_hours": 72,
            },
        ).json()["item_id"]
        client.post(f"/api/items/{item_id}/details", json={"text": "good, 3 days, facebook only"})
        client.post(f"/api/items/{item_id}/plan-listing", json={"research": True})
        client.post(f"/api/items/{item_id}/go")  # facebook handoff -> active pack, no eBay
        assert active_item_ids(app.state.engine) == [item_id]
        client.post("/api/clock/skip", json={"hours": 30})
        outcomes = asyncio.run(
            reprice_once(
                engine=app.state.engine,
                clock=app.state.clock,
                settings=app_settings_for(app),
                item_locks=app.state.item_locks,
                ebay_publisher=None,
                adapter=None,
            )
        )
        assert len(outcomes) == 1 and outcomes[0].applied and outcomes[0].ebay_updated is False


def app_settings_for(app) -> Settings:
    from app.config import Settings as _Settings

    return _Settings(
        mode=Mode.SIM,
        database_url="sqlite:///:memory:",
        research_mode="fixture",
        tick_seconds=0.01,
    )
