from dataclasses import FrozenInstanceError
from datetime import date

import pytest

from tv90.adapters.fake_duration import FakeDurationIndex
from tv90.config import (
    HARRY_CHANNEL_NUMBER,
    HOLIDAY_CHANNEL_NUMBER,
    LITTLE_BEAR_CHANNEL_NUMBER,
    OSWALD_CHANNEL_NUMBER,
    Settings,
    load_settings,
)
from tv90.domain.airing import (
    Airing,
    CorruptTimelineError,
    OutsideBroadcastDay,
    Station,
    resolve_airing,
)
from tv90.domain.filename import parse_filename
from tv90.domain.holiday_calendar import HolidayCalendar
from tv90.domain.lineup import UnknownChannelError, episodes_for_channel
from tv90.domain.time_weight import InvalidClockHourError
from tv90.domain.timeline import SECONDS_PER_HOUR, DailyTimelineBuilder, Slot, Timeline

JULY_FIFTEENTH = date(2024, 7, 15)
HALLOWEEN_2024 = date(2024, 10, 31)
SIGN_ON_HOUR = 6.5
NIGHT_LOCK_HOUR = 21.0
ONE_HOUR_SECONDS = float(SECONDS_PER_HOUR)
HALF_HOUR_SECONDS = 1800.0
MID_FIRST_SLOT_HOUR = 7.0
MID_FIRST_SLOT_OFFSET_SECONDS = 0.5 * SECONDS_PER_HOUR
BEFORE_SIGN_ON_HOUR = 6.0
AFTER_NIGHT_LOCK_HOUR = 22.0
GAP_HOUR = 9.0

FIRST_EPISODE = parse_filename("LittleBear_S01E01.mp4")
SECOND_EPISODE = parse_filename("LittleBear_S01E02.mp4")
OSWALD_EPISODE = parse_filename("Oswald_S01E01.mp4")
HARRY_EPISODE = parse_filename("Harry_S01E01.mp4")
HALLOWEEN_MOVIE = parse_filename("Holiday_GreatPumpkin_HALLOWEEN.mp4")
CHRISTMAS_MOVIE = parse_filename("Holiday_Rudolph_CHRISTMAS.mp4")
STATION_LIBRARY = (
    FIRST_EPISODE,
    SECOND_EPISODE,
    OSWALD_EPISODE,
    HARRY_EPISODE,
    HALLOWEEN_MOVIE,
    CHRISTMAS_MOVIE,
)


def _settings() -> Settings:
    return load_settings({})


def _constructed_timeline() -> Timeline:
    first_slot = Slot.starting_at(FIRST_EPISODE, SIGN_ON_HOUR, ONE_HOUR_SECONDS)
    second_slot = Slot.starting_at(
        SECOND_EPISODE, first_slot.end_hour, HALF_HOUR_SECONDS
    )
    return Timeline(
        JULY_FIFTEENTH,
        LITTLE_BEAR_CHANNEL_NUMBER,
        (first_slot, second_slot),
    )


def test_airing_now_mid_episode_returns_file_and_offset() -> None:
    timeline = _constructed_timeline()

    result = resolve_airing(timeline, MID_FIRST_SLOT_HOUR, _settings())

    assert isinstance(result, Airing)
    assert result.episode == FIRST_EPISODE
    assert result.offset_seconds == MID_FIRST_SLOT_OFFSET_SECONDS
    assert result.slot == timeline.slots[0]
    assert result.channel_number == LITTLE_BEAR_CHANNEL_NUMBER


def test_airing_at_sign_on_has_zero_offset() -> None:
    result = resolve_airing(_constructed_timeline(), SIGN_ON_HOUR, _settings())

    assert isinstance(result, Airing)
    assert result.episode == FIRST_EPISODE
    assert result.offset_seconds == 0.0


def test_airing_before_sign_on_is_outside_broadcast_day() -> None:
    result = resolve_airing(_constructed_timeline(), BEFORE_SIGN_ON_HOUR, _settings())

    assert isinstance(result, OutsideBroadcastDay)
    assert result.clock_hour == BEFORE_SIGN_ON_HOUR


