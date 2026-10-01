from datetime import date

from tv90.config import (
    HOLIDAY_CHANNEL_NUMBER,
    LITTLE_BEAR_CHANNEL_NUMBER,
    OSWALD_CHANNEL_NUMBER,
    load_settings,
)
from tv90.domain.combined_weight import (
    HOLIDAY_CHANNEL_GENERAL_TIME_WEIGHT,
    CombinedWeight,
)
from tv90.domain.episode import Daypart, Episode
from tv90.domain.filename import parse_filename
from tv90.domain.holiday_calendar import HolidayCalendar
from tv90.domain.recency_weight import RecencyWeight
from tv90.domain.season_weight import SeasonWeight
from tv90.domain.time_weight import TimeOfDayWeight

JULY_FIFTEENTH = date(2024, 7, 15)
CHRISTMAS_DAY = date(2024, 12, 25)
EIGHT_IN_THE_MORNING = 8.0
MIDDAY_HOUR = 13.0

SUMMER_MORNING = parse_filename("LittleBear_S01E04_MORNING_SUMMER.mp4")
WINTER_NIGHT_CHRISTMAS = parse_filename("LittleBear_S01E08_NIGHT_WINTER_CHRISTMAS.mp4")
GENERAL_EVERGREEN = parse_filename("LittleBear_S01E01.mp4")
GENERAL_DAY_TAG = parse_filename("LittleBear_S01E02_DAY.mp4")
HOLIDAY_GENERAL_MOVIE = parse_filename("Holiday_Rudolph_CHRISTMAS.mp4")
HOLIDAY_DAY_TAG_MOVIE = parse_filename("Holiday_Frosty_DAY_CHRISTMAS.mp4")
HOLIDAY_MORNING_MOVIE = parse_filename("Holiday_Rudolph_MORNING_CHRISTMAS.mp4")
HOLIDAY_NIGHT_MOVIE = parse_filename("Holiday_Rudolph_NIGHT_CHRISTMAS.mp4")


def _combined(channel_number: int = LITTLE_BEAR_CHANNEL_NUMBER) -> CombinedWeight:
    settings = load_settings({})
    return CombinedWeight(
        settings,
        HolidayCalendar.from_defaults(settings),
        channel_number,
    )


def _time_factor(episode: Episode, clock_hour: float, channel_number: int) -> float:
    if channel_number == HOLIDAY_CHANNEL_NUMBER and episode.daypart is Daypart.GENERAL:
        return HOLIDAY_CHANNEL_GENERAL_TIME_WEIGHT
    return TimeOfDayWeight(load_settings({})).weight(episode, clock_hour)


def _expected_product(
    episode: Episode,
    clock_hour: float,
    on_date: date,
    recently_aired_filenames: tuple[str, ...],
    channel_number: int,
) -> float:
    settings = load_settings({})
    return (
        _time_factor(episode, clock_hour, channel_number)
        * SeasonWeight(settings).weight(episode, on_date.month)
        * HolidayCalendar.from_defaults(settings).layer_a_multiplier(episode, on_date)
        * RecencyWeight(settings).weight(episode, recently_aired_filenames)
    )


def test_combined_weight_is_the_product_of_the_four_factors() -> None:
    recently_aired = ("LittleBear_S01E99.mp4",)
    expected = _expected_product(
        SUMMER_MORNING,
        EIGHT_IN_THE_MORNING,
        JULY_FIFTEENTH,
        recently_aired,
        LITTLE_BEAR_CHANNEL_NUMBER,
    )

    actual = _combined().weight(
        SUMMER_MORNING,
        EIGHT_IN_THE_MORNING,
        JULY_FIFTEENTH,
        recently_aired,
    )

    settings = load_settings({})
    time_factor = TimeOfDayWeight(settings).weight(SUMMER_MORNING, EIGHT_IN_THE_MORNING)
    season_factor = SeasonWeight(settings).weight(SUMMER_MORNING, JULY_FIFTEENTH.month)
    holiday_factor = HolidayCalendar.from_defaults(settings).layer_a_multiplier(
        SUMMER_MORNING, JULY_FIFTEENTH
    )
    recency_factor = RecencyWeight(settings).weight(SUMMER_MORNING, recently_aired)

    assert time_factor == 1.0
    assert season_factor == settings.in_season_weight
    assert holiday_factor == 1.0
    assert recency_factor == 1.0
    assert expected == time_factor * season_factor * holiday_factor * recency_factor
    assert actual == expected
    assert actual == 1.0


