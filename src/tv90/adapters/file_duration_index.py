"""Read-only JSON duration index. Writing is a separate T14 maintenance function."""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path

from tv90.domain.duration import (
    DurationUnknownError,
    require_positive_duration,
)

JSON_INDENT_SPACES = 2
TEXT_ENCODING = "utf-8"


class DurationIndexUnreadableError(Exception):
    """The duration index file is missing, invalid JSON, or the wrong shape."""

    def __init__(self, index_path: Path, reason: str) -> None:
        self.index_path = index_path
        self.reason = reason
        super().__init__(f"{index_path}: {reason}")


class FileDurationIndex:
    def __init__(self, index_path: Path) -> None:
        self._index_path = index_path

    def duration_seconds(self, filename: str) -> float:
        durations = _read_duration_mapping(self._index_path)
        if filename not in durations:
            raise DurationUnknownError(filename)
        return require_positive_duration(filename, durations[filename])


def write_duration_index(index_path: Path, durations: Mapping[str, float]) -> None:
    """T14 maintenance helper. Runtime lookup must never call this."""
    validated = {
        filename: require_positive_duration(filename, seconds)
        for filename, seconds in durations.items()
    }
    index_path.write_text(
        json.dumps(validated, indent=JSON_INDENT_SPACES, sort_keys=True) + "\n",
        encoding=TEXT_ENCODING,
    )


def _read_duration_mapping(index_path: Path) -> dict[str, float]:
    try:
        file_text = index_path.read_text(encoding=TEXT_ENCODING)
    except OSError as error:
        raise DurationIndexUnreadableError(
            index_path, "duration index file could not be read"
        ) from error
    try:
        loaded: object = json.loads(file_text)
    except json.JSONDecodeError as error:
        raise DurationIndexUnreadableError(
            index_path, "duration index is not valid JSON"
        ) from error
    if not isinstance(loaded, dict):
        raise DurationIndexUnreadableError(
            index_path, "duration index must be a JSON object"
        )
    durations: dict[str, float] = {}
    for filename, value in loaded.items():
        durations[str(filename)] = _json_duration_seconds(index_path, value)
    return durations


def _json_duration_seconds(index_path: Path, value: object) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise DurationIndexUnreadableError(
            index_path, "duration index values must be JSON numbers"
        )
    return float(value)
