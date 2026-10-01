"""Probe library media and write the duration index. Maintenance only."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from tv90.domain.duration import CorruptDurationError, ProbeFailedError
from tv90.ports.duration import MediaProber

DurationIndexWriter = Callable[[Path, Mapping[str, float]], None]


@dataclass(frozen=True)
class DurationIndexResult:
    written_filenames: tuple[str, ...]
    failed_filenames: tuple[str, ...]


def index_library_durations(
    media_paths: Sequence[Path],
    prober: MediaProber,
    index_path: Path,
    write_index: DurationIndexWriter,
) -> DurationIndexResult:
    durations: dict[str, float] = {}
    failed: list[str] = []
    for path in media_paths:
        try:
            durations[path.name] = prober.duration_seconds(str(path))
        except (ProbeFailedError, CorruptDurationError):
            failed.append(path.name)
    write_index(index_path, durations)
    return DurationIndexResult(
        written_filenames=tuple(durations),
        failed_filenames=tuple(failed),
    )
