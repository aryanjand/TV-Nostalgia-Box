"""Product of time, season, holiday, and recency weights. No I/O."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date

from tv90.config import HOLIDAY_CHANNEL_NUMBER, Settings
from tv90.domain.episode import Daypart, Episode
from tv90.domain.holiday_calendar import HolidayCalendar
from tv90.domain.recency_weight import RecencyWeight
from tv90.domain.season_weight import SeasonWeight
from tv90.domain.time_weight import TimeOfDayWeight

# CH 04 is a movie marathon. Untagged / _DAY files are not dayparted cartoons.
HOLIDAY_CHANNEL_GENERAL_TIME_WEIGHT = 1.0


class CombinedWeight:
    def __init__(
        self,
        settings: Settings,
        holiday_calendar: HolidayCalendar,
        channel_number: int,
    ) -> None:
        self._channel_number = channel_number
        self._holiday_calendar = holiday_calendar
        self._time_of_day = TimeOfDayWeight(settings)
        self._season = SeasonWeight(settings)
        self._recency = RecencyWeight(settings)

    def weight(
        self,
        episode: Episode,
        clock_hour: float,
        on_date: date,
        recently_aired_filenames: Sequence[str],
    ) -> float:
        return (
            self._time_factor(episode, clock_hour)
            * self._season.weight(episode, on_date.month)
            * self._holiday_calendar.layer_a_multiplier(episode, on_date)
            * self._recency.weight(episode, recently_aired_filenames)
        )

    def _time_factor(self, episode: Episode, clock_hour: float) -> float:
        if (
            self._channel_number == HOLIDAY_CHANNEL_NUMBER
            and episode.daypart is Daypart.GENERAL
        ):
            return HOLIDAY_CHANNEL_GENERAL_TIME_WEIGHT
        return self._time_of_day.weight(episode, clock_hour)
