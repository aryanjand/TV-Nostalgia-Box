"""Whether the wall clock is inside the broadcast day. No I/O."""

from __future__ import annotations

import math

from tv90.config import MAXIMUM_CLOCK_HOUR, MINIMUM_CLOCK_HOUR, Settings
from tv90.domain.time_weight import InvalidClockHourError


def broadcast_day_contains(clock_hour: float, settings: Settings) -> bool:
    """True iff sign-on <= clock_hour < night lock. Standby owns the rest."""
    _require_clock_hour(clock_hour)
    return settings.sign_on_hour <= clock_hour < settings.night_lock_hour


def _require_clock_hour(clock_hour: float) -> None:
    if not math.isfinite(clock_hour):
        raise InvalidClockHourError(clock_hour, "clock_hour must be a finite number")
    if clock_hour < MINIMUM_CLOCK_HOUR or clock_hour > MAXIMUM_CLOCK_HOUR:
        raise InvalidClockHourError(
            clock_hour,
            (
                "clock_hour must be a decimal hour between "
                f"{MINIMUM_CLOCK_HOUR} and {MAXIMUM_CLOCK_HOUR}"
            ),
        )
