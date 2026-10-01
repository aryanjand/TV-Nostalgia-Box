"""Meteorological season mapping and per-file season weight. No I/O."""

from __future__ import annotations

from tv90.config import (
    AUTUMN_MONTHS,
    SPRING_MONTHS,
    SUMMER_MONTHS,
    WINTER_MONTHS,
    Settings,
)
from tv90.domain.episode import Episode, SeasonTag


class InvalidMonthError(Exception):
    """month is not a meteorological calendar month."""

    def __init__(self, month: int, reason: str) -> None:
        self.month = month
        self.reason = reason
        super().__init__(reason)


def month_to_season(month: int) -> SeasonTag:
    """Map a calendar month to a meteorological season. Never evergreen."""
    if month in SPRING_MONTHS:
        return SeasonTag.SPRING
    if month in SUMMER_MONTHS:
        return SeasonTag.SUMMER
    if month in AUTUMN_MONTHS:
        return SeasonTag.AUTUMN
    if month in WINTER_MONTHS:
        return SeasonTag.WINTER
    raise InvalidMonthError(month, "month must be a meteorological calendar month")


class SeasonWeight:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def weight(self, episode: Episode, month: int) -> float:
        calendar_season = month_to_season(month)
        # Evergreen is a file tag, not a calendar season; month is still validated.
        if episode.season_tag is SeasonTag.EVERGREEN:
            return self._settings.evergreen_season_weight
        if episode.season_tag is calendar_season:
            return self._settings.in_season_weight
        return self._settings.wrong_season_weight
