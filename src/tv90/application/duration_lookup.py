"""Runtime duration lookup: index first, probe on miss, never write."""

from __future__ import annotations

from dataclasses import dataclass

from tv90.domain.duration import DurationUnknownError
from tv90.ports.duration import DurationIndex, MediaProber


@dataclass(frozen=True)
class DurationLookup:
    duration_index: DurationIndex
    media_prober: MediaProber

    def duration_seconds(self, filename: str) -> float:
        try:
            return self.duration_index.duration_seconds(filename)
        except DurationUnknownError:
            return self.media_prober.duration_seconds(filename)