def test_combined_weight_multiplies_off_peak_wrong_season_and_holiday_downweight() -> (
    None
):
    expected = _expected_product(
        WINTER_NIGHT_CHRISTMAS,
        EIGHT_IN_THE_MORNING,
        JULY_FIFTEENTH,
        (),
        LITTLE_BEAR_CHANNEL_NUMBER,
    )

    actual = _combined().weight(
        WINTER_NIGHT_CHRISTMAS,
        EIGHT_IN_THE_MORNING,
        JULY_FIFTEENTH,
        (),
    )

    settings = load_settings({})
    time_factor = TimeOfDayWeight(settings).weight(
        WINTER_NIGHT_CHRISTMAS, EIGHT_IN_THE_MORNING
    )
    season_factor = SeasonWeight(settings).weight(
        WINTER_NIGHT_CHRISTMAS, JULY_FIFTEENTH.month
    )
    holiday_factor = HolidayCalendar.from_defaults(settings).layer_a_multiplier(
        WINTER_NIGHT_CHRISTMAS, JULY_FIFTEENTH
    )
    recency_factor = RecencyWeight(settings).weight(WINTER_NIGHT_CHRISTMAS, ())

    assert time_factor == settings.time_weight_floor
    assert season_factor == settings.wrong_season_weight
    assert holiday_factor == settings.wrong_season_weight
    assert recency_factor == 1.0
    assert actual == expected
    assert actual == (time_factor * season_factor * holiday_factor * recency_factor)


def test_blocked_recency_makes_the_product_zero() -> None:
    history = (
        "LittleBear_S01E09.mp4",
        "LittleBear_S01E10.mp4",
        GENERAL_EVERGREEN.filename,
    )
    settings = load_settings({})
    recency_factor = RecencyWeight(settings).weight(GENERAL_EVERGREEN, history)

    actual = _combined().weight(
        GENERAL_EVERGREEN,
        MIDDAY_HOUR,
        JULY_FIFTEENTH,
        history,
    )

    assert recency_factor == settings.recency_block_weight
    assert recency_factor == 0.0
    assert actual == 0.0


def test_channel_four_general_movie_at_eight_has_time_factor_one() -> None:
    settings = load_settings({})
    cartoon_time = TimeOfDayWeight(settings).weight(
        HOLIDAY_GENERAL_MOVIE, EIGHT_IN_THE_MORNING
    )
    season_factor = SeasonWeight(settings).weight(
        HOLIDAY_GENERAL_MOVIE, CHRISTMAS_DAY.month
    )
    holiday_factor = HolidayCalendar.from_defaults(settings).layer_a_multiplier(
        HOLIDAY_GENERAL_MOVIE, CHRISTMAS_DAY
    )
    recency_factor = RecencyWeight(settings).weight(HOLIDAY_GENERAL_MOVIE, ())

    actual = _combined(HOLIDAY_CHANNEL_NUMBER).weight(
        HOLIDAY_GENERAL_MOVIE,
        EIGHT_IN_THE_MORNING,
        CHRISTMAS_DAY,
        (),
    )

    assert HOLIDAY_GENERAL_MOVIE.daypart is Daypart.GENERAL
    assert cartoon_time == settings.general_off_peak_weight
    assert cartoon_time != HOLIDAY_CHANNEL_GENERAL_TIME_WEIGHT
    assert HOLIDAY_CHANNEL_GENERAL_TIME_WEIGHT == 1.0
    assert actual == (
        HOLIDAY_CHANNEL_GENERAL_TIME_WEIGHT
        * season_factor
        * holiday_factor
        * recency_factor
    )
    assert actual != cartoon_time * season_factor * holiday_factor * recency_factor


def test_channel_four_day_tag_movie_at_eight_has_time_factor_one() -> None:
    assert HOLIDAY_DAY_TAG_MOVIE.daypart is Daypart.GENERAL

    actual = _combined(HOLIDAY_CHANNEL_NUMBER).weight(
        HOLIDAY_DAY_TAG_MOVIE,
        EIGHT_IN_THE_MORNING,
        CHRISTMAS_DAY,
        (),
    )
    expected = _expected_product(
        HOLIDAY_DAY_TAG_MOVIE,
        EIGHT_IN_THE_MORNING,
        CHRISTMAS_DAY,
        (),
        HOLIDAY_CHANNEL_NUMBER,
    )

    assert actual == expected
    assert actual == _expected_product(
        HOLIDAY_GENERAL_MOVIE,
        EIGHT_IN_THE_MORNING,
        CHRISTMAS_DAY,
        (),
        HOLIDAY_CHANNEL_NUMBER,
    )


