"""Ports for looking up and probing media durations."""

from typing import Protocol


class DurationIndex(Protocol):
    def duration_seconds(self, filename: str) -> float:
        """Return seconds, or raise DurationUnknownError or CorruptDurationError."""
        ...


class MediaProber(Protocol):
    def duration_seconds(self, filename: str) -> float:
        """Return seconds, or raise ProbeFailedError or CorruptDurationError."""
        ...