def test_airing_at_night_lock_is_outside_broadcast_day() -> None:
    late_slot = Slot.starting_at(
        FIRST_EPISODE, NIGHT_LOCK_HOUR - 1.0, 2 * ONE_HOUR_SECONDS
    )
    timeline = Timeline(JULY_FIFTEENTH, LITTLE_BEAR_CHANNEL_NUMBER, (late_slot,))

    at_lock = resolve_airing(timeline, NIGHT_LOCK_HOUR, _settings())
    after_lock = resolve_airing(timeline, AFTER_NIGHT_LOCK_HOUR, _settings())

    assert isinstance(at_lock, OutsideBroadcastDay)
    assert isinstance(after_lock, OutsideBroadcastDay)


def test_airing_in_last_slot_before_lock_while_file_extends_past_lock() -> None:
    late_slot = Slot.starting_at(
        FIRST_EPISODE, NIGHT_LOCK_HOUR - 1.0, 2 * ONE_HOUR_SECONDS
    )
    timeline = Timeline(JULY_FIFTEENTH, LITTLE_BEAR_CHANNEL_NUMBER, (late_slot,))
    still_on_hour = NIGHT_LOCK_HOUR - 0.5

    result = resolve_airing(timeline, still_on_hour, _settings())

    assert isinstance(result, Airing)
    assert result.episode == FIRST_EPISODE
    assert result.offset_seconds == 0.5 * SECONDS_PER_HOUR


def test_gap_inside_broadcast_day_is_outside_broadcast_day() -> None:
    first_slot = Slot.starting_at(FIRST_EPISODE, SIGN_ON_HOUR, ONE_HOUR_SECONDS)
    later_slot = Slot.starting_at(SECOND_EPISODE, 10.0, ONE_HOUR_SECONDS)
    timeline = Timeline(
        JULY_FIFTEENTH,
        LITTLE_BEAR_CHANNEL_NUMBER,
        (first_slot, later_slot),
    )

    result = resolve_airing(timeline, GAP_HOUR, _settings())

    assert isinstance(result, OutsideBroadcastDay)


def test_empty_timeline_inside_broadcast_day_is_outside_broadcast_day() -> None:
    timeline = Timeline(JULY_FIFTEENTH, LITTLE_BEAR_CHANNEL_NUMBER, ())

    result = resolve_airing(timeline, MID_FIRST_SLOT_HOUR, _settings())

    assert isinstance(result, OutsideBroadcastDay)


def test_overlapping_slots_raise_corrupt_timeline() -> None:
    first_slot = Slot.starting_at(FIRST_EPISODE, SIGN_ON_HOUR, ONE_HOUR_SECONDS)
    overlapping = Slot.starting_at(
        SECOND_EPISODE, SIGN_ON_HOUR + 0.25, ONE_HOUR_SECONDS
    )
    timeline = Timeline(
        JULY_FIFTEENTH,
        LITTLE_BEAR_CHANNEL_NUMBER,
        (first_slot, overlapping),
    )

    with pytest.raises(CorruptTimelineError):
        resolve_airing(timeline, MID_FIRST_SLOT_HOUR, _settings())


def test_inverted_slot_hours_raise_corrupt_timeline() -> None:
    inverted = Slot(
        episode=FIRST_EPISODE,
        start_hour=8.0,
        duration_seconds=ONE_HOUR_SECONDS,
        end_hour=7.0,
    )
    timeline = Timeline(JULY_FIFTEENTH, LITTLE_BEAR_CHANNEL_NUMBER, (inverted,))

    with pytest.raises(CorruptTimelineError):
        resolve_airing(timeline, MID_FIRST_SLOT_HOUR, _settings())


def test_invalid_clock_hour_raises() -> None:
    timeline = _constructed_timeline()
    settings = _settings()

    with pytest.raises(InvalidClockHourError):
        resolve_airing(timeline, float("nan"), settings)
    with pytest.raises(InvalidClockHourError):
        resolve_airing(timeline, 25.0, settings)


def test_airing_is_frozen() -> None:
    result = resolve_airing(_constructed_timeline(), MID_FIRST_SLOT_HOUR, _settings())
    assert isinstance(result, Airing)
    with pytest.raises(FrozenInstanceError):
        setattr(result, "offset_seconds", 0.0)


