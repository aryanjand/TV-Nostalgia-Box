from collections.abc import Mapping
from dataclasses import FrozenInstanceError, replace
from datetime import date, timedelta

import pytest

from tv90.config import load_settings
from tv90.domain.episode import HolidayTag
from tv90.domain.filename import parse_filename
from tv90.domain.holiday_calendar import (
    DEFAULT_HOLIDAY_DEFINITIONS,
    UNTAGGED_LAYER_A_MULTIPLIER,
    HolidayCalendar,
    HolidayDefinition,
    InvalidHolidayDateError,
    InvalidHolidayOverrideError,
    UnknownHolidayError,
    holiday_enabled_environment_name,
    holiday_event_environment_name,
    load_holiday_calendar,
)
from tv90.domain.holiday_dates import canadian_thanksgiving, western_easter_sunday

HALLOWEEN_CARTOON = parse_filename("LittleBear_S01E01_HALLOWEEN.mp4")
THANKSGIVING_CARTOON = parse_filename("Oswald_S01E02_THANKSGIVING.mp4")
CHRISTMAS_CARTOON = parse_filename("Harry_S01E03_CHRISTMAS.mp4")
EASTER_CARTOON = parse_filename("LittleBear_S01E04_EASTER.mp4")
UNTAGGED_CARTOON = parse_filename("LittleBear_S01E05.mp4")
CHRISTMAS_MOVIE = parse_filename("Holiday_Rudolph_CHRISTMAS.mp4")

YEAR_2023 = 2023
YEAR_2024 = 2024
YEAR_2025 = 2025
OCTOBER = 10
DECEMBER = 12
HALLOWEEN_DAY = 31
CHRISTMAS_EVE_DAY = 24
CHRISTMAS_DAY = 25
DAY_AFTER_CHRISTMAS = 26
MIDPOINT_RAMP_FRACTION = 0.5


def _calendar(environ: Mapping[str, str] | None = None) -> HolidayCalendar:
    mapping: dict[str, str] = {} if environ is None else dict(environ)
    return load_holiday_calendar(mapping, load_settings(mapping))


def test_environment_names_match_documented_overrides() -> None:
    assert holiday_enabled_environment_name(HolidayTag.HALLOWEEN) == (
        "TV90_HOLIDAY_HALLOWEEN"
    )
    assert holiday_enabled_environment_name(HolidayTag.THANKSGIVING) == (
        "TV90_HOLIDAY_THANKSGIVING"
    )
    assert holiday_enabled_environment_name(HolidayTag.CHRISTMAS) == (
        "TV90_HOLIDAY_CHRISTMAS"
    )
    assert holiday_enabled_environment_name(HolidayTag.EASTER) == "TV90_HOLIDAY_EASTER"
    assert holiday_event_environment_name(HolidayTag.HALLOWEEN) == (
        "TV90_HOLIDAY_HALLOWEEN_EVENT"
    )
    assert holiday_event_environment_name(HolidayTag.THANKSGIVING) == (
        "TV90_HOLIDAY_THANKSGIVING_EVENT"
    )
    assert holiday_event_environment_name(HolidayTag.CHRISTMAS) == (
        "TV90_HOLIDAY_CHRISTMAS_EVENT"
    )
    assert holiday_event_environment_name(HolidayTag.EASTER) == (
        "TV90_HOLIDAY_EASTER_EVENT"
    )


def test_default_table_is_the_canadian_set_in_readme_order() -> None:
    assert tuple(definition.tag for definition in DEFAULT_HOLIDAY_DEFINITIONS) == (
        HolidayTag.HALLOWEEN,
        HolidayTag.THANKSGIVING,
        HolidayTag.CHRISTMAS,
        HolidayTag.EASTER,
    )


def test_holiday_definition_is_frozen() -> None:
    definition = DEFAULT_HOLIDAY_DEFINITIONS[0]

    with pytest.raises(FrozenInstanceError):
        setattr(definition, "enabled", False)


