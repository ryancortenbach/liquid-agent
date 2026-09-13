from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from threading import Lock
from typing import Protocol


def utc_now() -> datetime:
    return datetime.now(UTC)


def require_aware(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("clock timestamps must be timezone-aware")
    return value


def as_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


class Clock(Protocol):
    def now(self) -> datetime: ...

    def wall(self) -> datetime: ...


@dataclass(slots=True)
class RealClock:
    def now(self) -> datetime:
        return utc_now()

    def wall(self) -> datetime:
        return utc_now()


class DemoClock:
    def __init__(
        self,
        start: datetime,
        speed: float = 3600,
        wall_fn=utc_now,
    ) -> None:
        if speed <= 0:
            raise ValueError("speed must be positive")
        self._speed = speed
        self._wall_fn = wall_fn
        self._sim_anchor = require_aware(start)
        self._wall_anchor = require_aware(wall_fn())
        self._paused_at: datetime | None = None
        self._lock = Lock()

    def now(self) -> datetime:
        with self._lock:
            wall = self._paused_at or require_aware(self._wall_fn())
            elapsed = (wall - self._wall_anchor).total_seconds() * self._speed
            return self._sim_anchor + timedelta(seconds=elapsed)

    def wall(self) -> datetime:
        return require_aware(self._wall_fn())

    @property
    def paused(self) -> bool:
        return self._paused_at is not None

    def pause(self) -> datetime:
        with self._lock:
            if self._paused_at is None:
                self._paused_at = require_aware(self._wall_fn())
            wall = self._paused_at
            elapsed = (wall - self._wall_anchor).total_seconds() * self._speed
            return self._sim_anchor + timedelta(seconds=elapsed)

    def skip(self, delta: timedelta) -> datetime:
        """Jump the simulated clock forward (the demo's "skip ahead" control)."""
        if delta.total_seconds() < 0:
            raise ValueError("demo clock cannot move backward")
        with self._lock:
            self._sim_anchor += delta
            return self.now() if self._paused_at is None else self._sim_anchor + timedelta(
                seconds=(self._paused_at - self._wall_anchor).total_seconds() * self._speed
            )

    def resume(self) -> datetime:
        with self._lock:
            if self._paused_at is not None:
                elapsed = (self._paused_at - self._wall_anchor).total_seconds() * self._speed
                self._sim_anchor += timedelta(seconds=elapsed)
                self._wall_anchor = require_aware(self._wall_fn())
                self._paused_at = None
            return self._sim_anchor


class SimClock:
    def __init__(self, start: datetime, wall_fn=utc_now) -> None:
        self._now = require_aware(start)
        self._wall_fn = wall_fn

    def now(self) -> datetime:
        return self._now

    def wall(self) -> datetime:
        return require_aware(self._wall_fn())

    def advance(self, delta: timedelta) -> datetime:
        if delta.total_seconds() < 0:
            raise ValueError("simulation clock cannot move backward")
        self._now += delta
        return self._now
