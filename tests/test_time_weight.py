import math
from dataclasses import replace

import pytest

from tv90.config import (
    MAXIMUM_CLOCK_HOUR,
    MINIMUM_CLOCK_HOUR,
    load_settings,
)
from tv90.domain.filename import parse_filename
from tv90.domain.time_weight import (
    InvalidClockHourError,
    TimeOfDayWeight,
    gaussian_weight,
)

# Closed-form values of exp(-(x-mean)^2 / (2 * std^2)) at 1σ and 2σ.
# Hardcoded so a broken gaussian_weight cannot hide behind a shared formula.
GAUSSIAN_ONE_STANDARD_DEVIATION = 0.6065306597126334
GAUSSIAN_TWO_STANDARD_DEVIATIONS = 0.1353352832366127

MORNING_EPISODE = parse_filename("LittleBear_S01E04_MORNING.mp4")
NIGHT_EPISODE = parse_filename("Oswald_S01E09_NIGHT.mp4")
GENERAL_EPISODE = parse_filename("Harry_S01E01.mp4")
GENERAL_DAY_TAG_EPISODE = parse_filename("LittleBear_S01E01_DAY.mp4")
HOLIDAY_GENERAL_EPISODE = parse_filename("Holiday_Rudolph_CHRISTMAS.mp4")


def _strategy() -> TimeOfDayWeight:
    return TimeOfDayWeight(load_settings({}))


def test_gaussian_weight_at_mean_is_one() -> None:
    assert gaussian_weight(8.0, 8.0, 2.0) == pytest.approx(1.0)
    assert gaussian_weight(20.0, 20.0, 1.5) == pytest.approx(1.0)


def test_gaussian_weight_one_standard_deviation_from_mean() -> None:
    assert gaussian_weight(10.0, 8.0, 2.0) == pytest.approx(
        GAUSSIAN_ONE_STANDARD_DEVIATION
    )
    assert gaussian_weight(21.5, 20.0, 1.5) == pytest.approx(
        GAUSSIAN_ONE_STANDARD_DEVIATION
    )


def test_gaussian_weight_two_standard_deviations_from_mean() -> None:
    assert gaussian_weight(12.0, 8.0, 2.0) == pytest.approx(
        GAUSSIAN_TWO_STANDARD_DEVIATIONS
    )
    assert gaussian_weight(17.0, 20.0, 1.5) == pytest.approx(
        GAUSSIAN_TWO_STANDARD_DEVIATIONS
    )


def test_morning_weight_at_eight_is_peak() -> None:
    assert _strategy().weight(MORNING_EPISODE, 8.0) == pytest.approx(1.0)


def test_night_weight_at_eight_is_floor() -> None:
    settings = load_settings({})
    raw_night = gaussian_weight(
        8.0,
        settings.night_gaussian_mean,
        settings.night_gaussian_standard_deviation,
    )

    assert raw_night < settings.time_weight_floor
    assert _strategy().weight(NIGHT_EPISODE, 8.0) == settings.time_weight_floor


def test_general_weight_at_eight_is_off_peak() -> None:
    assert _strategy().weight(GENERAL_EPISODE, 8.0) == 0.35


def test_general_weight_at_thirteen_is_midday() -> None:
    assert _strategy().weight(GENERAL_EPISODE, 13.0) == 1.0


def test_morning_weight_at_thirteen_is_floored_gaussian() -> None:
    settings = load_settings({})
    raw_morning = gaussian_weight(
        13.0,
        settings.morning_gaussian_mean,
        settings.morning_gaussian_standard_deviation,
    )

    assert raw_morning == pytest.approx(0.04393693358068612)
    assert raw_morning < settings.time_weight_floor
    assert _strategy().weight(MORNING_EPISODE, 13.0) == settings.time_weight_floor


def test_night_weight_at_thirteen_is_floored_gaussian() -> None:
    settings = load_settings({})
    raw_night = gaussian_weight(
        13.0,
        settings.night_gaussian_mean,
        settings.night_gaussian_standard_deviation,
    )

    assert raw_night < settings.time_weight_floor
    assert _strategy().weight(NIGHT_EPISODE, 13.0) == settings.time_weight_floor


def test_night_weight_at_twenty_is_peak() -> None:
    assert _strategy().weight(NIGHT_EPISODE, 20.0) == pytest.approx(1.0)


