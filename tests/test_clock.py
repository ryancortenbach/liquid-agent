from __future__ import annotations

from datetime import UTC, datetime, timedelta

from app.clock import DemoClock, SimClock


class FakeWall:
    def __init__(self, now: datetime) -> None:
        self.value = now

    def __call__(self) -> datetime:
        return self.value


def test_demo_clock_accelerates_and_pauses() -> None:
    wall = FakeWall(datetime(2026, 9, 13, 12, tzinfo=UTC))
    clock = DemoClock(datetime(2026, 9, 13, 16, tzinfo=UTC), speed=3600, wall_fn=wall)

    wall.value += timedelta(seconds=2)
    assert clock.now() == datetime(2026, 9, 13, 18, tzinfo=UTC)

    clock.pause()
    wall.value += timedelta(minutes=5)
    assert clock.now() == datetime(2026, 9, 13, 18, tzinfo=UTC)

    clock.resume()
    wall.value += timedelta(seconds=1)
    assert clock.now() == datetime(2026, 9, 13, 19, tzinfo=UTC)


def test_sim_clock_rejects_backward_time() -> None:
    clock = SimClock(datetime(2026, 9, 13, tzinfo=UTC))
    clock.advance(timedelta(hours=3))
    assert clock.now().hour == 3

    try:
        clock.advance(timedelta(seconds=-1))
    except ValueError as exc:
        assert "backward" in str(exc)
    else:
        raise AssertionError("backward simulation time should fail")
