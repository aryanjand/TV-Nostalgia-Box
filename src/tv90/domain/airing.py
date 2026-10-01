"""What is airing now: file plus offset, or outside the broadcast day. No I/O."""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date

from tv90.config import (
    MAXIMUM_CLOCK_HOUR,
    MINIMUM_CLOCK_HOUR,
    Settings,
)
from tv90.domain.episode import Episode
from tv90.domain.holiday_calendar import HolidayCalendar
from tv90.domain.lineup import ChannelLineup, episodes_for_channel
from tv90.domain.time_weight import InvalidClockHourError
from tv90.domain.timeline import SECONDS_PER_HOUR, DailyTimelineBuilder, Slot, Timeline
from tv90.ports.duration import DurationIndex


class CorruptTimelineError(Exception):
    """Slots overlap or run backwards; this is not an empty-slate day."""

    def __init__(self, timeline: Timeline, reason: str) -> None:
        self.timeline = timeline
        self.reason = reason
        super().__init__(reason)


@dataclass(frozen=True)
class Airing:
    episode: Episode
    offset_seconds: float
    slot: Slot
    channel_number: int


@dataclass(frozen=True)
class OutsideBroadcastDay:
    """Nothing is on; the player holds the slate."""

    clock_hour: float


def resolve_airing(
    timeline: Timeline, clock_hour: float, settings: Settings
) -> Airing | OutsideBroadcastDay:
    _require_clock_hour(clock_hour)
    if clock_hour < settings.sign_on_hour or clock_hour >= settings.night_lock_hour:
        return OutsideBroadcastDay(clock_hour)
    covering = _covering_slot(timeline, clock_hour)
    if covering is None:
        return OutsideBroadcastDay(clock_hour)
    offset_seconds = (clock_hour - covering.start_hour) * SECONDS_PER_HOUR
    return Airing(
        episode=covering.episode,
        offset_seconds=offset_seconds,
        slot=covering,
        channel_number=timeline.channel_number,
    )


class Station:
    def __init__(
        self,
        settings: Settings,
        holiday_calendar: HolidayCalendar,
        duration_index: DurationIndex,
    ) -> None:
        self._lineup = ChannelLineup(settings, holiday_calendar)
        self._calendar = holiday_calendar
        self._builder = DailyTimelineBuilder(settings, holiday_calendar, duration_index)
        self._timelines: dict[tuple[date, int], Timeline] = {}

    def timeline(
        self,
        on_date: date,
        channel_number: int,
        episodes: Sequence[Episode],
    ) -> Timeline:
        live_channel = self._lineup.coerce_current_channel(channel_number, on_date)
        cache_key = (on_date, live_channel)
        cached = self._timelines.get(cache_key)
        if cached is not None:
            return cached
        pool = episodes_for_channel(episodes, live_channel, on_date, self._calendar)
        built = self._builder.build(on_date, live_channel, pool)
        self._timelines[cache_key] = built
        return built

    def timelines_on(
        self, on_date: date, episodes: Sequence[Episode]
    ) -> dict[int, Timeline]:
        return {
            channel_number: self.timeline(on_date, channel_number, episodes)
            for channel_number in self._lineup.channels_on(on_date)
        }


def _covering_slot(timeline: Timeline, clock_hour: float) -> Slot | None:
    previous_end_hour: float | None = None
    covering: Slot | None = None
    for slot in timeline.slots:
        if slot.start_hour >= slot.end_hour:
            raise CorruptTimelineError(timeline, "slot hours are inverted")
        if previous_end_hour is not None and slot.start_hour < previous_end_hour:
            raise CorruptTimelineError(timeline, "slots overlap")
        previous_end_hour = slot.end_hour
        if covering is None and slot.start_hour <= clock_hour < slot.end_hour:
            covering = slot
    return covering


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