def test_halloween_window_opens_lead_days_before_october_thirty_first() -> None:
    settings = load_settings({})
    calendar = HolidayCalendar.from_defaults(settings)
    event_day = date(YEAR_2024, OCTOBER, HALLOWEEN_DAY)
    window_start = event_day - timedelta(days=settings.holiday_lead_days)

    assert calendar.channel_four_window(HolidayTag.HALLOWEEN, YEAR_2024) == (
        window_start,
        event_day,
    )
    assert calendar.channel_four_open(window_start)
    assert calendar.active_holiday(window_start) is HolidayTag.HALLOWEEN
    assert calendar.channel_four_open(event_day)
    assert not calendar.channel_four_open(window_start - timedelta(days=1))
    assert not calendar.channel_four_open(event_day + timedelta(days=1))


def test_thanksgiving_windows_use_second_monday_across_years() -> None:
    settings = load_settings({})
    calendar = HolidayCalendar.from_defaults(settings)
    for year in (YEAR_2023, YEAR_2024, YEAR_2025):
        event_day = canadian_thanksgiving(year)
        window_start = event_day - timedelta(days=settings.holiday_lead_days)
        assert calendar.channel_four_window(HolidayTag.THANKSGIVING, year) == (
            window_start,
            event_day,
        )
        assert calendar.active_holiday(event_day) is HolidayTag.THANKSGIVING
        assert not calendar.channel_four_open(event_day + timedelta(days=1))


def test_christmas_window_includes_eve_and_closes_end_of_christmas_day() -> None:
    settings = load_settings({})
    calendar = HolidayCalendar.from_defaults(settings)
    first_event = date(YEAR_2024, DECEMBER, CHRISTMAS_EVE_DAY)
    last_event = date(YEAR_2024, DECEMBER, CHRISTMAS_DAY)
    window_start = first_event - timedelta(days=settings.holiday_lead_days)

    assert calendar.channel_four_window(HolidayTag.CHRISTMAS, YEAR_2024) == (
        window_start,
        last_event,
    )
    assert calendar.channel_four_open(window_start)
    assert calendar.channel_four_open(first_event)
    assert calendar.channel_four_open(last_event)
    assert calendar.active_holiday(last_event) is HolidayTag.CHRISTMAS
    assert not calendar.channel_four_open(
        date(YEAR_2024, DECEMBER, DAY_AFTER_CHRISTMAS)
    )


def test_easter_windows_follow_western_sunday() -> None:
    settings = load_settings({})
    calendar = HolidayCalendar.from_defaults(settings)
    for year in (YEAR_2024, YEAR_2025, 2026):
        event_day = western_easter_sunday(year)
        window_start = event_day - timedelta(days=settings.holiday_lead_days)
        assert calendar.channel_four_window(HolidayTag.EASTER, year) == (
            window_start,
            event_day,
        )
        assert calendar.active_holiday(event_day) is HolidayTag.EASTER
        assert not calendar.channel_four_open(event_day + timedelta(days=1))


def test_lead_days_override_widens_channel_four_window() -> None:
    environ = {"TV90_HOLIDAY_LEAD_DAYS": "5"}
    settings = load_settings(environ)
    calendar = load_holiday_calendar(environ, settings)
    event_day = date(YEAR_2024, OCTOBER, HALLOWEEN_DAY)
    window_start = event_day - timedelta(days=settings.holiday_lead_days)

    assert settings.holiday_lead_days == 5
    assert calendar.channel_four_window(HolidayTag.HALLOWEEN, YEAR_2024) == (
        window_start,
        event_day,
    )
    assert calendar.channel_four_open(window_start)
    assert not calendar.channel_four_open(window_start - timedelta(days=1))


def test_disabling_halloween_closes_channel_four_and_skips_layer_a() -> None:
    settings = load_settings({})
    calendar = _calendar({"TV90_HOLIDAY_HALLOWEEN": "0"})
    event_day = date(YEAR_2024, OCTOBER, HALLOWEEN_DAY)

    assert calendar.channel_four_window(HolidayTag.HALLOWEEN, YEAR_2024) is None
    assert not calendar.channel_four_open(event_day)
    assert calendar.active_holiday(event_day) is None
    assert calendar.layer_a_multiplier(HALLOWEEN_CARTOON, event_day) == (
        settings.wrong_season_weight
    )


