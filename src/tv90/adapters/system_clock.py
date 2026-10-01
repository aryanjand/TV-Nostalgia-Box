"""System clock adapter. Domain and application must not import this module."""

from __future__ import annotations

import subprocess
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

SYSTEMD_TIMESYNC_SYNCHRONIZED_PATH = Path("/run/systemd/timesync/synchronized")
# Cap the NTP probe so a stuck timedatectl cannot freeze kiosk start.
TIMEDATECTL_PROBE_TIMEOUT_SECONDS = 2
TIMEDATECTL_TRUSTED_VALUES = frozenset({"yes", "true", "1"})


class SystemClock:
    def __init__(
        self,
        time_source: Callable[[], datetime],
        trust_source: Callable[[], bool],
    ) -> None:
        self._time_source = time_source
        self._trust_source = trust_source

    def now(self) -> datetime:
        return self._time_source()

    def is_trusted(self) -> bool:
        return self._trust_source()


def build_system_clock(timezone: ZoneInfo) -> SystemClock:
    """T15 wires this factory; tests construct SystemClock with fakes instead."""
    return SystemClock(
        time_source=lambda: datetime.now(timezone),
        trust_source=_system_trust_source,
    )


def detect_system_clock_trust(
    stamp_present: Callable[[], bool],
    read_timedatectl: Callable[[], str],
) -> bool:
    try:
        if stamp_present():
            return True
    except OSError:
        pass
    try:
        output = read_timedatectl()
    except (OSError, subprocess.SubprocessError):
        return False
    return output.strip().lower() in TIMEDATECTL_TRUSTED_VALUES


def _system_trust_source() -> bool:
    return detect_system_clock_trust(
        stamp_present=_synchronized_stamp_exists,
        read_timedatectl=_read_timedatectl_output,
    )


def _synchronized_stamp_exists() -> bool:
    return SYSTEMD_TIMESYNC_SYNCHRONIZED_PATH.exists()


def _read_timedatectl_output() -> str:
    completed = subprocess.run(
        ["timedatectl", "show", "--property=NTPSynchronized", "--value"],
        check=False,
        capture_output=True,
        text=True,
        timeout=TIMEDATECTL_PROBE_TIMEOUT_SECONDS,
    )
    return completed.stdout
