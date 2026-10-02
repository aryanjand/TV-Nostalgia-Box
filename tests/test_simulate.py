from datetime import date

import pytest

from tv90.adapters.fake_duration import FakeDurationIndex
from tv90.adapters.fake_library import FakeLibrarySource
from tv90.application.simulate import (
    CARTOON_FALLBACK_DURATION_SECONDS,
    HOLIDAY_MOVIE_FALLBACK_DURATION_SECONDS,
    FallbackDurationIndex,
    format_channel_header,
    format_clock_hour,
    simulate_schedule,
)
from tv90.config import Settings, load_settings
from tv90.domain.filename import parse_filename
from tv90.domain.holiday_calendar import HolidayCalendar
from tv90.domain.lineup import UnknownChannelError
from tv90.domain.time_weight import InvalidClockHourError

JULY_FIFTEENTH = date(2024, 7, 15)
HALLOWEEN_2024 = date(2024, 10, 31)
BROADCAST_DAY_SECONDS = (21.0 - 6.5) * 3600.0

KIPPER = parse_filename("Kipper_S01E01.mp4")
OSWALD = parse_filename("Oswald_S01E01.mp4")
HARRY = parse_filename("Harry_S01E01.mp4")
HALLOWEEN_MOVIE = parse_filename("Holiday_GreatPumpkin_HALLOWEEN.mp4")
CHRISTMAS_MOVIE = parse_filename("Holiday_Rudolph_CHRISTMAS.mp4")
TINY_LIBRARY = FakeLibrarySource(
    episodes=(KIPPER, OSWALD, HARRY, HALLOWEEN_MOVIE, CHRISTMAS_MOVIE)
)
TINY_DURATIONS = FakeDurationIndex(
    {
        KIPPER.filename: BROADCAST_DAY_SECONDS,
        OSWALD.filename: BROADCAST_DAY_SECONDS,
        HARRY.filename: BROADCAST_DAY_SECONDS,
        HALLOWEEN_MOVIE.filename: BROADCAST_DAY_SECONDS,
        CHRISTMAS_MOVIE.filename: BROADCAST_DAY_SECONDS,
    }
)


def _settings() -> Settings:
    return load_settings({})


def _calendar() -> HolidayCalendar:
    return HolidayCalendar.from_defaults(_settings())


def _simulate(on_date: date) -> str:
    return simulate_schedule(
        on_date,
        TINY_LIBRARY.episodes(),
        TINY_DURATIONS,
        _settings(),
        _calendar(),
    )


@pytest.mark.parametrize(
    ("clock_hour", "expected"),
    [
        pytest.param(6.5, "6:30 AM", id="sign-on"),
        pytest.param(8.0, "8:00 AM", id="morning"),
        pytest.param(12.0, "12:00 PM", id="noon"),
        pytest.param(13.25, "1:15 PM", id="afternoon"),
        pytest.param(0.0, "12:00 AM", id="midnight"),
        pytest.param(21.0, "9:00 PM", id="night-lock"),
        pytest.param(23.5, "11:30 PM", id="late"),
        pytest.param(24.0, "12:00 AM", id="hour-24"),
    ],
)
def test_format_clock_hour_uses_human_clock(clock_hour: float, expected: str) -> None:
    assert format_clock_hour(clock_hour) == expected


def test_format_clock_hour_rejects_non_finite() -> None:
    with pytest.raises(InvalidClockHourError):
        format_clock_hour(float("nan"))


def test_format_clock_hour_rejects_hour_outside_range() -> None:
    with pytest.raises(InvalidClockHourError):
        format_clock_hour(-0.1)


def test_format_channel_header_rejects_unknown_channel() -> None:
    with pytest.raises(UnknownChannelError):
        format_channel_header(99)


def test_simulate_schedule_on_non_holiday_prints_cartoon_channels_only() -> None:
    output = _simulate(JULY_FIFTEENTH)

    assert "CH 01 Kipper" in output
    assert "CH 02 Oswald" in output
    assert "CH 03 Harry and His Bucket Full of Dinosaurs" in output
    assert "CH 04" not in output
    assert "6:30 AM" in output
    assert KIPPER.filename in output
    assert OSWALD.filename in output
    assert HARRY.filename in output
    assert HALLOWEEN_MOVIE.filename not in output


def test_simulate_schedule_on_holiday_includes_channel_four() -> None:
    output = _simulate(HALLOWEEN_2024)

    assert "CH 01 Kipper" in output
    assert "CH 04 Holiday movies" in output
    assert HALLOWEEN_MOVIE.filename in output
    assert CHRISTMAS_MOVIE.filename not in output


def test_simulate_schedule_is_a_text_dump_not_a_picker() -> None:
    output = _simulate(JULY_FIFTEENTH)

    lowered = output.lower()
    assert "menu" not in lowered
    assert "up next" not in lowered
    assert "thumbnail" not in lowered
    assert "synopsis" not in lowered


def test_fallback_duration_uses_named_cartoon_and_holiday_constants() -> None:
    index = FallbackDurationIndex()

    assert index.duration_seconds(KIPPER.filename) == CARTOON_FALLBACK_DURATION_SECONDS
    assert (
        index.duration_seconds(HALLOWEEN_MOVIE.filename)
        == HOLIDAY_MOVIE_FALLBACK_DURATION_SECONDS
    )
    assert CARTOON_FALLBACK_DURATION_SECONDS == 7 * 60
    assert HOLIDAY_MOVIE_FALLBACK_DURATION_SECONDS == 60 * 60