def test_morning_weight_at_twenty_is_floor() -> None:
    settings = load_settings({})
    raw_morning = gaussian_weight(
        20.0,
        settings.morning_gaussian_mean,
        settings.morning_gaussian_standard_deviation,
    )

    assert raw_morning < settings.time_weight_floor
    assert _strategy().weight(MORNING_EPISODE, 20.0) == settings.time_weight_floor


def test_general_weight_at_twenty_is_off_peak() -> None:
    assert _strategy().weight(GENERAL_EPISODE, 20.0) == 0.35


def test_general_weight_at_ten_includes_midday_start() -> None:
    assert _strategy().weight(GENERAL_EPISODE, 10.0) == 1.0


def test_morning_weight_at_ten_is_one_standard_deviation() -> None:
    assert _strategy().weight(MORNING_EPISODE, 10.0) == pytest.approx(
        GAUSSIAN_ONE_STANDARD_DEVIATION
    )


def test_general_weight_at_seventeen_excludes_midday_end() -> None:
    assert _strategy().weight(GENERAL_EPISODE, 17.0) == 0.35


def test_night_weight_at_seventeen_is_two_standard_deviations() -> None:
    assert _strategy().weight(NIGHT_EPISODE, 17.0) == pytest.approx(
        GAUSSIAN_TWO_STANDARD_DEVIATIONS
    )


def test_morning_weight_far_from_mean_is_exactly_the_floor() -> None:
    weight = _strategy().weight(MORNING_EPISODE, 0.0)

    assert weight == 0.05
    assert weight != 0.0


def test_day_tagged_episode_uses_general_piecewise() -> None:
    strategy = _strategy()

    assert strategy.weight(GENERAL_DAY_TAG_EPISODE, 8.0) == 0.35
    assert strategy.weight(GENERAL_DAY_TAG_EPISODE, 13.0) == 1.0


def test_general_daypart_does_not_use_the_morning_gaussian() -> None:
    strategy = _strategy()
    morning_at_eight = strategy.weight(MORNING_EPISODE, 8.0)
    general_at_eight = strategy.weight(GENERAL_EPISODE, 8.0)

    assert morning_at_eight == pytest.approx(1.0)
    assert general_at_eight == 0.35
    assert general_at_eight != pytest.approx(morning_at_eight)


def test_holiday_movie_without_daypart_uses_general_piecewise() -> None:
    strategy = _strategy()

    assert strategy.weight(HOLIDAY_GENERAL_EPISODE, 8.0) == 0.35
    assert strategy.weight(HOLIDAY_GENERAL_EPISODE, 13.0) == 1.0


def test_morning_peak_follows_settings_mean() -> None:
    settings = replace(load_settings({}), morning_gaussian_mean=9.0)
    strategy = TimeOfDayWeight(settings)

    assert strategy.weight(MORNING_EPISODE, 9.0) == pytest.approx(1.0)
    assert strategy.weight(MORNING_EPISODE, 8.0) < 1.0


def test_floor_follows_settings_time_weight_floor() -> None:
    settings = replace(load_settings({}), time_weight_floor=0.08)
    strategy = TimeOfDayWeight(settings)

    assert strategy.weight(MORNING_EPISODE, 20.0) == 0.08


@pytest.mark.parametrize("clock_hour", [math.nan, math.inf, -math.inf])
def test_non_finite_clock_hour_raises(clock_hour: float) -> None:
    with pytest.raises(InvalidClockHourError):
        _strategy().weight(MORNING_EPISODE, clock_hour)


def test_gaussian_weight_rejects_non_finite_clock_hour() -> None:
    with pytest.raises(InvalidClockHourError):
        gaussian_weight(math.nan, 8.0, 2.0)


def test_clock_hour_below_minimum_raises() -> None:
    with pytest.raises(InvalidClockHourError):
        _strategy().weight(MORNING_EPISODE, MINIMUM_CLOCK_HOUR - 0.01)


def test_clock_hour_above_maximum_raises() -> None:
    with pytest.raises(InvalidClockHourError):
        _strategy().weight(MORNING_EPISODE, MAXIMUM_CLOCK_HOUR + 0.01)


def test_clock_hour_at_minimum_is_allowed() -> None:
    weight = _strategy().weight(GENERAL_EPISODE, MINIMUM_CLOCK_HOUR)

    assert weight == 0.35


def test_clock_hour_at_maximum_is_allowed() -> None:
    weight = _strategy().weight(GENERAL_EPISODE, MAXIMUM_CLOCK_HOUR)

    assert weight == 0.35
