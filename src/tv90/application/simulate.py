"""Plain-text dump of a day's channel timelines. No I/O."""

from __future__ import annotations

import math
from collections.abc import Sequence
from datetime import date

from tv90.config import (
    HARRY_CHANNEL_NUMBER,
    HOLIDAY_CHANNEL_NUMBER,
    HOLIDAY_SHOW_STEM,
    KIPPER_CHANNEL_NUMBER,
    MAXIMUM_CLOCK_HOUR,
    MINIMUM_CLOCK_HOUR,
    OSWALD_CHANNEL_NUMBER,
    Settings,
)
from tv90.domain.airing import Station
from tv90.domain.episode import Episode
from tv90.domain.holiday_calendar import HolidayCalendar
from tv90.domain.lineup import UnknownChannelError
from tv90.domain.time_weight import InvalidClockHourError
from tv90.domain.timeline import Timeline
from tv90.ports.duration import DurationIndex

SECONDS_PER_MINUTE = 60
CARTOON_FALLBACK_DURATION_MINUTES = 7
HOLIDAY_MOVIE_FALLBACK_DURATION_MINUTES = 60
CARTOON_FALLBACK_DURATION_SECONDS = float(
    CARTOON_FALLBACK_DURATION_MINUTES * SECONDS_PER_MINUTE
)
HOLIDAY_MOVIE_FALLBACK_DURATION_SECONDS = float(
    HOLIDAY_MOVIE_FALLBACK_DURATION_MINUTES * SECONDS_PER_MINUTE
)
HOLIDAY_FILENAME_PREFIX = f"{HOLIDAY_SHOW_STEM}_"
DURATION_INDEX_FILENAME = "duration-index.json"

MINUTES_PER_HOUR = 60
HOURS_PER_DAY = 24
MINUTES_PER_DAY = MINUTES_PER_HOUR * HOURS_PER_DAY
NOON_HOUR = 12
ANTE_MERIDIEM = "AM"
POST_MERIDIEM = "PM"

CHANNEL_NUMBER_WIDTH = 2
SLOT_FIELD_SEPARATOR = "  "
CHANNEL_SECTION_SEPARATOR = "\n\n"
CHANNEL_DISPLAY_NAME = {
    KIPPER_CHANNEL_NUMBER: "Kipper",
    OSWALD_CHANNEL_NUMBER: "Oswald",
    HARRY_CHANNEL_NUMBER: "Harry and His Bucket Full of Dinosaurs",
    HOLIDAY_CHANNEL_NUMBER: "Holiday movies",
}


class FallbackDurationIndex:
    """Named simulate fallback when duration-index.json is absent. Never probes."""

    def duration_seconds(self, filename: str) -> float:
        if filename.startswith(HOLIDAY_FILENAME_PREFIX):
            return HOLIDAY_MOVIE_FALLBACK_DURATION_SECONDS
        return CARTOON_FALLBACK_DURATION_SECONDS


def format_clock_hour(hour: float) -> str:
    _require_clock_hour(hour)
    total_minutes = int(round(hour * MINUTES_PER_HOUR))
    wrapped_minutes = total_minutes % MINUTES_PER_DAY
    hour_24, minute = divmod(wrapped_minutes, MINUTES_PER_HOUR)
    display_hour = hour_24 % NOON_HOUR
    if display_hour == 0:
        display_hour = NOON_HOUR
    meridiem = ANTE_MERIDIEM if hour_24 < NOON_HOUR else POST_MERIDIEM
    return f"{display_hour}:{minute:02d} {meridiem}"


def simulate_schedule(
    on_date: date,
    episodes: Sequence[Episode],
    duration_index: DurationIndex,
    settings: Settings,
    holiday_calendar: HolidayCalendar,
) -> str:
    station = Station(settings, holiday_calendar, duration_index)
    timelines = station.timelines_on(on_date, episodes)
    sections = tuple(
        format_channel_timeline(timeline) for timeline in timelines.values()
    )
    return CHANNEL_SECTION_SEPARATOR.join(sections) + "\n"


def format_channel_timeline(timeline: Timeline) -> str:
    lines = [format_channel_header(timeline.channel_number)]
    lines.extend(
        format_slot_line(slot.start_hour, slot.episode.filename)
        for slot in timeline.slots
    )
    return "\n".join(lines)


def format_channel_header(channel_number: int) -> str:
    try:
        display_name = CHANNEL_DISPLAY_NAME[channel_number]
    except KeyError:
        raise UnknownChannelError(channel_number) from None
    padded = f"{channel_number:0{CHANNEL_NUMBER_WIDTH}d}"
    return f"CH {padded} {display_name}"


def format_slot_line(start_hour: float, filename: str) -> str:
    return f"{format_clock_hour(start_hour)}{SLOT_FIELD_SEPARATOR}{filename}"


def _require_clock_hour(hour: float) -> None:
    if not math.isfinite(hour):
        raise InvalidClockHourError(hour, "clock_hour must be a finite number")
    if hour < MINIMUM_CLOCK_HOUR or hour > MAXIMUM_CLOCK_HOUR:
        raise InvalidClockHourError(
            hour,
            (
                "clock_hour must be a decimal hour between "
                f"{MINIMUM_CLOCK_HOUR} and {MAXIMUM_CLOCK_HOUR}"
            ),
        )
