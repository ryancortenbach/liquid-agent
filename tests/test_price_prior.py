"""A $20 charger must never be priced like a $100 item just because no comps came back."""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient
from sqlmodel import Session, select

from app.inbound.identify import ItemIdentity, normalize_identity, price_prior_cents
from app.main import create_app
from app.models import Item
from app.research.comps import analyze
from app.research.sources import CompRecord
from tests.test_listing_flow import FakeMessageAdapter, FakePhotoEditor, make_settings, send

CHARGER = ItemIdentity(
    title="Apple 20W USB-C Power Adapter",
    brand="Apple",
    model="A2305",
    category="electronics",
    condition_guess="B",
    confidence=0.9,
    new_price_usd=19.0,
    used_price_usd=10.0,
)


class ChargerIdentifier:
    async def identify(self, content: bytes, mime_type: str, caption: str) -> ItemIdentity:
        return CHARGER.model_copy(deep=True)


def comp(title: str, price: float, kind: str = "sold") -> CompRecord:
    return CompRecord(title=title, price_cents=round(price * 100), kind=kind, source="test")


def test_price_estimates_are_cleaned_and_turned_into_a_prior() -> None:
    identity = normalize_identity(
        ItemIdentity(title="x", confidence=1, new_price_usd=19, used_price_usd=40)
    )
    assert identity.used_price_usd == 19  # used can never exceed new
    assert price_prior_cents(identity) == 1900
    only_new = normalize_identity(ItemIdentity(title="x", confidence=1, new_price_usd=19))
    assert price_prior_cents(only_new) == 1045  # 55% of new
    junk = normalize_identity(ItemIdentity(title="x", confidence=1, new_price_usd=-5))
    assert junk.new_price_usd is None and price_prior_cents(junk) is None


def test_prior_bounds_which_comps_are_believable() -> None:
    query = "Apple 20W USB-C Power Adapter"
    records = [
        comp("Apple 20W USB-C Power Adapter A2305 genuine", 9.5),
        comp("Apple 20W USB-C Power Adapter charger block", 11.0),
        comp("Apple 20W USB-C Power Adapter + cable", 12.5),
        comp("Apple 20W USB-C Power Adapter", 10.0),
        comp("Apple 20W USB-C Power Adapter white", 8.0),
        # the accessory trap: the main product mentions the adapter in its title
        comp("Apple iPad Air 5th gen 64GB with 20W USB-C Power Adapter", 380.0),
        comp("Apple iPad Pro 11 with Apple 20W USB-C Power Adapter", 520.0),
        comp("Lot of 10 Apple 20W USB-C Power Adapter", 95.0),
    ]
    without_prior = analyze(query, records)
    with_prior = analyze(query, records, prior_cents=1000)
    assert with_prior.market_value_cents <= 1300
    assert with_prior.basis == "sold" and with_prior.sold_n == 5
    assert without_prior.market_value_cents >= with_prior.market_value_cents


def test_no_comps_falls_back_to_the_prior_not_a_placeholder() -> None:
    summary = analyze(
        "Apple 20W USB-C Power Adapter", [], provisional_cents=10_000, prior_cents=1000
    )
    assert summary.basis == "prior"
    assert summary.market_value_cents == 1000
    assert summary.sigma_cents >= 250
    legacy = analyze("Apple 20W USB-C Power Adapter", [], provisional_cents=10_000)
    assert legacy.basis == "provisional" and legacy.market_value_cents == 10_000


def test_charger_photo_is_priced_near_its_real_value(tmp_path: Path) -> None:
    adapter = FakeMessageAdapter()
    app = create_app(
        make_settings(tmp_path),
        photo_editor=FakePhotoEditor(),
        message_adapter=adapter,
        identifier=ChargerIdentifier(),
    )
    with TestClient(app) as client:
        send(client, "c1", "sell this", with_photo=True)
        with Session(app.state.engine) as session:
            item = session.exec(select(Item)).one()
            assert item.market_value_cents == 1000
            assert item.constraints_json["market_value_source"] == "prior"
            assert item.constraints_json["price_prior"]["cents"] == 1000
        send(client, "c2", "yes")
        send(client, "c3", "APPROVE")
        send(client, "c4", "2, just the charger")
        send(client, "c5", "week")
        card = adapter.sent_texts[-1]
        assert card.startswith("Here's the plan"), card
        with Session(app.state.engine) as session:
            item = session.exec(select(Item)).one()
            assert item.market_value_cents <= 1300, item.market_value_cents
            assert item.market_value_cents >= 700
        assert "$100" not in card
        assert "(estimate, no close matches)" in card or "based on" in card
