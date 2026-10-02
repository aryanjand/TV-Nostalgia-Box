from datetime import date

import pytest

from tv90.config import (
    HARRY_CHANNEL_NUMBER,
    HARRY_SHOW_STEM,
    HOLIDAY_CHANNEL_NUMBER,
    HOLIDAY_SHOW_STEM,
    KIPPER_CHANNEL_NUMBER,
    KIPPER_SHOW_STEM,
    OSWALD_CHANNEL_NUMBER,
    OSWALD_SHOW_STEM,
    load_settings,
)
from tv90.domain.filename import parse_filename
from tv90.domain.holiday_calendar import HolidayCalendar
from tv90.domain.lineup import (
    ChannelLineup,
    UnknownChannelError,
    episodes_for_channel,
)

HALLOWEEN_2024 = date(2024, 10, 31)
DAY_AFTER_HALLOWEEN_2024 = date(2024, 11, 1)
JULY_FIFTEENTH = date(2024, 7, 15)

KIPPER = parse_filename("Kipper_S01E01.mp4")
KIPPER_HALLOWEEN = parse_filename("Kipper_S01E02_HALLOWEEN.mp4")
OSWALD = parse_filename("Oswald_S01E01.mp4")
OSWALD_TWO = parse_filename("Oswald_S01E02.mp4")
HARRY = parse_filename("Harry_S01E01.mp4")
HALLOWEEN_MOVIE = parse_filename("Holiday_GreatPumpkin_HALLOWEEN.mp4")
CHRISTMAS_MOVIE = parse_filename("Holiday_Rudolph_CHRISTMAS.mp4")
MIXED_LIBRARY = (
    KIPPER,
    KIPPER_HALLOWEEN,
    OSWALD,
    OSWALD_TWO,
    HARRY,
    HALLOWEEN_MOVIE,
    CHRISTMAS_MOVIE,
)


def _lineup() -> ChannelLineup:
    settings = load_settings({})
    return ChannelLineup(settings, HolidayCalendar.from_defaults(settings))


def _calendar() -> HolidayCalendar:
    return HolidayCalendar.from_defaults(load_settings({}))


def _up_cycle(lineup: ChannelLineup, on_date: date) -> tuple[int, ...]:
    visited = [KIPPER_CHANNEL_NUMBER]
    current = KIPPER_CHANNEL_NUMBER
    for _ in range(len(lineup.channels_on(on_date))):
        current = lineup.channel_up(current, on_date)
        if current == KIPPER_CHANNEL_NUMBER:
            return tuple(visited)
        visited.append(current)
    raise AssertionError("channel-up did not wrap back to CH 01")


def _down_cycle(lineup: ChannelLineup, on_date: date) -> tuple[int, ...]:
    visited = [KIPPER_CHANNEL_NUMBER]
    current = KIPPER_CHANNEL_NUMBER
    for _ in range(len(lineup.channels_on(on_date))):
        current = lineup.channel_down(current, on_date)
        if current == KIPPER_CHANNEL_NUMBER:
            return tuple(visited)
        visited.append(current)
    raise AssertionError("channel-down did not wrap back to CH 01")


def test_channel_four_is_in_the_lineup_on_halloween() -> None:
    assert _lineup().channels_on(HALLOWEEN_2024) == (
        KIPPER_CHANNEL_NUMBER,
        OSWALD_CHANNEL_NUMBER,
        HARRY_CHANNEL_NUMBER,
        HOLIDAY_CHANNEL_NUMBER,
    )


def test_channel_four_is_absent_the_day_after_halloween() -> None:
    assert _lineup().channels_on(DAY_AFTER_HALLOWEEN_2024) == (
        KIPPER_CHANNEL_NUMBER,
        OSWALD_CHANNEL_NUMBER,
        HARRY_CHANNEL_NUMBER,
    )


def test_stale_channel_four_coerces_to_channel_one_after_close() -> None:
    assert (
        _lineup().coerce_current_channel(
            HOLIDAY_CHANNEL_NUMBER, DAY_AFTER_HALLOWEEN_2024
        )
        == KIPPER_CHANNEL_NUMBER
    )


def test_channel_up_from_stale_four_lands_on_channel_one() -> None:
    assert (
        _lineup().channel_up(HOLIDAY_CHANNEL_NUMBER, DAY_AFTER_HALLOWEEN_2024)
        == KIPPER_CHANNEL_NUMBER
    )


def test_channel_down_from_stale_four_lands_on_channel_one() -> None:
    assert (
        _lineup().channel_down(HOLIDAY_CHANNEL_NUMBER, DAY_AFTER_HALLOWEEN_2024)
        == KIPPER_CHANNEL_NUMBER
    )


def test_channel_up_wraps_without_channel_four() -> None:
    lineup = _lineup()

    assert lineup.channel_up(KIPPER_CHANNEL_NUMBER, JULY_FIFTEENTH) == (
        OSWALD_CHANNEL_NUMBER
    )
    assert lineup.channel_up(OSWALD_CHANNEL_NUMBER, JULY_FIFTEENTH) == (
        HARRY_CHANNEL_NUMBER
    )
    assert lineup.channel_up(HARRY_CHANNEL_NUMBER, JULY_FIFTEENTH) == (
        KIPPER_CHANNEL_NUMBER
    )