@pytest.mark.parametrize("raw_value", ["1", "ON", "on", "Off", "OFF", "0"])
def test_enable_tokens_are_one_zero_on_off(raw_value: str) -> None:
    calendar = _calendar({"TV90_HOLIDAY_EASTER": raw_value})
    event_day = western_easter_sunday(YEAR_2025)
    enabled = raw_value.strip().upper() in {"1", "ON"}

    assert calendar.channel_four_open(event_day) is enabled


def test_missing_enable_env_keeps_holiday_on() -> None:
    calendar = _calendar({})
    assert calendar.channel_four_open(date(YEAR_2024, OCTOBER, HALLOWEEN_DAY))


def test_halloween_event_month_day_override() -> None:
    calendar = _calendar({"TV90_HOLIDAY_HALLOWEEN_EVENT": "10-30"})
    event_day = date(YEAR_2024, OCTOBER, 30)

    assert calendar.channel_four_window(HolidayTag.HALLOWEEN, YEAR_2024) == (
        event_day - timedelta(days=load_settings({}).holiday_lead_days),
        event_day,
    )
    assert calendar.active_holiday(event_day) is HolidayTag.HALLOWEEN
    assert not calendar.channel_four_open(date(YEAR_2024, OCTOBER, HALLOWEEN_DAY))


def test_easter_iso_override_applies_that_month_day_every_year() -> None:
    calendar = _calendar({"TV90_HOLIDAY_EASTER_EVENT": "2024-04-01"})
    overridden = date(YEAR_2025, 4, 1)

    assert calendar.active_holiday(overridden) is HolidayTag.EASTER
    assert calendar.active_holiday(western_easter_sunday(YEAR_2025)) is None


def test_christmas_event_list_override() -> None:
    calendar = _calendar({"TV90_HOLIDAY_CHRISTMAS_EVENT": "12-23,12-24"})
    assert calendar.channel_four_open(date(YEAR_2024, DECEMBER, 23))
    assert calendar.channel_four_open(date(YEAR_2024, DECEMBER, 24))
    assert not calendar.channel_four_open(date(YEAR_2024, DECEMBER, CHRISTMAS_DAY))


def test_invalid_enable_value_raises() -> None:
    with pytest.raises(InvalidHolidayOverrideError) as caught:
        _calendar({"TV90_HOLIDAY_HALLOWEEN": "true"})

    assert caught.value.variable_name == "TV90_HOLIDAY_HALLOWEEN"


def test_empty_enable_value_raises() -> None:
    with pytest.raises(InvalidHolidayOverrideError) as caught:
        _calendar({"TV90_HOLIDAY_HALLOWEEN": "  "})

    assert caught.value.variable_name == "TV90_HOLIDAY_HALLOWEEN"


@pytest.mark.parametrize(
    "raw_value",
    [
        "31-10",
        "13-01",
        "potato",
        "10",
        "10-ab",
        "ab-10",
        "2024-13-01",
        "10-31-01",
        "12-24,",
        "12-24,12-24",
    ],
)
def test_invalid_event_override_raises(raw_value: str) -> None:
    with pytest.raises(InvalidHolidayOverrideError) as caught:
        _calendar({"TV90_HOLIDAY_HALLOWEEN_EVENT": raw_value})

    assert caught.value.variable_name == "TV90_HOLIDAY_HALLOWEEN_EVENT"


def test_empty_event_override_raises() -> None:
    with pytest.raises(InvalidHolidayOverrideError) as caught:
        _calendar({"TV90_HOLIDAY_CHRISTMAS_EVENT": ""})

    assert caught.value.variable_name == "TV90_HOLIDAY_CHRISTMAS_EVENT"


