import calendar
from datetime import date

import pytest

from tv90.domain.holiday_dates import (
    canadian_thanksgiving,
    christmas_event_days,
    halloween,
    western_easter_sunday,
)

# Western (Gregorian) Easter Sundays from Wikipedia's list of Easter dates
# and the Anonymous Gregorian / Meeus–Jones–Butcher computus. Pinned so a
# wrong formula cannot hide behind a shared helper.
EASTER_SUNDAY_BY_YEAR = {
    2023: date(2023, 4, 9),
    2024: date(2024, 3, 31),
    2025: date(2025, 4, 20),
    2026: date(2026, 4, 5),
}

# Second Monday of October. 2023–2025 are required known dates.
THANKSGIVING_MONDAY_BY_YEAR = {
    2023: date(2023, 10, 9),
    2024: date(2024, 10, 14),
    2025: date(2025, 10, 13),
}


@pytest.mark.parametrize("year, expected", EASTER_SUNDAY_BY_YEAR.items())
def test_western_easter_sunday_matches_known_gregorian_dates(
    year: int, expected: date
) -> None:
    assert western_easter_sunday(year) == expected
    assert western_easter_sunday(year).weekday() == calendar.SUNDAY


@pytest.mark.parametrize("year, expected", THANKSGIVING_MONDAY_BY_YEAR.items())
def test_canadian_thanksgiving_matches_known_second_mondays(
    year: int, expected: date
) -> None:
    assert canadian_thanksgiving(year) == expected
    assert canadian_thanksgiving(year).weekday() == calendar.MONDAY


def test_canadian_thanksgiving_is_second_monday_of_october_across_years() -> None:
    for year in range(2020, 2031):
        observed = canadian_thanksgiving(year)
        october_mondays = [
            day
            for day in range(1, calendar.monthrange(year, 10)[1] + 1)
            if date(year, 10, day).weekday() == calendar.MONDAY
        ]
        assert observed == date(year, 10, october_mondays[1])


def test_halloween_is_october_thirty_first() -> None:
    assert halloween(2024) == date(2024, 10, 31)
    assert halloween(2025) == date(2025, 10, 31)


def test_christmas_event_days_are_december_twenty_four_and_twenty_five() -> None:
    assert christmas_event_days(2024) == (date(2024, 12, 24), date(2024, 12, 25))
    assert christmas_event_days(2025) == (date(2025, 12, 24), date(2025, 12, 25))
