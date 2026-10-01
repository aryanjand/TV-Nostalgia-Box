"""Named broadcast settings and environment overrides.

`load_settings` reads an injected mapping so tests never touch os.environ.
The composition root (T15) will pass the real environment later.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

# Environment names. The TV90_ prefix keeps household overrides off the OS namespace.
TIMEZONE_ENVIRONMENT_NAME = "TV90_TIMEZONE"
CLOCK_TRUST_TIMEOUT_ENVIRONMENT_NAME = "TV90_CLOCK_TRUST_TIMEOUT_SECONDS"
HOLIDAY_LEAD_DAYS_ENVIRONMENT_NAME = "TV90_HOLIDAY_LEAD_DAYS"
SIGN_ON_ENVIRONMENT_NAME = "TV90_SIGN_ON"
NIGHT_LOCK_ENVIRONMENT_NAME = "TV90_NIGHT_LOCK"
LIBRARY_PATH_ENVIRONMENT_NAME = "TV90_LIBRARY_PATH"
DEFAULT_LIBRARY_PATH = Path("/srv/90stv/library")

DEFAULT_TIMEZONE_NAME = "America/Vancouver"
DEFAULT_CLOCK_TRUST_TIMEOUT_SECONDS = 180
DEFAULT_HOLIDAY_LEAD_DAYS = 3

SIGN_ON_HOUR = 6.5
NIGHT_LOCK_HOUR = 21.0
MINIMUM_CLOCK_HOUR = 0.0
MAXIMUM_CLOCK_HOUR = 24.0
MINIMUM_NON_NEGATIVE_VALUE = 0

MORNING_GAUSSIAN_MEAN = 8.0
MORNING_GAUSSIAN_STANDARD_DEVIATION = 2.0
NIGHT_GAUSSIAN_MEAN = 20.0
NIGHT_GAUSSIAN_STANDARD_DEVIATION = 1.5
TIME_WEIGHT_FLOOR = 0.05

GENERAL_MIDDAY_START_HOUR = 10.0
GENERAL_MIDDAY_END_HOUR = 17.0
GENERAL_MIDDAY_WEIGHT = 1.0
GENERAL_OFF_PEAK_WEIGHT = 0.35

RECENCY_BLOCK_COUNT = 3
RECENCY_BLOCK_WEIGHT = 0.0
RECENCY_PENALTY_COUNT = 10
RECENCY_PENALTY_WEIGHT = 0.15

OSD_BANNER_SECONDS = 3.0
OSD_COLOR = "#00FF00"
# Muted sage field for the fail-soft / off-air slate. Not neon OSD green.
CALM_SLATE_COLOR = "#3A4A42"
TUNER_BURST_MILLISECONDS = 150
COMMAND_COOLDOWN_MILLISECONDS = 500
VOLUME_CEILING = 0.65
VOLUME_DEFAULT = 0.40
EPISODE_JOIN_FADE_SECONDS = 1.5

LAYER_A_LEAD_DAYS = 14
LAYER_A_LEAD_MULTIPLIER = 1.25
LAYER_A_EVENT_MULTIPLIER = 1.50

IN_SEASON_WEIGHT = 1.0
EVERGREEN_SEASON_WEIGHT = 0.20
WRONG_SEASON_WEIGHT = 0.05

LITTLE_BEAR_SHOW_STEM = "LittleBear"
OSWALD_SHOW_STEM = "Oswald"
HARRY_SHOW_STEM = "Harry"
HOLIDAY_SHOW_STEM = "Holiday"

LITTLE_BEAR_CHANNEL_NUMBER = 1
OSWALD_CHANNEL_NUMBER = 2
HARRY_CHANNEL_NUMBER = 3
HOLIDAY_CHANNEL_NUMBER = 4

SPRING_MONTHS = (3, 4, 5)
SUMMER_MONTHS = (6, 7, 8)
AUTUMN_MONTHS = (9, 10, 11)
WINTER_MONTHS = (12, 1, 2)


class InvalidSettingsError(Exception):
    """An environment override cannot be parsed or is out of range."""

    def __init__(self, variable_name: str, reason: str) -> None:
        self.variable_name = variable_name
        self.reason = reason
        super().__init__(f"{variable_name}: {reason}")


@dataclass(frozen=True)
class Settings:
    timezone: ZoneInfo
    clock_trust_timeout_seconds: int
    holiday_lead_days: int
    sign_on_hour: float
    night_lock_hour: float
    morning_gaussian_mean: float
    morning_gaussian_standard_deviation: float
    night_gaussian_mean: float
    night_gaussian_standard_deviation: float
    time_weight_floor: float
    general_midday_start_hour: float
    general_midday_end_hour: float
    general_midday_weight: float
    general_off_peak_weight: float
    recency_block_count: int
    recency_block_weight: float
    recency_penalty_count: int
    recency_penalty_weight: float
    osd_banner_seconds: float
    osd_color: str
    tuner_burst_milliseconds: int
    command_cooldown_milliseconds: int
    volume_ceiling: float
    volume_default: float
    episode_join_fade_seconds: float
    layer_a_lead_days: int
    layer_a_lead_multiplier: float
    layer_a_event_multiplier: float
    in_season_weight: float
    evergreen_season_weight: float
    wrong_season_weight: float


def load_library_path(environ: Mapping[str, str]) -> Path:
    """Library mount. Missing or blank TV90_LIBRARY_PATH keeps the Pi default."""
    raw_value = _optional_stripped(environ, LIBRARY_PATH_ENVIRONMENT_NAME)
    if raw_value is None or raw_value == "":
        return DEFAULT_LIBRARY_PATH
    return Path(raw_value)


def load_settings(environ: Mapping[str, str]) -> Settings:
    sign_on_hour = _load_clock_hour(environ, SIGN_ON_ENVIRONMENT_NAME, SIGN_ON_HOUR)
    night_lock_hour = _load_clock_hour(
        environ, NIGHT_LOCK_ENVIRONMENT_NAME, NIGHT_LOCK_HOUR
    )
    _require_night_lock_after_sign_on(sign_on_hour, night_lock_hour)
    return Settings(
        timezone=_load_timezone(environ),
        clock_trust_timeout_seconds=_load_clock_trust_timeout_seconds(environ),
        holiday_lead_days=_load_holiday_lead_days(environ),
        sign_on_hour=sign_on_hour,
        night_lock_hour=night_lock_hour,
        morning_gaussian_mean=MORNING_GAUSSIAN_MEAN,
        morning_gaussian_standard_deviation=MORNING_GAUSSIAN_STANDARD_DEVIATION,
        night_gaussian_mean=NIGHT_GAUSSIAN_MEAN,
        night_gaussian_standard_deviation=NIGHT_GAUSSIAN_STANDARD_DEVIATION,
        time_weight_floor=TIME_WEIGHT_FLOOR,
        general_midday_start_hour=GENERAL_MIDDAY_START_HOUR,
        general_midday_end_hour=GENERAL_MIDDAY_END_HOUR,
        general_midday_weight=GENERAL_MIDDAY_WEIGHT,
        general_off_peak_weight=GENERAL_OFF_PEAK_WEIGHT,
        recency_block_count=RECENCY_BLOCK_COUNT,
        recency_block_weight=RECENCY_BLOCK_WEIGHT,
        recency_penalty_count=RECENCY_PENALTY_COUNT,
        recency_penalty_weight=RECENCY_PENALTY_WEIGHT,
        osd_banner_seconds=OSD_BANNER_SECONDS,
        osd_color=OSD_COLOR,
        tuner_burst_milliseconds=TUNER_BURST_MILLISECONDS,
        command_cooldown_milliseconds=COMMAND_COOLDOWN_MILLISECONDS,
        volume_ceiling=VOLUME_CEILING,
        volume_default=VOLUME_DEFAULT,
        episode_join_fade_seconds=EPISODE_JOIN_FADE_SECONDS,
        layer_a_lead_days=LAYER_A_LEAD_DAYS,
        layer_a_lead_multiplier=LAYER_A_LEAD_MULTIPLIER,
        layer_a_event_multiplier=LAYER_A_EVENT_MULTIPLIER,
        in_season_weight=IN_SEASON_WEIGHT,
        evergreen_season_weight=EVERGREEN_SEASON_WEIGHT,
        wrong_season_weight=WRONG_SEASON_WEIGHT,
    )


def _optional_stripped(environ: Mapping[str, str], variable_name: str) -> str | None:
    if variable_name not in environ:
        return None
    return environ[variable_name].strip()


def _load_timezone(environ: Mapping[str, str]) -> ZoneInfo:
    raw_value = _optional_stripped(environ, TIMEZONE_ENVIRONMENT_NAME)
    if raw_value is None:
        return ZoneInfo(DEFAULT_TIMEZONE_NAME)
    if raw_value == "":
        raise InvalidSettingsError(TIMEZONE_ENVIRONMENT_NAME, "must not be empty")
    try:
        return ZoneInfo(raw_value)
    except ZoneInfoNotFoundError as error:
        raise InvalidSettingsError(
            TIMEZONE_ENVIRONMENT_NAME, "must be a valid IANA time zone"
        ) from error


def _load_clock_trust_timeout_seconds(environ: Mapping[str, str]) -> int:
    timeout_seconds = _load_integer(
        environ,
        CLOCK_TRUST_TIMEOUT_ENVIRONMENT_NAME,
        DEFAULT_CLOCK_TRUST_TIMEOUT_SECONDS,
    )
    if timeout_seconds < MINIMUM_NON_NEGATIVE_VALUE:
        raise InvalidSettingsError(
            CLOCK_TRUST_TIMEOUT_ENVIRONMENT_NAME, "must not be negative"
        )
    return timeout_seconds


def _load_holiday_lead_days(environ: Mapping[str, str]) -> int:
    holiday_lead_days = _load_integer(
        environ,
        HOLIDAY_LEAD_DAYS_ENVIRONMENT_NAME,
        DEFAULT_HOLIDAY_LEAD_DAYS,
    )
    if holiday_lead_days < MINIMUM_NON_NEGATIVE_VALUE:
        raise InvalidSettingsError(
            HOLIDAY_LEAD_DAYS_ENVIRONMENT_NAME, "must not be negative"
        )
    return holiday_lead_days


def _load_clock_hour(
    environ: Mapping[str, str], variable_name: str, default: float
) -> float:
    clock_hour = _load_finite_number(environ, variable_name, default)
    if clock_hour < MINIMUM_CLOCK_HOUR or clock_hour > MAXIMUM_CLOCK_HOUR:
        raise InvalidSettingsError(
            variable_name,
            (
                "must be a decimal hour between "
                f"{MINIMUM_CLOCK_HOUR} and {MAXIMUM_CLOCK_HOUR}"
            ),
        )
    return clock_hour


def _require_night_lock_after_sign_on(
    sign_on_hour: float, night_lock_hour: float
) -> None:
    if night_lock_hour <= sign_on_hour:
        raise InvalidSettingsError(NIGHT_LOCK_ENVIRONMENT_NAME, "must be after sign-on")


def _load_integer(environ: Mapping[str, str], variable_name: str, default: int) -> int:
    raw_value = _optional_stripped(environ, variable_name)
    if raw_value is None:
        return default
    try:
        return int(raw_value)
    except ValueError as error:
        raise InvalidSettingsError(variable_name, "must be an integer") from error


def _load_finite_number(
    environ: Mapping[str, str], variable_name: str, default: float
) -> float:
    raw_value = _optional_stripped(environ, variable_name)
    if raw_value is None:
        return default
    try:
        parsed = float(raw_value)
    except ValueError as error:
        raise InvalidSettingsError(variable_name, "must be a number") from error
    if not math.isfinite(parsed):
        raise InvalidSettingsError(variable_name, "must be a finite number")
    return parsed
