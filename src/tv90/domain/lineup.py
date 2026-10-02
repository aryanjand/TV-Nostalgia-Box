"""Channel wrap, ghost CH 04, and per-channel episode pools. No I/O."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date

from tv90.config import (
    HARRY_CHANNEL_NUMBER,
    HARRY_SHOW_STEM,
    HOLIDAY_CHANNEL_NUMBER,
    HOLIDAY_SHOW_STEM,
    KIPPER_CHANNEL_NUMBER,
    KIPPER_SHOW_STEM,
    OSWALD_CHANNEL_NUMBER,
    OSWALD_SHOW_STEM,
    Settings,
)
from tv90.domain.episode import Episode
from tv90.domain.holiday_calendar import HolidayCalendar

CARTOON_CHANNEL_NUMBERS = (
    KIPPER_CHANNEL_NUMBER,
    OSWALD_CHANNEL_NUMBER,
    HARRY_CHANNEL_NUMBER,
)
CARTOON_SHOW_STEM_BY_CHANNEL = {
    KIPPER_CHANNEL_NUMBER: KIPPER_SHOW_STEM,
    OSWALD_CHANNEL_NUMBER: OSWALD_SHOW_STEM,
    HARRY_CHANNEL_NUMBER: HARRY_SHOW_STEM,
}
CHANNEL_UP_STEP = 1
CHANNEL_DOWN_STEP = -1


class UnknownChannelError(Exception):
    """The remote asked for a channel that is not in the station lineup."""

    def __init__(self, channel_number: int) -> None:
        self.channel_number = channel_number
        super().__init__(f"unknown channel {channel_number}")


class ChannelLineup:
    def __init__(self, settings: Settings, holiday_calendar: HolidayCalendar) -> None:
        # Settings matches the composition root; wrap uses calendar + config numbers.
        self._settings = settings
        self._holiday_calendar = holiday_calendar

    def channels_on(self, on_date: date) -> tuple[int, ...]:
        if self._holiday_calendar.channel_four_open(on_date):
            return (*CARTOON_CHANNEL_NUMBERS, HOLIDAY_CHANNEL_NUMBER)
        return CARTOON_CHANNEL_NUMBERS

    def channel_up(self, current: int, on_date: date) -> int:
        return self._neighbor(current, on_date, CHANNEL_UP_STEP)

    def channel_down(self, current: int, on_date: date) -> int:
        return self._neighbor(current, on_date, CHANNEL_DOWN_STEP)

    def coerce_current_channel(self, current: int, on_date: date) -> int:
        if self._is_leftover_holiday_channel(current, on_date):
            return KIPPER_CHANNEL_NUMBER
        channels = self.channels_on(on_date)
        if current not in channels:
            raise UnknownChannelError(current)
        return current

    def _neighbor(self, current: int, on_date: date, step: int) -> int:
        if self._is_leftover_holiday_channel(current, on_date):
            return KIPPER_CHANNEL_NUMBER
        channels = self.channels_on(on_date)
        try:
            index = channels.index(current)
        except ValueError:
            raise UnknownChannelError(current) from None
        return channels[(index + step) % len(channels)]

    def _is_leftover_holiday_channel(self, current: int, on_date: date) -> bool:
        return (
            current == HOLIDAY_CHANNEL_NUMBER
            and not self._holiday_calendar.channel_four_open(on_date)
        )


def episodes_for_channel(
    episodes: Sequence[Episode],
    channel_number: int,
    on_date: date,
    calendar: HolidayCalendar,
) -> tuple[Episode, ...]:
    if channel_number == HOLIDAY_CHANNEL_NUMBER:
        return _holiday_channel_pool(episodes, on_date, calendar)
    show_stem = CARTOON_SHOW_STEM_BY_CHANNEL.get(channel_number)
    if show_stem is None:
        raise UnknownChannelError(channel_number)
    return tuple(episode for episode in episodes if episode.show_stem == show_stem)


def _holiday_channel_pool(
    episodes: Sequence[Episode],
    on_date: date,
    calendar: HolidayCalendar,
) -> tuple[Episode, ...]:
    active_holiday = calendar.active_holiday(on_date)
    if active_holiday is None:
        return ()
    return tuple(
        episode
        for episode in episodes
        if episode.show_stem == HOLIDAY_SHOW_STEM
        and episode.holiday_tag is active_holiday
    )
