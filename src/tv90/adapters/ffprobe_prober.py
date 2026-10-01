"""ffprobe duration adapter. Tests inject a command runner; never call real ffprobe."""

from __future__ import annotations

import json
import subprocess
from collections.abc import Callable

from tv90.domain.duration import ProbeFailedError, require_positive_duration

FFPROBE_COMMAND = "ffprobe"
FFPROBE_LOG_LEVEL_FLAG = "-v"
FFPROBE_LOG_LEVEL = "quiet"
FFPROBE_PRINT_FORMAT_FLAG = "-print_format"
FFPROBE_PRINT_FORMAT = "json"
FFPROBE_SHOW_FORMAT_FLAG = "-show_format"
FFPROBE_END_OF_OPTIONS = "--"
FFPROBE_TIMEOUT_SECONDS = 30
JSON_FORMAT_KEY = "format"
JSON_DURATION_KEY = "duration"

FfprobeCommandRunner = Callable[[tuple[str, ...]], str]


class FfprobeMediaProber:
    def __init__(self, run_command: FfprobeCommandRunner) -> None:
        self._run_command = run_command

    def duration_seconds(self, filename: str) -> float:
        try:
            output = self._run_command(ffprobe_arguments(filename))
        except (OSError, subprocess.SubprocessError) as error:
            raise ProbeFailedError(filename, "ffprobe command failed") from error
        return _duration_from_ffprobe_output(filename, output)


def ffprobe_arguments(filename: str) -> tuple[str, ...]:
    return (
        FFPROBE_COMMAND,
        FFPROBE_LOG_LEVEL_FLAG,
        FFPROBE_LOG_LEVEL,
        FFPROBE_PRINT_FORMAT_FLAG,
        FFPROBE_PRINT_FORMAT,
        FFPROBE_SHOW_FORMAT_FLAG,
        FFPROBE_END_OF_OPTIONS,
        filename,
    )


def run_ffprobe_command(arguments: tuple[str, ...]) -> str:
    """T15 wires this runner; tests inject a fake instead."""
    completed = subprocess.run(
        arguments,
        check=True,
        capture_output=True,
        text=True,
        timeout=FFPROBE_TIMEOUT_SECONDS,
    )
    return completed.stdout


def build_ffprobe_media_prober() -> FfprobeMediaProber:
    return FfprobeMediaProber(run_ffprobe_command)


def _duration_from_ffprobe_output(filename: str, output: str) -> float:
    try:
        loaded: object = json.loads(output)
    except json.JSONDecodeError as error:
        raise ProbeFailedError(filename, "ffprobe output is not JSON") from error
    if not isinstance(loaded, dict):
        raise ProbeFailedError(filename, "ffprobe output is not a JSON object")
    format_section: object = loaded.get(JSON_FORMAT_KEY)
    if not isinstance(format_section, dict):
        raise ProbeFailedError(filename, "ffprobe output is missing format")
    return _ffprobe_duration_seconds(filename, format_section.get(JSON_DURATION_KEY))


def _ffprobe_duration_seconds(filename: str, duration_value: object) -> float:
    if duration_value is None or isinstance(duration_value, bool):
        raise ProbeFailedError(filename, "ffprobe output is missing format.duration")
    if isinstance(duration_value, (int, float)):
        return require_positive_duration(filename, float(duration_value))
    if isinstance(duration_value, str):
        try:
            parsed = float(duration_value)
        except ValueError as error:
            raise ProbeFailedError(
                filename, "ffprobe duration is not a number"
            ) from error
        return require_positive_duration(filename, parsed)
    raise ProbeFailedError(filename, "ffprobe duration is not a number")
