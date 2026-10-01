import math
import subprocess
from dataclasses import replace

import pytest

from tv90.config import MAXIMUM_CLOCK_HOUR, MINIMUM_CLOCK_HOUR, load_settings
from tv90.domain.broadcast_day import broadcast_day_contains
from tv90.domain.time_weight import InvalidClockHourError

MINUTES_PER_HOUR = 60
SIX_TWENTY_NINE = 6 + 29 / MINUTES_PER_HOUR
SIX_THIRTY = 6.5
EIGHT_FIFTY_NINE_PM = 20 + 59 / MINUTES_PER_HOUR
NINE_PM = 21.0


def test_broadcast_day_contains_is_false_at_six_twenty_nine() -> None:
    assert broadcast_day_contains(SIX_TWENTY_NINE, load_settings({})) is False


def test_broadcast_day_contains_is_true_at_six_thirty() -> None:
    assert broadcast_day_contains(SIX_THIRTY, load_settings({})) is True


def test_broadcast_day_contains_is_true_at_eight_fifty_nine_pm() -> None:
    assert broadcast_day_contains(EIGHT_FIFTY_NINE_PM, load_settings({})) is True


def test_broadcast_day_contains_is_false_at_nine_pm() -> None:
    assert broadcast_day_contains(NINE_PM, load_settings({})) is False


def test_broadcast_day_contains_follows_settings_hours() -> None:
    settings = replace(load_settings({}), sign_on_hour=7.0, night_lock_hour=20.0)

    assert broadcast_day_contains(6.5, settings) is False
    assert broadcast_day_contains(7.0, settings) is True
    assert broadcast_day_contains(19.99, settings) is True
    assert broadcast_day_contains(20.0, settings) is False


def test_broadcast_day_contains_allows_day_boundaries_outside_sign_on() -> None:
    settings = load_settings({})

    assert broadcast_day_contains(MINIMUM_CLOCK_HOUR, settings) is False
    assert broadcast_day_contains(MAXIMUM_CLOCK_HOUR, settings) is False


@pytest.mark.parametrize("clock_hour", [math.nan, math.inf, -math.inf])
def test_broadcast_day_contains_rejects_non_finite_clock_hour(
    clock_hour: float,
) -> None:
    with pytest.raises(InvalidClockHourError):
        broadcast_day_contains(clock_hour, load_settings({}))


def test_broadcast_day_contains_rejects_hour_below_minimum() -> None:
    with pytest.raises(InvalidClockHourError):
        broadcast_day_contains(MINIMUM_CLOCK_HOUR - 0.01, load_settings({}))


def test_broadcast_day_contains_rejects_hour_above_maximum() -> None:
    with pytest.raises(InvalidClockHourError):
        broadcast_day_contains(MAXIMUM_CLOCK_HOUR + 0.01, load_settings({}))


def test_broadcast_day_contains_does_not_open_files_or_run_processes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_open(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("broadcast_day_contains must not open files")

    def fail_run(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("broadcast_day_contains must not run processes")

    monkeypatch.setattr("builtins.open", fail_open)
    monkeypatch.setattr(subprocess, "run", fail_run)
    monkeypatch.setattr(subprocess, "Popen", fail_run)

    assert broadcast_day_contains(8.0, load_settings({})) is True
