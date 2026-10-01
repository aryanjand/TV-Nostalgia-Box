"""Holiday table, CH 04 windows, and Layer A multipliers. No I/O."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, replace
from datetime import date, timedelta

from tv90.config import Settings
from tv90.domain.episode import Episode, HolidayTag
from tv90.domain.holiday_dates import (
    canadian_thanksgiving,
    christmas_event_days,
    halloween,
    western_easter_sunday,
)

UNTAGGED_LAYER_A_MULTIPLIER = 1.0
HOLIDAY_ENVIRONMENT_PREFIX = "TV90_HOLIDAY_"
HOLIDAY_EVENT_ENVIRONMENT_SUFFIX = "_EVENT"
ENABLED_OVERRIDE_TOKENS = frozenset({"1", "ON"})
DISABLED_OVERRIDE_TOKENS = frozenset({"0", "OFF"})
EVENT_DAY_LIST_SEPARATOR = ","
DATE_PART_SEPARATOR = "-"
ISO_DATE_PART_COUNT = 3
MONTH_DAY_PART_COUNT = 2
# 2000 is a Gregorian leap year, so month-day validation can accept Feb 29.
LEAP_YEAR_FOR_MONTH_DAY_VALIDATION = 2000


class InvalidHolidayOverrideError(Exception):
    """An environment override for the holiday table cannot be parsed."""

    def __init__(self, variable_name: str, reason: str) -> None:
        self.variable_name = variable_name
        self.reason = reason
        super().__init__(f"{variable_name}: {reason}")


class InvalidHolidayDateError(Exception):
    """Event days for a year are empty or not a real calendar date."""

    def __init__(self, year: int, reason: str) -> None:
        self.year = year
        self.reason = reason
        super().__init__(reason)


class UnknownHolidayError(Exception):
    """The calendar has no definition for this holiday tag."""

    def __init__(self, holiday: HolidayTag) -> None:
        self.holiday = holiday
        super().__init__(f"no holiday definition for {holiday.name}")


@dataclass(frozen=True)
class HolidayDefinition:
    tag: HolidayTag
    event_days_for_year: Callable[[int], tuple[date, ...]]
    enabled: bool = True


def holiday_enabled_environment_name(tag: HolidayTag) -> str:
    return f"{HOLIDAY_ENVIRONMENT_PREFIX}{tag.name}"


def holiday_event_environment_name(tag: HolidayTag) -> str:
    return f"{HOLIDAY_ENVIRONMENT_PREFIX}{tag.name}{HOLIDAY_EVENT_ENVIRONMENT_SUFFIX}"


def _event_days_from_single_date(
    event_date_for_year: Callable[[int], date],
) -> Callable[[int], tuple[date, ...]]:
    def event_days_for_year(year: int) -> tuple[date, ...]:
        return (event_date_for_year(year),)

    return event_days_for_year


DEFAULT_HOLIDAY_DEFINITIONS: tuple[HolidayDefinition, ...] = (
    HolidayDefinition(
        tag=HolidayTag.HALLOWEEN,
        event_days_for_year=_event_days_from_single_date(halloween),
    ),
    HolidayDefinition(
        tag=HolidayTag.THANKSGIVING,
        event_days_for_year=_event_days_from_single_date(canadian_thanksgiving),
    ),
    HolidayDefinition(
        tag=HolidayTag.CHRISTMAS,
        event_days_for_year=christmas_event_days,
    ),
    HolidayDefinition(
        tag=HolidayTag.EASTER,
        event_days_for_year=_event_days_from_single_date(western_easter_sunday),
    ),
)


def load_holiday_calendar(
    environ: Mapping[str, str], settings: Settings
) -> HolidayCalendar:
    resolved = tuple(
        replace(
            definition,
            enabled=_enabled_with_override(environ, definition.tag),
            event_days_for_year=_event_days_with_override(environ, definition),
        )
        for definition in DEFAULT_HOLIDAY_DEFINITIONS
    )
    return HolidayCalendar(settings, resolved)


class HolidayCalendar:
    def __init__(
        self, settings: Settings, definitions: tuple[HolidayDefinition, ...]
    ) -> None:
        self._settings = settings
        self._definitions = definitions
        self._by_tag = {definition.tag: definition for definition in definitions}

    @classmethod
    def from_defaults(cls, settings: Settings) -> HolidayCalendar:
        return cls(settings, DEFAULT_HOLIDAY_DEFINITIONS)

    def channel_four_open(self, on_date: date) -> bool:
        return self.active_holiday(on_date) is not None

    def active_holiday(self, on_date: date) -> HolidayTag | None:
        candidates: list[tuple[date, str, HolidayTag]] = []
        for definition in self._definitions:
            if not definition.enabled:
                continue
            occurrence = self._channel_four_occurrence(definition, on_date)
            if occurrence is None:
                continue
            first_event, _last_event = occurrence
            # Sooner first event day wins; tag name breaks ties so table order
            # cannot change which movie marathon CH 04 is running.
            candidates.append((first_event, definition.tag.name, definition.tag))
        if not candidates:
            return None
        _first_event, _name, holiday = min(candidates)
        return holiday

    def layer_a_multiplier(self, episode: Episode, on_date: date) -> float:
        holiday_tag = episode.holiday_tag
        if holiday_tag is None:
            return UNTAGGED_LAYER_A_MULTIPLIER
        definition = self._definition(holiday_tag)
        if not definition.enabled:
            return self._settings.wrong_season_weight
        occurrence = self._layer_a_occurrence(definition, on_date)
        if occurrence is None:
            return self._settings.wrong_season_weight
        first_event, last_event = occurrence
        return self._ramp(on_date, first_event, last_event)

    def channel_four_window(
        self, holiday: HolidayTag, year: int
    ) -> tuple[date, date] | None:
        definition = self._definition(holiday)
        if not definition.enabled:
            return None
        first_event, last_event = self._event_span(definition, year)
        window_start = first_event - timedelta(days=self._settings.holiday_lead_days)
        return window_start, last_event

    def _definition(self, holiday: HolidayTag) -> HolidayDefinition:
        try:
            return self._by_tag[holiday]
        except KeyError as error:
            raise UnknownHolidayError(holiday) from error

    def _event_span(
        self, definition: HolidayDefinition, year: int
    ) -> tuple[date, date]:
        try:
            event_days = definition.event_days_for_year(year)
        except ValueError as error:
            raise InvalidHolidayDateError(
                year, "event day is not a valid calendar date"
            ) from error
        if not event_days:
            raise InvalidHolidayDateError(
                year, "holiday must have at least one event day"
            )
        return min(event_days), max(event_days)

    def _channel_four_occurrence(
        self, definition: HolidayDefinition, on_date: date
    ) -> tuple[date, date] | None:
        lead_days = self._settings.holiday_lead_days
        matches: list[tuple[date, date]] = []
        for year in _years_around(on_date.year):
            first_event, last_event = self._event_span(definition, year)
            window_start = first_event - timedelta(days=lead_days)
            if window_start <= on_date <= last_event:
                matches.append((first_event, last_event))
        if not matches:
            return None
        return min(matches, key=lambda span: span[0])

    def _layer_a_occurrence(
        self, definition: HolidayDefinition, on_date: date
    ) -> tuple[date, date] | None:
        lead_days = self._settings.layer_a_lead_days
        matches: list[tuple[date, date]] = []
        for year in _years_around(on_date.year):
            first_event, last_event = self._event_span(definition, year)
            ramp_start = first_event - timedelta(days=lead_days)
            if ramp_start <= on_date <= last_event:
                matches.append((first_event, last_event))
        if not matches:
            return None
        return min(matches, key=lambda span: span[0])

    def _ramp(self, on_date: date, first_event: date, last_event: date) -> float:
        settings = self._settings
        if first_event <= on_date <= last_event:
            return settings.layer_a_event_multiplier
        days_until_first = (first_event - on_date).days
        # Endpoints return Settings values exactly so 14 days out cannot
        # drift off 1.25 via float interpolation.
        if days_until_first == settings.layer_a_lead_days:
            return settings.layer_a_lead_multiplier
        lead_days = settings.layer_a_lead_days
        progress = (lead_days - days_until_first) / lead_days
        return settings.layer_a_lead_multiplier + progress * (
            settings.layer_a_event_multiplier - settings.layer_a_lead_multiplier
        )


def _years_around(year: int) -> tuple[int, ...]:
    years = [year]
    previous_year = year - 1
    next_year = year + 1
    if previous_year >= date.min.year:
        years.append(previous_year)
    if next_year <= date.max.year:
        years.append(next_year)
    return tuple(years)


def _enabled_with_override(environ: Mapping[str, str], tag: HolidayTag) -> bool:
    variable_name = holiday_enabled_environment_name(tag)
    raw_value = _optional_stripped(environ, variable_name)
    if raw_value is None:
        return True
    token = raw_value.upper()
    if token in ENABLED_OVERRIDE_TOKENS:
        return True
    if token in DISABLED_OVERRIDE_TOKENS:
        return False
    raise InvalidHolidayOverrideError(variable_name, "must be 1, 0, ON, or OFF")


def _event_days_with_override(
    environ: Mapping[str, str], definition: HolidayDefinition
) -> Callable[[int], tuple[date, ...]]:
    variable_name = holiday_event_environment_name(definition.tag)
    raw_value = _optional_stripped(environ, variable_name)
    if raw_value is None:
        return definition.event_days_for_year
    month_days = _parse_event_override(variable_name, raw_value)
    return _event_days_from_month_days(month_days)


def _event_days_from_month_days(
    month_days: tuple[tuple[int, int], ...],
) -> Callable[[int], tuple[date, ...]]:
    def event_days_for_year(year: int) -> tuple[date, ...]:
        days: list[date] = []
        for month, day in month_days:
            try:
                days.append(date(year, month, day))
            except ValueError as error:
                raise InvalidHolidayDateError(
                    year, "event day is not a valid calendar date"
                ) from error
        return tuple(days)

    return event_days_for_year


def _parse_event_override(
    variable_name: str, raw_value: str
) -> tuple[tuple[int, int], ...]:
    if raw_value == "":
        raise InvalidHolidayOverrideError(variable_name, "must not be empty")
    tokens = [token.strip() for token in raw_value.split(EVENT_DAY_LIST_SEPARATOR)]
    month_days: list[tuple[int, int]] = []
    seen: set[tuple[int, int]] = set()
    for token in tokens:
        if token == "":
            raise InvalidHolidayOverrideError(
                variable_name, "must not contain an empty event day"
            )
        month_day = _parse_event_day_token(variable_name, token)
        if month_day in seen:
            raise InvalidHolidayOverrideError(variable_name, "duplicate event day")
        seen.add(month_day)
        month_days.append(month_day)
    month_days.sort()
    return tuple(month_days)


def _parse_event_day_token(variable_name: str, token: str) -> tuple[int, int]:
    parts = token.split(DATE_PART_SEPARATOR)
    if len(parts) == ISO_DATE_PART_COUNT:
        try:
            parsed = date.fromisoformat(token)
        except ValueError as error:
            raise InvalidHolidayOverrideError(
                variable_name, "must be MM-DD or YYYY-MM-DD"
            ) from error
        return parsed.month, parsed.day
    if len(parts) == MONTH_DAY_PART_COUNT:
        return _parse_month_day(variable_name, parts[0], parts[1])
    raise InvalidHolidayOverrideError(variable_name, "must be MM-DD or YYYY-MM-DD")


def _parse_month_day(
    variable_name: str, month_token: str, day_token: str
) -> tuple[int, int]:
    if not month_token.isdigit() or not day_token.isdigit():
        raise InvalidHolidayOverrideError(variable_name, "must be MM-DD or YYYY-MM-DD")
    month = int(month_token)
    day = int(day_token)
    try:
        date(LEAP_YEAR_FOR_MONTH_DAY_VALIDATION, month, day)
    except ValueError as error:
        raise InvalidHolidayOverrideError(
            variable_name, "must be a real month-day"
        ) from error
    return month, day


def _optional_stripped(environ: Mapping[str, str], variable_name: str) -> str | None:
    if variable_name not in environ:
        return None
    return environ[variable_name].strip()