def test_station_builds_cartoon_timelines_from_the_full_library() -> None:
    settings = _settings()
    calendar = HolidayCalendar.from_defaults(settings)
    durations = {episode.filename: HALF_HOUR_SECONDS for episode in STATION_LIBRARY}
    station = Station(settings, calendar, FakeDurationIndex(durations))
    builder = DailyTimelineBuilder(settings, calendar, FakeDurationIndex(durations))

    little_bear = station.timeline(
        JULY_FIFTEENTH, LITTLE_BEAR_CHANNEL_NUMBER, STATION_LIBRARY
    )
    expected_pool = episodes_for_channel(
        STATION_LIBRARY, LITTLE_BEAR_CHANNEL_NUMBER, JULY_FIFTEENTH, calendar
    )
    expected = builder.build(JULY_FIFTEENTH, LITTLE_BEAR_CHANNEL_NUMBER, expected_pool)

    assert little_bear == expected
    assert all(
        slot.episode.show_stem == FIRST_EPISODE.show_stem for slot in little_bear.slots
    )


def test_station_includes_channel_four_only_inside_the_holiday_window() -> None:
    settings = _settings()
    calendar = HolidayCalendar.from_defaults(settings)
    durations = {episode.filename: HALF_HOUR_SECONDS for episode in STATION_LIBRARY}
    station = Station(settings, calendar, FakeDurationIndex(durations))

    july_channels = station.timelines_on(JULY_FIFTEENTH, STATION_LIBRARY)
    halloween_channels = station.timelines_on(HALLOWEEN_2024, STATION_LIBRARY)

    assert set(july_channels) == {
        LITTLE_BEAR_CHANNEL_NUMBER,
        OSWALD_CHANNEL_NUMBER,
        HARRY_CHANNEL_NUMBER,
    }
    assert HOLIDAY_CHANNEL_NUMBER not in july_channels
    assert set(halloween_channels) == {
        LITTLE_BEAR_CHANNEL_NUMBER,
        OSWALD_CHANNEL_NUMBER,
        HARRY_CHANNEL_NUMBER,
        HOLIDAY_CHANNEL_NUMBER,
    }
    assert all(
        slot.episode == HALLOWEEN_MOVIE
        for slot in halloween_channels[HOLIDAY_CHANNEL_NUMBER].slots
    )


def test_station_cache_is_in_memory_and_reuses_the_same_timeline() -> None:
    settings = _settings()
    calendar = HolidayCalendar.from_defaults(settings)
    durations = {episode.filename: HALF_HOUR_SECONDS for episode in STATION_LIBRARY}
    station = Station(settings, calendar, FakeDurationIndex(durations))

    first = station.timeline(
        JULY_FIFTEENTH, LITTLE_BEAR_CHANNEL_NUMBER, STATION_LIBRARY
    )
    second = station.timeline(
        JULY_FIFTEENTH, LITTLE_BEAR_CHANNEL_NUMBER, STATION_LIBRARY
    )
    other_date = station.timeline(
        HALLOWEEN_2024, LITTLE_BEAR_CHANNEL_NUMBER, STATION_LIBRARY
    )

    assert first is second
    assert other_date is not first


def test_station_coerces_stale_channel_four_to_channel_one() -> None:
    settings = _settings()
    calendar = HolidayCalendar.from_defaults(settings)
    durations = {episode.filename: HALF_HOUR_SECONDS for episode in STATION_LIBRARY}
    station = Station(settings, calendar, FakeDurationIndex(durations))

    leftover = station.timeline(JULY_FIFTEENTH, HOLIDAY_CHANNEL_NUMBER, STATION_LIBRARY)
    little_bear = station.timeline(
        JULY_FIFTEENTH, LITTLE_BEAR_CHANNEL_NUMBER, STATION_LIBRARY
    )

    assert leftover is little_bear
    assert leftover.channel_number == LITTLE_BEAR_CHANNEL_NUMBER


def test_station_unknown_channel_raises() -> None:
    settings = _settings()
    station = Station(
        settings,
        HolidayCalendar.from_defaults(settings),
        FakeDurationIndex({}),
    )

    with pytest.raises(UnknownChannelError):
        station.timeline(JULY_FIFTEENTH, 99, STATION_LIBRARY)
