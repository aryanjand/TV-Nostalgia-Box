from dataclasses import FrozenInstanceError
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from tv90.config import (
    AUTUMN_MONTHS,
    HARRY_CHANNEL_NUMBER,
    HARRY_SHOW_STEM,
    HOLIDAY_CHANNEL_NUMBER,
    HOLIDAY_SHOW_STEM,
    LITTLE_BEAR_CHANNEL_NUMBER,
    LITTLE_BEAR_SHOW_STEM,
    OSWALD_CHANNEL_NUMBER,
    OSWALD_SHOW_STEM,
    SPRING_MONTHS,
    SUMMER_MONTHS,
    WINTER_MONTHS,
    InvalidSettingsError,
    load_library_path,
    load_settings,
)


def test_load_settings_with_empty_environ_uses_documented_defaults() -> None:
    settings = load_settings({})

    assert settings.timezone == ZoneInfo("America/Vancouver")
    assert settings.clock_trust_timeout_seconds == 180
    assert settings.holiday_lead_days == 3
    assert settings.sign_on_hour == 6.5
    assert settings.night_lock_hour == 21.0
    assert settings.morning_gaussian_mean == 8.0
    assert settings.morning_gaussian_standard_deviation == 2.0
    assert settings.night_gaussian_mean == 20.0
    assert settings.night_gaussian_standard_deviation == 1.5
    assert settings.time_weight_floor == 0.05
    assert settings.general_midday_start_hour == 10.0
    assert settings.general_midday_end_hour == 17.0
    assert settings.general_midday_weight == 1.0
    assert settings.general_off_peak_weight == 0.35
    assert settings.recency_block_count == 3
    assert settings.recency_block_weight == 0.0
    assert settings.recency_penalty_count == 10
    assert settings.recency_penalty_weight == 0.15
    assert settings.osd_banner_seconds == 3.0
    assert settings.osd_color == "#00FF00"
    assert settings.tuner_burst_milliseconds == 150
    assert settings.command_cooldown_milliseconds == 500
    assert settings.volume_ceiling == 0.65
    assert settings.volume_default == 0.40
    assert settings.episode_join_fade_seconds == 1.5
    assert settings.layer_a_lead_days == 14
    assert settings.layer_a_lead_multiplier == 1.25
    assert settings.layer_a_event_multiplier == 1.50
    assert settings.in_season_weight == 1.0
    assert settings.evergreen_season_weight == 0.20
    assert settings.wrong_season_weight == 0.05


def test_assigning_a_settings_field_raises() -> None:
    settings = load_settings({})

    with pytest.raises(FrozenInstanceError):
        setattr(settings, "sign_on_hour", 7.0)


def test_load_settings_overrides_timezone() -> None:
    settings = load_settings({"TV90_TIMEZONE": "America/Toronto"})

    assert settings.timezone == ZoneInfo("America/Toronto")


def test_load_settings_overrides_clock_trust_timeout() -> None:
    settings = load_settings({"TV90_CLOCK_TRUST_TIMEOUT_SECONDS": "90"})

    assert settings.clock_trust_timeout_seconds == 90


def test_load_settings_overrides_holiday_lead_days() -> None:
    settings = load_settings({"TV90_HOLIDAY_LEAD_DAYS": "5"})

    assert settings.holiday_lead_days == 5


def test_load_settings_overrides_sign_on() -> None:
    settings = load_settings({"TV90_SIGN_ON": "7.25"})

    assert settings.sign_on_hour == 7.25


def test_load_settings_overrides_night_lock() -> None:
    settings = load_settings({"TV90_NIGHT_LOCK": "20.5"})

    assert settings.night_lock_hour == 20.5


def test_load_settings_rejects_empty_timezone() -> None:
    with pytest.raises(InvalidSettingsError) as caught:
        load_settings({"TV90_TIMEZONE": ""})

    assert caught.value.variable_name == "TV90_TIMEZONE"


def test_load_settings_rejects_unknown_timezone() -> None:
    with pytest.raises(InvalidSettingsError) as caught:
        load_settings({"TV90_TIMEZONE": "Not/AZone"})

    assert caught.value.variable_name == "TV90_TIMEZONE"


def test_load_settings_rejects_non_numeric_trust_timeout() -> None:
    with pytest.raises(InvalidSettingsError) as caught:
        load_settings({"TV90_CLOCK_TRUST_TIMEOUT_SECONDS": "soon"})

    assert caught.value.variable_name == "TV90_CLOCK_TRUST_TIMEOUT_SECONDS"


