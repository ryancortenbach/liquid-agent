from __future__ import annotations

from fastapi.testclient import TestClient

from app.config import Mode, Settings
from app.main import create_app


def test_create_tick_and_ledger_round_trip() -> None:
    app = create_app(Settings(mode=Mode.SIM, database_url="sqlite:///:memory:"))
    with TestClient(app) as client:
        response = client.post(
            "/api/items",
            json={
                "seller_handle": "+14155550123",
                "title": "Sony WH-1000XM5",
                "brand": "Sony",
                "model": "WH-1000XM5",
                "market_value_cents": 20_500,
                "sigma_cents": 2_500,
                "floor_cents": 17_000,
                "deadline_hours": 72,
            },
        )
        assert response.status_code == 201
        item_id = response.json()["item_id"]
        assert response.json()["opening_price_cents"] >= 17_000

        tick = client.post(f"/api/items/{item_id}/tick")
        assert tick.status_code == 200
        assert tick.json()["applied"] is True

        ledger = client.get(f"/api/items/{item_id}/ledger")
        assert ledger.status_code == 200
        rows = ledger.json()
        assert [row["action"] for row in rows] == ["list", "hold"]
        assert all(row["reason"] for row in rows)


def test_plan_endpoint_is_credential_free() -> None:
    app = create_app(Settings(mode=Mode.SIM, database_url="sqlite:///:memory:"))
    with TestClient(app) as client:
        response = client.post(
            "/api/plan",
            json={
                "market_value_cents": 20_500,
                "sigma_cents": 2_500,
                "floor_cents": 17_000,
                "deadline_hours": 72,
            },
        )
        assert response.status_code == 200
        payload = response.json()
        assert payload["instant_cents"] == 14_760
        assert [point["hours"] for point in payload["frontier"]] == [24, 72, 168]


def test_landing_page_opens_liquid_imessage_chat() -> None:
    app = create_app(Settings(mode=Mode.SIM, database_url="sqlite:///:memory:"))
    with TestClient(app) as client:
        response = client.get("/")
    assert response.status_code == 200
    assert "the friend that helps your stuff" in response.text
    assert 'href="sms:+17027428016"' in response.text

    asset = client.get("/assets/approve-item.webp")
    assert asset.status_code == 200
    assert asset.headers["content-type"] == "image/webp"
