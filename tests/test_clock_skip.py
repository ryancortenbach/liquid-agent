from __future__ import annotations

from datetime import UTC, datetime, timedelta

from app.clock import DemoClock


def test_demo_clock_skip_moves_forward_running_and_paused() -> None:
    wall = [datetime(2026, 9, 13, 12, 0, tzinfo=UTC)]
    clock = DemoClock(
        start=datetime(2026, 9, 13, 16, 0, tzinfo=UTC), speed=3600, wall_fn=lambda: wall[0]
    )
    assert clock.now() == datetime(2026, 9, 13, 16, 0, tzinfo=UTC)
    wall[0] += timedelta(seconds=2)  # two real seconds = two simulated hours
    assert clock.now() == datetime(2026, 9, 13, 18, 0, tzinfo=UTC)
    skipped = clock.skip(timedelta(hours=30))
    assert skipped == datetime(2026, 9, 15, 0, 0, tzinfo=UTC)  # 18:00 + 30h
    assert clock.now() == skipped
    clock.pause()
    wall[0] += timedelta(seconds=5)
    assert clock.now() == skipped  # paused: wall time no longer advances the sim
    assert clock.skip(timedelta(hours=1)) == skipped + timedelta(hours=1)
    assert clock.now() == skipped + timedelta(hours=1)
    clock.resume()
    wall[0] += timedelta(seconds=1)
    assert clock.now() == skipped + timedelta(hours=2)
