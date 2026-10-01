"""In-memory TvPower for tests. No OS, no cec-client, and no sleep."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class StandbyCommand:
    pass


@dataclass(frozen=True)
class PowerOnCommand:
    pass


TvPowerCommand = StandbyCommand | PowerOnCommand


class FakeTvPower:
    """Starts powered on so night-lock tests can send standby from a live TV."""

    def __init__(self) -> None:
        self._commands: list[TvPowerCommand] = []
        self._in_standby = False

    @property
    def commands(self) -> tuple[TvPowerCommand, ...]:
        return tuple(self._commands)

    def standby(self) -> None:
        self._in_standby = True
        self._commands.append(StandbyCommand())

    def power_on(self) -> None:
        self._in_standby = False
        self._commands.append(PowerOnCommand())

    def is_in_standby(self) -> bool:
        return self._in_standby