def test_channel_up_wraps_with_channel_four() -> None:
    lineup = _lineup()

    assert lineup.channel_up(KIPPER_CHANNEL_NUMBER, HALLOWEEN_2024) == (
        OSWALD_CHANNEL_NUMBER
    )
    assert lineup.channel_up(OSWALD_CHANNEL_NUMBER, HALLOWEEN_2024) == (
        HARRY_CHANNEL_NUMBER
    )
    assert lineup.channel_up(HARRY_CHANNEL_NUMBER, HALLOWEEN_2024) == (
        HOLIDAY_CHANNEL_NUMBER
    )
    assert lineup.channel_up(HOLIDAY_CHANNEL_NUMBER, HALLOWEEN_2024) == (
        KIPPER_CHANNEL_NUMBER
    )


def test_channel_down_is_the_mirror_of_channel_up_without_channel_four() -> None:
    lineup = _lineup()
    up_cycle = _up_cycle(lineup, JULY_FIFTEENTH)
    down_cycle = _down_cycle(lineup, JULY_FIFTEENTH)

    assert up_cycle == (
        KIPPER_CHANNEL_NUMBER,
        OSWALD_CHANNEL_NUMBER,
        HARRY_CHANNEL_NUMBER,
    )
    assert down_cycle == (up_cycle[0],) + tuple(reversed(up_cycle[1:]))


def test_channel_down_is_the_mirror_of_channel_up_with_channel_four() -> None:
    lineup = _lineup()
    up_cycle = _up_cycle(lineup, HALLOWEEN_2024)
    down_cycle = _down_cycle(lineup, HALLOWEEN_2024)

    assert up_cycle == (
        KIPPER_CHANNEL_NUMBER,
        OSWALD_CHANNEL_NUMBER,
        HARRY_CHANNEL_NUMBER,
        HOLIDAY_CHANNEL_NUMBER,
    )
    assert down_cycle == (up_cycle[0],) + tuple(reversed(up_cycle[1:]))


def test_live_channel_four_stays_on_channel_four() -> None:
    assert (
        _lineup().coerce_current_channel(HOLIDAY_CHANNEL_NUMBER, HALLOWEEN_2024)
        == HOLIDAY_CHANNEL_NUMBER
    )


def test_unknown_channel_raises() -> None:
    lineup = _lineup()

    with pytest.raises(UnknownChannelError) as coerce_error:
        lineup.coerce_current_channel(99, JULY_FIFTEENTH)
    assert coerce_error.value.channel_number == 99

    with pytest.raises(UnknownChannelError):
        lineup.channel_up(0, JULY_FIFTEENTH)
    with pytest.raises(UnknownChannelError):
        lineup.channel_down(5, HALLOWEEN_2024)


def test_oswald_pool_never_contains_kipper() -> None:
    pool = episodes_for_channel(
        MIXED_LIBRARY, OSWALD_CHANNEL_NUMBER, JULY_FIFTEENTH, _calendar()
    )

    assert pool == (OSWALD, OSWALD_TWO)
    assert all(episode.show_stem == OSWALD_SHOW_STEM for episode in pool)
    assert KIPPER not in pool
    assert KIPPER_HALLOWEEN not in pool


def test_cartoon_channel_never_includes_another_show() -> None:
    kipper_pool = episodes_for_channel(
        MIXED_LIBRARY, KIPPER_CHANNEL_NUMBER, HALLOWEEN_2024, _calendar()
    )
    harry_pool = episodes_for_channel(
        MIXED_LIBRARY, HARRY_CHANNEL_NUMBER, HALLOWEEN_2024, _calendar()
    )

    assert kipper_pool == (KIPPER, KIPPER_HALLOWEEN)
    assert all(episode.show_stem == KIPPER_SHOW_STEM for episode in kipper_pool)
    assert harry_pool == (HARRY,)
    assert harry_pool[0].show_stem == HARRY_SHOW_STEM
    assert CHRISTMAS_MOVIE not in kipper_pool
    assert HALLOWEEN_MOVIE not in harry_pool


def test_channel_four_pool_is_only_the_active_holiday() -> None:
    pool = episodes_for_channel(
        MIXED_LIBRARY, HOLIDAY_CHANNEL_NUMBER, HALLOWEEN_2024, _calendar()
    )

    assert pool == (HALLOWEEN_MOVIE,)
    assert CHRISTMAS_MOVIE not in pool
    assert KIPPER_HALLOWEEN not in pool
    assert all(episode.show_stem == HOLIDAY_SHOW_STEM for episode in pool)
    assert all(episode.holiday_tag is HALLOWEEN_MOVIE.holiday_tag for episode in pool)


def test_channel_four_pool_is_empty_when_the_window_is_closed() -> None:
    pool = episodes_for_channel(
        MIXED_LIBRARY, HOLIDAY_CHANNEL_NUMBER, DAY_AFTER_HALLOWEEN_2024, _calendar()
    )

    assert pool == ()


def test_unknown_channel_pool_raises() -> None:
    with pytest.raises(UnknownChannelError) as error:
        episodes_for_channel(MIXED_LIBRARY, 99, JULY_FIFTEENTH, _calendar())

    assert error.value.channel_number == 99
