from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from tv90.adapters.fake_clock import FakeClock, UnawareDateTimeError
from tv90.adapters.system_clock import SystemClock, detect_system_clock_trust
from tv90.ports import Clock

VANCOUVER = ZoneInfo("America/Vancouver")
MORNING = datetime(2026, 10, 1, 8, 0, tzinfo=VANCOUVER)


def test_fake_clock_now_returns_injected_time() -> None:
    clock = FakeClock(MORNING, trusted=True)

    assert clock.now() == MORNING


def test_fake_clock_is_trusted_matches_trusted_construction() -> None:
    clock = FakeClock(MORNING, trusted=True)

    assert clock.is_trusted() is True


def test_fake_clock_is_trusted_matches_untrusted_construction() -> None:
    clock = FakeClock(MORNING, trusted=False)

    assert clock.is_trusted() is False


def test_fake_clock_advance_time_changes_now() -> None:
    clock = FakeClock(MORNING, trusted=True)

    clock.advance_time(timedelta(minutes=15))

    assert clock.now() == datetime(2026, 10, 1, 8, 15, tzinfo=VANCOUVER)


def test_fake_clock_mark_trusted_makes_clock_trusted() -> None:
    clock = FakeClock(MORNING, trusted=False)

    clock.mark_trusted()

    assert clock.is_trusted() is True


def test_fake_clock_mark_untrusted_makes_clock_untrusted() -> None:
    clock = FakeClock(MORNING, trusted=True)

    clock.mark_untrusted()

    assert clock.is_trusted() is False


def test_fake_clock_rejects_naive_datetime() -> None:
    with pytest.raises(UnawareDateTimeError):
        FakeClock(datetime(2026, 10, 1, 8, 0), trusted=True)


def test_system_clock_now_returns_injected_time() -> None:
    clock = SystemClock(time_source=lambda: MORNING, trust_source=lambda: True)

    assert clock.now() == MORNING


def test_system_clock_is_trusted_returns_injected_true() -> None:
    clock = SystemClock(time_source=lambda: MORNING, trust_source=lambda: True)

    assert clock.is_trusted() is True


def test_system_clock_is_trusted_returns_injected_false() -> None:
    clock = SystemClock(time_source=lambda: MORNING, trust_source=lambda: False)

    assert clock.is_trusted() is False


def test_fake_clock_and_system_clock_satisfy_clock_protocol() -> None:
    clocks: list[Clock] = [
        FakeClock(MORNING, trusted=True),
        SystemClock(time_source=lambda: MORNING, trust_source=lambda: False),
    ]

    for clock in clocks:
        current_time = clock.now()
        assert current_time.tzinfo is not None
        assert isinstance(clock.is_trusted(), bool)


def test_detect_system_clock_trust_when_stamp_present() -> None:
    def fail_timedatectl() -> str:
        raise AssertionError("timedatectl must not run when the stamp exists")

    trusted = detect_system_clock_trust(
        stamp_present=lambda: True,
        read_timedatectl=fail_timedatectl,
    )

    assert trusted is True


def test_detect_system_clock_trust_when_timedatectl_reports_yes() -> None:
    trusted = detect_system_clock_trust(
        stamp_present=lambda: False,
        read_timedatectl=lambda: "yes\n",
    )

    assert trusted is True


def test_detect_system_clock_trust_when_timedatectl_reports_no() -> None:
    trusted = detect_system_clock_trust(
        stamp_present=lambda: False,
        read_timedatectl=lambda: "no\n",
    )

    assert trusted is False


def test_detect_system_clock_trust_when_probe_is_unavailable() -> None:
    def missing_timedatectl() -> str:
        raise FileNotFoundError("timedatectl")

    trusted = detect_system_clock_trust(
        stamp_present=lambda: False,
        read_timedatectl=missing_timedatectl,
    )

    assert trusted is False


def test_detect_system_clock_trust_falls_through_when_stamp_check_fails() -> None:
    def stamp_unreadable() -> bool:
        raise OSError("permission denied")

    trusted = detect_system_clock_trust(
        stamp_present=stamp_unreadable,
        read_timedatectl=lambda: "yes\n",
    )

    assert trusted is True