def test_untagged_episode_multiplier_is_one() -> None:
    calendar = HolidayCalendar.from_defaults(load_settings({}))
    event_day = date(YEAR_2024, OCTOBER, HALLOWEEN_DAY)

    assert calendar.layer_a_multiplier(UNTAGGED_CARTOON, event_day) == (
        UNTAGGED_LAYER_A_MULTIPLIER
    )


def test_layer_a_lead_start_uses_lead_multiplier() -> None:
    settings = load_settings({})
    calendar = HolidayCalendar.from_defaults(settings)
    first_event = date(YEAR_2024, OCTOBER, HALLOWEEN_DAY)
    lead_start = first_event - timedelta(days=settings.layer_a_lead_days)

    assert calendar.layer_a_multiplier(HALLOWEEN_CARTOON, lead_start) == (
        settings.layer_a_lead_multiplier
    )


def test_layer_a_event_day_uses_event_multiplier() -> None:
    settings = load_settings({})
    calendar = HolidayCalendar.from_defaults(settings)
    event_day = date(YEAR_2024, OCTOBER, HALLOWEEN_DAY)

    assert calendar.layer_a_multiplier(HALLOWEEN_CARTOON, event_day) == (
        settings.layer_a_event_multiplier
    )


def test_layer_a_christmas_plateau_covers_eve_and_day() -> None:
    settings = load_settings({})
    calendar = HolidayCalendar.from_defaults(settings)
    eve = date(YEAR_2024, DECEMBER, CHRISTMAS_EVE_DAY)
    christmas = date(YEAR_2024, DECEMBER, CHRISTMAS_DAY)

    assert calendar.layer_a_multiplier(CHRISTMAS_CARTOON, eve) == (
        settings.layer_a_event_multiplier
    )
    assert calendar.layer_a_multiplier(CHRISTMAS_CARTOON, christmas) == (
        settings.layer_a_event_multiplier
    )
    assert calendar.layer_a_multiplier(CHRISTMAS_MOVIE, christmas) == (
        settings.layer_a_event_multiplier
    )


def test_layer_a_midpoint_interpolates_linearly() -> None:
    settings = load_settings({})
    calendar = HolidayCalendar.from_defaults(settings)
    first_event = date(YEAR_2024, OCTOBER, HALLOWEEN_DAY)
    days_before = settings.layer_a_lead_days // 2
    midpoint = first_event - timedelta(days=days_before)
    expected = settings.layer_a_lead_multiplier + MIDPOINT_RAMP_FRACTION * (
        settings.layer_a_event_multiplier - settings.layer_a_lead_multiplier
    )

    assert days_before * 2 == settings.layer_a_lead_days
    assert calendar.layer_a_multiplier(HALLOWEEN_CARTOON, midpoint) == pytest.approx(
        expected
    )


def test_layer_a_outside_lead_up_is_wrong_season_for_tagged() -> None:
    settings = load_settings({})
    calendar = HolidayCalendar.from_defaults(settings)
    first_event = date(YEAR_2024, OCTOBER, HALLOWEEN_DAY)
    before_lead = first_event - timedelta(days=settings.layer_a_lead_days + 1)
    after_event = first_event + timedelta(days=1)

    assert calendar.layer_a_multiplier(HALLOWEEN_CARTOON, before_lead) == (
        settings.wrong_season_weight
    )
    assert calendar.layer_a_multiplier(HALLOWEEN_CARTOON, after_event) == (
        settings.wrong_season_weight
    )


def test_foreign_holiday_tag_does_not_ride_the_active_ramp() -> None:
    settings = load_settings({})
    calendar = HolidayCalendar.from_defaults(settings)
    halloween = date(YEAR_2024, OCTOBER, HALLOWEEN_DAY)
    thanksgiving = canadian_thanksgiving(YEAR_2024)

    # Thanksgiving's event is over by Halloween; Halloween is still 17 days
    # after Thanksgiving in 2024, so a Halloween file on Thanksgiving Monday
    # is also outside its own 14-day lead-up.
    assert calendar.layer_a_multiplier(THANKSGIVING_CARTOON, halloween) == (
        settings.wrong_season_weight
    )
    assert calendar.layer_a_multiplier(HALLOWEEN_CARTOON, thanksgiving) == (
        settings.wrong_season_weight
    )
    assert calendar.layer_a_multiplier(THANKSGIVING_CARTOON, thanksgiving) == (
        settings.layer_a_event_multiplier
    )


