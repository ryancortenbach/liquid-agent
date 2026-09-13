from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from app.config import Mode, Settings
from app.main import create_app


def test_dashboard_lists_items_and_shows_plan(tmp_path: Path) -> None:
    app = create_app(
        Settings(
            mode=Mode.SIM,
            database_url="sqlite:///:memory:",
            photo_storage_dir=str(tmp_path / "photos"),
            handoff_dir=str(tmp_path / "handoff"),
            research_mode="fixture",
        )
    )
    with TestClient(app) as client:
        empty = client.get("/dashboard")
        assert empty.status_code == 200 and "No items yet" in empty.text
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
        client.post(f"/api/items/{item_id}/details", json={"text": "good, 3 days, all"})
        client.post(f"/api/items/{item_id}/plan-listing", json={"research": True})
        page = client.get(f"/dashboard/{item_id}")
        assert page.status_code == 200
        assert "here&#39;s the plan" in page.text or "here's the plan" in page.text
        assert "offline sample" in page.text
        assert "price_plan" in page.text and "research" in page.text
        assert "facebook" in page.text and "offerup" in page.text
        index = client.get("/dashboard")
        assert "iPad Air 5th gen 64GB" in index.text
        assert client.get("/dashboard/nope").status_code == 404
