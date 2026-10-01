"""In-memory Clock for tests. Never reads the OS clock and never sleeps."""

from datetime import datetime, timedelta


class UnawareDateTimeError(ValueError):
    """Clock times must include a timezone so airings follow local civil time."""


class FakeClock:
    def __init__(self, current_time: datetime, *, trusted: bool) -> None:
        self._current_time = _require_aware(current_time)
        self._trusted = trusted

    def now(self) -> datetime:
        return self._current_time

    def is_trusted(self) -> bool:
        return self._trusted

    def advance_time(self, duration: timedelta) -> None:
        self._current_time = self._current_time + duration

    def mark_trusted(self) -> None:
        self._trusted = True

    def mark_untrusted(self) -> None:
        self._trusted = False


def _require_aware(current_time: datetime) -> datetime:
    if current_time.tzinfo is None or current_time.utcoffset() is None:
        raise UnawareDateTimeError("FakeClock requires a timezone-aware datetime")
    return current_time