def test_channel_four_stays_closed_during_layer_a_only_lead_up() -> None:
    settings = load_settings({})
    calendar = HolidayCalendar.from_defaults(settings)
    first_event = date(YEAR_2024, DECEMBER, CHRISTMAS_EVE_DAY)
    layer_a_start = first_event - timedelta(days=settings.layer_a_lead_days)
    channel_four_start = first_event - timedelta(days=settings.holiday_lead_days)

    assert calendar.layer_a_multiplier(CHRISTMAS_CARTOON, layer_a_start) == (
        settings.layer_a_lead_multiplier
    )
    assert not calendar.channel_four_open(layer_a_start)
    assert calendar.channel_four_open(channel_four_start)


def test_overlapping_windows_prefer_sooner_first_event() -> None:
    # Constructed table: both CH 04 windows contain Oct 17. Thanksgiving's
    # first event is earlier, so it wins even though Halloween is first in
    # the default Canadian table.
    settings = load_settings({})
    definitions = (
        HolidayDefinition(
            tag=HolidayTag.HALLOWEEN,
            event_days_for_year=lambda year: (date(year, OCTOBER, 20),),
            enabled=True,
        ),
        HolidayDefinition(
            tag=HolidayTag.THANKSGIVING,
            event_days_for_year=lambda year: (date(year, OCTOBER, 18),),
            enabled=True,
        ),
    )
    calendar = HolidayCalendar(settings, definitions)
    overlap = date(YEAR_2024, OCTOBER, 17)
    after_thanksgiving = date(YEAR_2024, OCTOBER, 19)

    assert calendar.channel_four_open(overlap)
    assert calendar.active_holiday(overlap) is HolidayTag.THANKSGIVING
    assert calendar.active_holiday(after_thanksgiving) is HolidayTag.HALLOWEEN


def test_overlap_with_equal_first_event_uses_tag_name_order() -> None:
    settings = load_settings({})
    definitions = (
        HolidayDefinition(
            tag=HolidayTag.THANKSGIVING,
            event_days_for_year=lambda year: (date(year, OCTOBER, 20),),
            enabled=True,
        ),
        HolidayDefinition(
            tag=HolidayTag.HALLOWEEN,
            event_days_for_year=lambda year: (date(year, OCTOBER, 20),),
            enabled=True,
        ),
    )
    calendar = HolidayCalendar(settings, definitions)

    assert calendar.active_holiday(date(YEAR_2024, OCTOBER, 20)) is HolidayTag.HALLOWEEN


def test_zero_layer_a_lead_days_boosts_only_event_days() -> None:
    settings = replace(load_settings({}), layer_a_lead_days=0)
    calendar = HolidayCalendar.from_defaults(settings)
    event_day = date(YEAR_2024, OCTOBER, HALLOWEEN_DAY)

    assert calendar.layer_a_multiplier(HALLOWEEN_CARTOON, event_day) == (
        settings.layer_a_event_multiplier
    )
    assert calendar.layer_a_multiplier(
        HALLOWEEN_CARTOON, event_day - timedelta(days=1)
    ) == (settings.wrong_season_weight)


def test_empty_event_days_raise() -> None:
    calendar = HolidayCalendar(
        load_settings({}),
        (
            HolidayDefinition(
                tag=HolidayTag.HALLOWEEN,
                event_days_for_year=lambda year: (),
                enabled=True,
            ),
        ),
    )

    with pytest.raises(InvalidHolidayDateError) as caught:
        calendar.channel_four_window(HolidayTag.HALLOWEEN, YEAR_2024)
    assert caught.value.year == YEAR_2024


