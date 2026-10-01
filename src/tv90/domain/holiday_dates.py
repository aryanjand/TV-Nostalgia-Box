"""Holiday event-day rules. Oct 31 and similar literals live only here."""

from __future__ import annotations

import calendar
from datetime import date, timedelta

# Halloween and Christmas month-day pairs belong in these rules, not in the
# calendar that reads the holiday table.
HALLOWEEN_MONTH = 10
HALLOWEEN_DAY = 31
CHRISTMAS_MONTH = 12
CHRISTMAS_EVE_DAY = 24
CHRISTMAS_DAY = 25
CANADIAN_THANKSGIVING_MONTH = 10
FIRST_DAY_OF_MONTH = 1
DAYS_IN_WEEK = 7

# Anonymous Gregorian (Meeus/Jones/Butcher) computus coefficients. These are
# the published formula, not household tunables; renaming them would hide the
# algorithm from anyone checking it against a reference.
GOLDEN_NUMBER_MODULUS = 19
CENTURY_DIVISOR = 100
QUARTER_CENTURY_DIVISOR = 4
SOLAR_CORRECTION_OFFSET = 8
SOLAR_CORRECTION_DIVISOR = 25
LUNAR_CORRECTION_OFFSET = 1
LUNAR_CORRECTION_DIVISOR = 3
PASCHAL_COEFFICIENT = 19
PASCHAL_OFFSET = 15
PASCHAL_MODULUS = 30
SUNDAY_BASE = 32
SUNDAY_COEFFICIENT = 2
SUNDAY_MODULUS = 7
EPAC_COEFFICIENT = 11
EPAC_SECOND_COEFFICIENT = 22
EPAC_DIVISOR = 451
MONTH_OFFSET = 114
DAYS_IN_MONTH_DIVISOR = 31


def halloween(year: int) -> date:
    return date(year, HALLOWEEN_MONTH, HALLOWEEN_DAY)


def christmas_event_days(year: int) -> tuple[date, ...]:
    return (
        date(year, CHRISTMAS_MONTH, CHRISTMAS_EVE_DAY),
        date(year, CHRISTMAS_MONTH, CHRISTMAS_DAY),
    )


def canadian_thanksgiving(year: int) -> date:
    october_first = date(year, CANADIAN_THANKSGIVING_MONTH, FIRST_DAY_OF_MONTH)
    days_until_monday = (calendar.MONDAY - october_first.weekday()) % DAYS_IN_WEEK
    first_monday = october_first + timedelta(days=days_until_monday)
    return first_monday + timedelta(days=DAYS_IN_WEEK)


def western_easter_sunday(year: int) -> date:
    """Western Easter Sunday via the Anonymous Gregorian computus."""
    golden_number = year % GOLDEN_NUMBER_MODULUS
    century = year // CENTURY_DIVISOR
    year_of_century = year % CENTURY_DIVISOR
    century_leap_days = century // QUARTER_CENTURY_DIVISOR
    century_leap_remainder = century % QUARTER_CENTURY_DIVISOR
    solar_correction = (century + SOLAR_CORRECTION_OFFSET) // SOLAR_CORRECTION_DIVISOR
    lunar_correction = (
        century - solar_correction + LUNAR_CORRECTION_OFFSET
    ) // LUNAR_CORRECTION_DIVISOR
    paschal_moon = (
        PASCHAL_COEFFICIENT * golden_number
        + century
        - century_leap_days
        - lunar_correction
        + PASCHAL_OFFSET
    ) % PASCHAL_MODULUS
    century_year_leap_days = year_of_century // QUARTER_CENTURY_DIVISOR
    century_year_leap_remainder = year_of_century % QUARTER_CENTURY_DIVISOR
    weekday_correction = (
        SUNDAY_BASE
        + SUNDAY_COEFFICIENT * century_leap_remainder
        + SUNDAY_COEFFICIENT * century_year_leap_days
        - paschal_moon
        - century_year_leap_remainder
    ) % SUNDAY_MODULUS
    epact_adjustment = (
        golden_number
        + EPAC_COEFFICIENT * paschal_moon
        + EPAC_SECOND_COEFFICIENT * weekday_correction
    ) // EPAC_DIVISOR
    day_of_year_offset = (
        paschal_moon
        + weekday_correction
        - SUNDAY_MODULUS * epact_adjustment
        + MONTH_OFFSET
    )
    month = day_of_year_offset // DAYS_IN_MONTH_DIVISOR
    day = (day_of_year_offset % DAYS_IN_MONTH_DIVISOR) + 1
    return date(year, month, day)
