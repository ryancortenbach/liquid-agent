from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from app.config import Settings
from app.engine.state import ItemState, default_channels
from app.models import ItemStatus


@pytest.fixture(autouse=True)
def ignore_local_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Tests must not pick up keys from a developer's .env or shell."""
    monkeypatch.setitem(Settings.model_config, "env_file", None)
    for name in ("OPENAI_API_KEY", "ANTHROPIC_API_KEY", "APIFY_TOKEN", "BB_PASSWORD",
                 "EBAY_CLIENT_ID", "EBAY_CLIENT_SECRET", "EBAY_SB_REFRESH_TOKEN"):
        monkeypatch.delenv(name, raising=False)


@pytest.fixture
def now() -> datetime:
    return datetime(2026, 9, 13, 16, 0, tzinfo=UTC)


@pytest.fixture
def item_state(now: datetime) -> ItemState:
    return ItemState(
        item_id="item-1",
        status=ItemStatus.LIVE,
        deadline_at=now + timedelta(hours=72),
        original_horizon_hours=72,
        floor_cents=17_000,
        market_value_cents=20_500,
        sigma_cents=2_500,
        instant_quote_cents=14_800,
        current_price_cents=23_300,
        channels=default_channels(),
    )