def test_unknown_holiday_raises_for_window_query() -> None:
    calendar = HolidayCalendar(
        load_settings({}),
        (
            HolidayDefinition(
                tag=HolidayTag.HALLOWEEN,
                event_days_for_year=lambda year: (date(year, OCTOBER, HALLOWEEN_DAY),),
                enabled=True,
            ),
        ),
    )

    with pytest.raises(UnknownHolidayError) as caught:
        calendar.channel_four_window(HolidayTag.EASTER, YEAR_2024)
    assert caught.value.holiday is HolidayTag.EASTER

    with pytest.raises(UnknownHolidayError):
        calendar.layer_a_multiplier(EASTER_CARTOON, date(YEAR_2024, 4, 1))


def test_february_twenty_nine_override_fails_in_common_year() -> None:
    calendar = _calendar({"TV90_HOLIDAY_EASTER_EVENT": "02-29"})

    with pytest.raises(InvalidHolidayDateError):
        calendar.channel_four_window(HolidayTag.EASTER, YEAR_2023)
    assert calendar.channel_four_window(HolidayTag.EASTER, YEAR_2024) == (
        date(YEAR_2024, 2, 29) - timedelta(days=load_settings({}).holiday_lead_days),
        date(YEAR_2024, 2, 29),
    )


def test_layer_a_uses_settings_multipliers_not_literals() -> None:
    settings = replace(
        load_settings({}),
        layer_a_lead_multiplier=1.1,
        layer_a_event_multiplier=1.4,
        layer_a_lead_days=10,
        wrong_season_weight=0.02,
    )
    calendar = HolidayCalendar.from_defaults(settings)
    first_event = date(YEAR_2024, OCTOBER, HALLOWEEN_DAY)
    lead_start = first_event - timedelta(days=settings.layer_a_lead_days)

    assert calendar.layer_a_multiplier(HALLOWEEN_CARTOON, lead_start) == (
        settings.layer_a_lead_multiplier
    )
    assert calendar.layer_a_multiplier(HALLOWEEN_CARTOON, first_event) == (
        settings.layer_a_event_multiplier
    )
    assert calendar.layer_a_multiplier(
        HALLOWEEN_CARTOON, lead_start - timedelta(days=1)
    ) == (settings.wrong_season_weight)


def test_easter_layer_a_fourteen_days_out() -> None:
    settings = load_settings({})
    calendar = HolidayCalendar.from_defaults(settings)
    first_event = western_easter_sunday(YEAR_2024)
    lead_start = first_event - timedelta(days=settings.layer_a_lead_days)

    assert calendar.layer_a_multiplier(EASTER_CARTOON, lead_start) == (
        settings.layer_a_lead_multiplier
    )


def test_active_holiday_none_on_an_ordinary_july_day() -> None:
    calendar = HolidayCalendar.from_defaults(load_settings({}))

    assert calendar.active_holiday(date(YEAR_2024, 7, 15)) is None
    assert not calendar.channel_four_open(date(YEAR_2024, 7, 15))


def test_invalid_year_for_event_day_raises() -> None:
    calendar = HolidayCalendar.from_defaults(load_settings({}))

    with pytest.raises(InvalidHolidayDateError) as caught:
        calendar.channel_four_window(HolidayTag.HALLOWEEN, 0)
    assert caught.value.year == 0


def test_layer_a_and_windows_at_calendar_year_bounds() -> None:
    settings = load_settings({})
    calendar = HolidayCalendar.from_defaults(settings)
    earliest = date(date.min.year, OCTOBER, HALLOWEEN_DAY)
    latest = date(date.max.year, OCTOBER, HALLOWEEN_DAY)

    assert calendar.layer_a_multiplier(HALLOWEEN_CARTOON, earliest) == (
        settings.layer_a_event_multiplier
    )
    assert calendar.layer_a_multiplier(HALLOWEEN_CARTOON, latest) == (
        settings.layer_a_event_multiplier
    )
    assert calendar.channel_four_open(earliest)
    assert calendar.channel_four_open(latest)
