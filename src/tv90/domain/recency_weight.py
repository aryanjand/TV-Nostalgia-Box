"""Per-file recency weight from injected airing history. No I/O."""

from __future__ import annotations

from collections.abc import Sequence

from tv90.config import Settings
from tv90.domain.episode import Episode

# Identity multiplier when the file is outside the penalty window (or history is empty).
RECENCY_CLEAR_WEIGHT = 1.0


class RecencyWeight:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def weight(
        self, episode: Episode, recently_aired_filenames: Sequence[str]
    ) -> float:
        # Chronological: oldest first, newest last. The block window is the tail.
        blocked_filenames = recently_aired_filenames[
            -self._settings.recency_block_count :
        ]
        if episode.filename in blocked_filenames:
            return self._settings.recency_block_weight
        penalized_filenames = recently_aired_filenames[
            -self._settings.recency_penalty_count :
        ]
        if episode.filename in penalized_filenames:
            return self._settings.recency_penalty_weight
        return RECENCY_CLEAR_WEIGHT
