"""Port for the current local time and whether that time can be trusted."""

from datetime import datetime
from typing import Protocol


class Clock(Protocol):
    def now(self) -> datetime:
        """Return timezone-aware local time in the configured timezone."""
        ...

    def is_trusted(self) -> bool:
        """Return True when the clock has been synchronized to network time."""
        ...
