"""Time-of-day weight from episode daypart and injected clock hour. No I/O."""

from __future__ import annotations

import math

from tv90.config import MAXIMUM_CLOCK_HOUR, MINIMUM_CLOCK_HOUR, Settings
from tv90.domain.episode import Daypart, Episode


class InvalidClockHourError(Exception):
    """clock_hour is not a finite decimal hour in the allowed range."""

    def __init__(self, clock_hour: float, reason: str) -> None:
        self.clock_hour = clock_hour
        self.reason = reason
        super().__init__(reason)


def gaussian_weight(clock_hour: float, mean: float, standard_deviation: float) -> float:
    """Unnormalized Gaussian so the peak at the mean is already 1.0."""
    _require_clock_hour(clock_hour)
    deviation = clock_hour - mean
    variance = standard_deviation * standard_deviation
    return math.exp(-(deviation * deviation) / (2.0 * variance))


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


class TimeOfDayWeight:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def weight(self, episode: Episode, clock_hour: float) -> float:
        _require_clock_hour(clock_hour)
        if episode.daypart is Daypart.MORNING:
            return self._floored_gaussian(
                clock_hour,
                self._settings.morning_gaussian_mean,
                self._settings.morning_gaussian_standard_deviation,
            )
        if episode.daypart is Daypart.NIGHT:
            return self._floored_gaussian(
                clock_hour,
                self._settings.night_gaussian_mean,
                self._settings.night_gaussian_standard_deviation,
            )
        return self._general_weight(clock_hour)

    def _floored_gaussian(
        self, clock_hour: float, mean: float, standard_deviation: float
    ) -> float:
        # Floor is statistical, not a ban: a morning file can still air at night.
        return max(
            self._settings.time_weight_floor,
            gaussian_weight(clock_hour, mean, standard_deviation),
        )

    def _general_weight(self, clock_hour: float) -> float:
        settings = self._settings
        if (
            settings.general_midday_start_hour
            <= clock_hour
            < settings.general_midday_end_hour
        ):
            return settings.general_midday_weight
        return settings.general_off_peak_weight
