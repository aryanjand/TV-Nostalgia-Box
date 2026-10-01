"""Duration rules shared by index, prober, and lookup. No I/O."""

from __future__ import annotations

import math

# Durations must be strictly greater than this. Zero-length media cannot fill a slot.
MINIMUM_DURATION_SECONDS = 0.0


class DurationUnknownError(Exception):
    """The duration index has no entry for this filename."""

    def __init__(self, filename: str) -> None:
        self.filename = filename
        super().__init__(f"{filename}: duration is not in the index")


class CorruptDurationError(Exception):
    """A duration was present but is not a positive finite number."""

    def __init__(self, filename: str, reason: str) -> None:
        self.filename = filename
        self.reason = reason
        super().__init__(f"{filename}: {reason}")


class ProbeFailedError(Exception):
    """The prober could not produce a duration for this file."""

    def __init__(self, filename: str, reason: str) -> None:
        self.filename = filename
        self.reason = reason
        super().__init__(f"{filename}: {reason}")


def require_positive_duration(filename: str, duration_seconds: float) -> float:
    if (
        not math.isfinite(duration_seconds)
        or duration_seconds <= MINIMUM_DURATION_SECONDS
    ):
        raise CorruptDurationError(
            filename, "duration must be a positive finite number"
        )
    return float(duration_seconds)