def test_load_settings_rejects_negative_trust_timeout() -> None:
    with pytest.raises(InvalidSettingsError) as caught:
        load_settings({"TV90_CLOCK_TRUST_TIMEOUT_SECONDS": "-1"})

    assert caught.value.variable_name == "TV90_CLOCK_TRUST_TIMEOUT_SECONDS"


def test_load_settings_rejects_negative_holiday_lead_days() -> None:
    with pytest.raises(InvalidSettingsError) as caught:
        load_settings({"TV90_HOLIDAY_LEAD_DAYS": "-1"})

    assert caught.value.variable_name == "TV90_HOLIDAY_LEAD_DAYS"


def test_load_settings_rejects_non_numeric_holiday_lead_days() -> None:
    with pytest.raises(InvalidSettingsError) as caught:
        load_settings({"TV90_HOLIDAY_LEAD_DAYS": "three"})

    assert caught.value.variable_name == "TV90_HOLIDAY_LEAD_DAYS"


def test_load_settings_rejects_night_lock_before_sign_on() -> None:
    with pytest.raises(InvalidSettingsError) as caught:
        load_settings({"TV90_SIGN_ON": "10", "TV90_NIGHT_LOCK": "9"})

    assert caught.value.variable_name == "TV90_NIGHT_LOCK"


def test_load_settings_rejects_night_lock_equal_to_sign_on() -> None:
    with pytest.raises(InvalidSettingsError) as caught:
        load_settings({"TV90_SIGN_ON": "12", "TV90_NIGHT_LOCK": "12"})

    assert caught.value.variable_name == "TV90_NIGHT_LOCK"


def test_load_settings_rejects_non_numeric_sign_on() -> None:
    with pytest.raises(InvalidSettingsError) as caught:
        load_settings({"TV90_SIGN_ON": "morning"})

    assert caught.value.variable_name == "TV90_SIGN_ON"


def test_load_settings_rejects_non_numeric_night_lock() -> None:
    with pytest.raises(InvalidSettingsError) as caught:
        load_settings({"TV90_NIGHT_LOCK": "bedtime"})

    assert caught.value.variable_name == "TV90_NIGHT_LOCK"


def test_load_settings_rejects_non_finite_sign_on() -> None:
    with pytest.raises(InvalidSettingsError) as caught:
        load_settings({"TV90_SIGN_ON": "inf"})

    assert caught.value.variable_name == "TV90_SIGN_ON"


def test_load_settings_rejects_sign_on_outside_day() -> None:
    with pytest.raises(InvalidSettingsError) as caught:
        load_settings({"TV90_SIGN_ON": "25"})

    assert caught.value.variable_name == "TV90_SIGN_ON"


def test_load_settings_rejects_night_lock_outside_day() -> None:
    with pytest.raises(InvalidSettingsError) as caught:
        load_settings({"TV90_NIGHT_LOCK": "-0.5"})

    assert caught.value.variable_name == "TV90_NIGHT_LOCK"


def test_show_stems_match_filename_scheme() -> None:
    assert LITTLE_BEAR_SHOW_STEM == "LittleBear"
    assert OSWALD_SHOW_STEM == "Oswald"
    assert HARRY_SHOW_STEM == "Harry"
    assert HOLIDAY_SHOW_STEM == "Holiday"


def test_channel_numbers_are_one_through_four() -> None:
    assert LITTLE_BEAR_CHANNEL_NUMBER == 1
    assert OSWALD_CHANNEL_NUMBER == 2
    assert HARRY_CHANNEL_NUMBER == 3
    assert HOLIDAY_CHANNEL_NUMBER == 4


def test_season_month_ranges_are_meteorological() -> None:
    assert SPRING_MONTHS == (3, 4, 5)
    assert SUMMER_MONTHS == (6, 7, 8)
    assert AUTUMN_MONTHS == (9, 10, 11)
    assert WINTER_MONTHS == (12, 1, 2)


def test_load_library_path_defaults_to_srv_mount() -> None:
    assert load_library_path({}) == Path("/srv/90stv/library")


def test_load_library_path_treats_blank_as_default() -> None:
    assert load_library_path({"TV90_LIBRARY_PATH": "  "}) == Path("/srv/90stv/library")


def test_load_library_path_uses_override() -> None:
    assert load_library_path({"TV90_LIBRARY_PATH": "/mnt/cartoons"}) == Path(
        "/mnt/cartoons"
    )