def test_channel_four_morning_movie_uses_time_of_day_weight() -> None:
    settings = load_settings({})
    time_factor = TimeOfDayWeight(settings).weight(
        HOLIDAY_MORNING_MOVIE, EIGHT_IN_THE_MORNING
    )

    actual = _combined(HOLIDAY_CHANNEL_NUMBER).weight(
        HOLIDAY_MORNING_MOVIE,
        EIGHT_IN_THE_MORNING,
        CHRISTMAS_DAY,
        (),
    )
    expected = _expected_product(
        HOLIDAY_MORNING_MOVIE,
        EIGHT_IN_THE_MORNING,
        CHRISTMAS_DAY,
        (),
        HOLIDAY_CHANNEL_NUMBER,
    )

    assert HOLIDAY_MORNING_MOVIE.daypart is Daypart.MORNING
    assert time_factor == 1.0
    assert actual == expected


def test_channel_four_night_movie_at_eight_uses_the_gaussian_floor() -> None:
    settings = load_settings({})
    time_factor = TimeOfDayWeight(settings).weight(
        HOLIDAY_NIGHT_MOVIE, EIGHT_IN_THE_MORNING
    )

    actual = _combined(HOLIDAY_CHANNEL_NUMBER).weight(
        HOLIDAY_NIGHT_MOVIE,
        EIGHT_IN_THE_MORNING,
        CHRISTMAS_DAY,
        (),
    )

    assert HOLIDAY_NIGHT_MOVIE.daypart is Daypart.NIGHT
    assert time_factor == settings.time_weight_floor
    assert actual == _expected_product(
        HOLIDAY_NIGHT_MOVIE,
        EIGHT_IN_THE_MORNING,
        CHRISTMAS_DAY,
        (),
        HOLIDAY_CHANNEL_NUMBER,
    )
    assert actual != _combined(HOLIDAY_CHANNEL_NUMBER).weight(
        HOLIDAY_GENERAL_MOVIE,
        EIGHT_IN_THE_MORNING,
        CHRISTMAS_DAY,
        (),
    )


def test_cartoon_channel_general_file_at_eight_stays_off_peak() -> None:
    settings = load_settings({})
    time_factor = TimeOfDayWeight(settings).weight(
        GENERAL_EVERGREEN, EIGHT_IN_THE_MORNING
    )

    actual = _combined(LITTLE_BEAR_CHANNEL_NUMBER).weight(
        GENERAL_EVERGREEN,
        EIGHT_IN_THE_MORNING,
        JULY_FIFTEENTH,
        (),
    )

    assert time_factor == settings.general_off_peak_weight
    assert actual == _expected_product(
        GENERAL_EVERGREEN,
        EIGHT_IN_THE_MORNING,
        JULY_FIFTEENTH,
        (),
        LITTLE_BEAR_CHANNEL_NUMBER,
    )
    assert actual != _combined(HOLIDAY_CHANNEL_NUMBER).weight(
        GENERAL_EVERGREEN,
        EIGHT_IN_THE_MORNING,
        JULY_FIFTEENTH,
        (),
    )


def test_day_tag_on_a_cartoon_channel_matches_untagged_general() -> None:
    untagged = _combined().weight(GENERAL_EVERGREEN, MIDDAY_HOUR, JULY_FIFTEENTH, ())
    day_tagged = _combined().weight(GENERAL_DAY_TAG, MIDDAY_HOUR, JULY_FIFTEENTH, ())

    assert GENERAL_DAY_TAG.daypart is Daypart.GENERAL
    assert untagged == day_tagged


def test_oswald_channel_does_not_use_the_holiday_channel_time_override() -> None:
    settings = load_settings({})
    oswald_weight = _combined(OSWALD_CHANNEL_NUMBER).weight(
        HOLIDAY_GENERAL_MOVIE,
        EIGHT_IN_THE_MORNING,
        CHRISTMAS_DAY,
        (),
    )
    holiday_channel_weight = _combined(HOLIDAY_CHANNEL_NUMBER).weight(
        HOLIDAY_GENERAL_MOVIE,
        EIGHT_IN_THE_MORNING,
        CHRISTMAS_DAY,
        (),
    )

    assert oswald_weight != holiday_channel_weight
    assert oswald_weight == _expected_product(
        HOLIDAY_GENERAL_MOVIE,
        EIGHT_IN_THE_MORNING,
        CHRISTMAS_DAY,
        (),
        OSWALD_CHANNEL_NUMBER,
    )
    assert (
        TimeOfDayWeight(settings).weight(HOLIDAY_GENERAL_MOVIE, EIGHT_IN_THE_MORNING)
        == settings.general_off_peak_weight
    )
