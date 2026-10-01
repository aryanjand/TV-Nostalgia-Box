"""In-memory duration index and prober. No ffprobe and no disk."""

from collections.abc import Mapping

from tv90.domain.duration import (
    DurationUnknownError,
    ProbeFailedError,
    require_positive_duration,
)


class FakeDurationIndex:
    def __init__(self, durations: Mapping[str, float]) -> None:
        self._durations = dict(durations)

    def duration_seconds(self, filename: str) -> float:
        if filename not in self._durations:
            raise DurationUnknownError(filename)
        return require_positive_duration(filename, self._durations[filename])


class FakeMediaProber:
    def __init__(self, durations: Mapping[str, float]) -> None:
        self._durations = dict(durations)

    def duration_seconds(self, filename: str) -> float:
        if filename not in self._durations:
            raise ProbeFailedError(filename, "media file is missing")
        return require_positive_duration(filename, self._durations[filename])
