"""Port for television power over HDMI-CEC. Adapters implement these methods."""

from typing import Protocol


class TvPower(Protocol):
    def standby(self) -> None:
        """Put the television in standby (night lock)."""
        ...

    def power_on(self) -> None:
        """Power the television on (morning sign-on)."""
        ...

    def is_in_standby(self) -> bool:
        """CQS query: True after standby until power_on. Does not change power."""
        ...
