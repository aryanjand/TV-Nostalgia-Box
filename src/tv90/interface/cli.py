"""Argparse entry for python -m tv90. Tests inject argv, environ, and stdout."""

from __future__ import annotations

import argparse
import os
import sys
from collections.abc import Mapping, Sequence
from datetime import date
from pathlib import Path
from typing import NoReturn, TextIO

from tv90.adapters.file_duration_index import FileDurationIndex
from tv90.adapters.filesystem_library import (
    FilesystemLibrarySource,
    LibraryDirectoryError,
)
from tv90.application.simulate import (
    DURATION_INDEX_FILENAME,
    FallbackDurationIndex,
    simulate_schedule,
)
from tv90.config import load_settings
from tv90.domain.holiday_calendar import load_holiday_calendar
from tv90.ports.duration import DurationIndex

SIMULATE_COMMAND = "simulate"
PROGRAM_NAME = "tv90"
ARGPARSE_ERROR_EXIT_CODE = 2
FAILURE_EXIT_CODE = 1
SUCCESS_EXIT_CODE = 0
DEFAULT_SAMPLE_LIBRARY_DIRECTORY = (
    Path(__file__).resolve().parents[3] / "tests" / "fixtures" / "sample_library"
)


class InvalidSimulateDateError(Exception):
    """--date was not an ISO calendar day."""

    def __init__(self, raw_value: str) -> None:
        self.raw_value = raw_value
        super().__init__(f"invalid date {raw_value!r}; expected YYYY-MM-DD")


class _InjectedArgumentParser(argparse.ArgumentParser):
    """Argparse writer that uses the injected stdout instead of sys.stderr."""

    _stdout: TextIO

    def error(self, message: str) -> NoReturn:
        self.print_usage(self._stdout)
        self._stdout.write(f"{PROGRAM_NAME}: error: {message}\n")
        raise SystemExit(ARGPARSE_ERROR_EXIT_CODE)


def run() -> int:
    """Composition wrapper: real process argv, environ, and stdout."""
    return main(sys.argv[1:], os.environ, sys.stdout)


def main(
    argv: Sequence[str],
    environ: Mapping[str, str],
    stdout: TextIO,
) -> int:
    parser = _build_parser(stdout)
    try:
        args = parser.parse_args(list(argv))
    except SystemExit as error:
        return _system_exit_code(error)
    command = str(args.command)
    if command == SIMULATE_COMMAND:
        try:
            return _run_simulate(
                str(args.date),
                _optional_library_path(args.library),
                environ,
                stdout,
            )
        except InvalidSimulateDateError as error:
            stdout.write(f"{PROGRAM_NAME}: error: {error}\n")
            return FAILURE_EXIT_CODE
        except LibraryDirectoryError as error:
            stdout.write(f"{PROGRAM_NAME}: error: {error}\n")
            return FAILURE_EXIT_CODE
    stdout.write(f"unknown command: {command}\n")
    return FAILURE_EXIT_CODE


def _build_parser(stdout: TextIO) -> argparse.ArgumentParser:
    parser = _InjectedArgumentParser(prog=PROGRAM_NAME)
    _bind_stdout(parser, stdout)
    subparsers = parser.add_subparsers(
        dest="command",
        required=True,
        parser_class=_InjectedArgumentParser,
    )
    simulate = subparsers.add_parser(
        SIMULATE_COMMAND,
        help="print each live channel's timeline for a date",
    )
    _bind_stdout(simulate, stdout)
    simulate.add_argument(
        "--date",
        required=True,
        metavar="YYYY-MM-DD",
        help="broadcast date (required; no clock default)",
    )
    simulate.add_argument(
        "--library",
        default=None,
        help="folder of episode files (default: tests/fixtures/sample_library)",
    )
    # T14 registers `tag` and `index` on this same subparser set.
    return parser


def _run_simulate(
    raw_date: str,
    library_directory: Path | None,
    environ: Mapping[str, str],
    stdout: TextIO,
) -> int:
    on_date = _parse_broadcast_date(raw_date)
    resolved_library = (
        DEFAULT_SAMPLE_LIBRARY_DIRECTORY
        if library_directory is None
        else library_directory
    )
    library = FilesystemLibrarySource(resolved_library)
    settings = load_settings(environ)
    holiday_calendar = load_holiday_calendar(environ, settings)
    duration_index = _duration_index_for_library(resolved_library)
    stdout.write(
        simulate_schedule(
            on_date,
            library.episodes(),
            duration_index,
            settings,
            holiday_calendar,
        )
    )
    return SUCCESS_EXIT_CODE


def _duration_index_for_library(library_directory: Path) -> DurationIndex:
    index_path = library_directory / DURATION_INDEX_FILENAME
    if index_path.is_file():
        return FileDurationIndex(index_path)
    return FallbackDurationIndex()


def _bind_stdout(parser: argparse.ArgumentParser, stdout: TextIO) -> None:
    if not isinstance(parser, _InjectedArgumentParser):
        raise TypeError("expected injected argparse parser")
    parser._stdout = stdout


def _parse_broadcast_date(raw_value: str) -> date:
    try:
        return date.fromisoformat(raw_value)
    except ValueError as error:
        raise InvalidSimulateDateError(raw_value) from error


def _optional_library_path(value: object) -> Path | None:
    if value is None:
        return None
    return Path(str(value))


def _system_exit_code(error: SystemExit) -> int:
    code = error.code
    if code is None:
        return SUCCESS_EXIT_CODE
    if isinstance(code, int):
        return code
    return FAILURE_EXIT_CODE
