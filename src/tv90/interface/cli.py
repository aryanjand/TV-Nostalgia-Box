"""Argparse entry for python -m tv90. Tests inject argv, environ, and stdout."""

from __future__ import annotations

import argparse
import os
import sys
from collections.abc import Mapping, Sequence
from datetime import date
from pathlib import Path
from typing import NoReturn, TextIO

from tv90.adapters.enriched_metadata import WikipediaEnrichedMetadataSource
from tv90.adapters.ffprobe_prober import build_ffprobe_media_prober
from tv90.adapters.file_duration_index import FileDurationIndex, write_duration_index
from tv90.adapters.filesystem_library import (
    FilesystemLibrarySource,
    LibraryDirectoryError,
)
from tv90.adapters.tvmaze_metadata import (
    METADATA_CACHE_FILENAME,
    EpisodeMetadataFetchError,
    build_tvmaze_metadata_source,
    urlopen_http_get,
)
from tv90.adapters.wikipedia_plots import WikipediaPlotIndex
from tv90.application.indexing import index_library_durations
from tv90.application.simulate import (
    DURATION_INDEX_FILENAME,
    FallbackDurationIndex,
    simulate_schedule,
)
from tv90.application.tagging import (
    apply_tags,
    format_tag_preview,
    packaged_keyword_rules,
    preview_tags,
)
from tv90.config import load_settings
from tv90.domain.episode import Episode
from tv90.domain.holiday_calendar import load_holiday_calendar
from tv90.domain.keyword_tags import KeywordTagRule
from tv90.ports.duration import DurationIndex, MediaProber
from tv90.ports.metadata import EpisodeMetadataSource, HttpGetter

SIMULATE_COMMAND = "simulate"
TAG_COMMAND = "tag"
INDEX_COMMAND = "index"
PROGRAM_NAME = "tv90"
ARGPARSE_ERROR_EXIT_CODE = 2
FAILURE_EXIT_CODE = 1
SUCCESS_EXIT_CODE = 0
DEFAULT_SAMPLE_LIBRARY_DIRECTORY = (
    Path(__file__).resolve().parents[3] / "tests" / "fixtures" / "sample_library"
)
LIBRARY_HELP = "folder of episode files (default: tests/fixtures/sample_library)"
INDEX_WROTE_PREFIX = "Wrote "
INDEX_WROTE_MIDDLE = " durations to "
INDEX_FAILED_HEADER = "Failed:"


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
    *,
    metadata_source: EpisodeMetadataSource | None = None,
    media_prober: MediaProber | None = None,
    http_get: HttpGetter | None = None,
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
    if command == TAG_COMMAND:
        try:
            if bool(args.apply):
                return _run_tag_apply(
                    _optional_library_path(args.library),
                    stdout,
                    metadata_source,
                    http_get,
                )
            return _run_tag_preview(
                _optional_library_path(args.library),
                stdout,
                metadata_source,
                http_get,
            )
        except LibraryDirectoryError as error:
            stdout.write(f"{PROGRAM_NAME}: error: {error}\n")
            return FAILURE_EXIT_CODE
        except EpisodeMetadataFetchError as error:
            stdout.write(f"{PROGRAM_NAME}: error: {error}\n")
            return FAILURE_EXIT_CODE
    if command == INDEX_COMMAND:
        try:
            return _run_index(
                _optional_library_path(args.library),
                stdout,
                media_prober,
            )
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
    simulate.add_argument("--library", default=None, help=LIBRARY_HELP)
    tag = subparsers.add_parser(
        TAG_COMMAND,
        help="preview or apply keyword tags from episode metadata",
    )
    _bind_stdout(tag, stdout)
    tag.add_argument("--library", default=None, help=LIBRARY_HELP)
    tag.add_argument(
        "--apply",
        action="store_true",
        help="rename files; default is a dry-run table",
    )
    index = subparsers.add_parser(
        INDEX_COMMAND,
        help="probe media durations and write duration-index.json",
    )
    _bind_stdout(index, stdout)
    index.add_argument("--library", default=None, help=LIBRARY_HELP)
    return parser


def _run_simulate(
    raw_date: str,
    library_directory: Path | None,
    environ: Mapping[str, str],
    stdout: TextIO,
) -> int:
    on_date = _parse_broadcast_date(raw_date)
    resolved_library = _resolve_library_directory(library_directory)
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


def _run_tag_preview(
    library_directory: Path | None,
    stdout: TextIO,
    metadata_source: EpisodeMetadataSource | None,
    http_get: HttpGetter | None,
) -> int:
    resolved_library, episodes, source, rules = _tag_inputs(
        library_directory, metadata_source, http_get, writable=False
    )
    stdout.write(format_tag_preview(preview_tags(episodes, source, rules)))
    _write_plot_count(stdout, source)
    return SUCCESS_EXIT_CODE


def _run_tag_apply(
    library_directory: Path | None,
    stdout: TextIO,
    metadata_source: EpisodeMetadataSource | None,
    http_get: HttpGetter | None,
) -> int:
    resolved_library, episodes, source, rules = _tag_inputs(
        library_directory, metadata_source, http_get, writable=True
    )
    stdout.write(
        format_tag_preview(apply_tags(resolved_library, episodes, source, rules))
    )
    _write_plot_count(stdout, source)
    return SUCCESS_EXIT_CODE


def _tag_inputs(
    library_directory: Path | None,
    metadata_source: EpisodeMetadataSource | None,
    http_get: HttpGetter | None,
    *,
    writable: bool,
) -> tuple[
    Path,
    tuple[Episode, ...],
    EpisodeMetadataSource,
    tuple[KeywordTagRule, ...],
]:
    resolved_library = _resolve_library_directory(library_directory)
    library = FilesystemLibrarySource(resolved_library)
    if metadata_source is not None:
        source: EpisodeMetadataSource = metadata_source
    else:
        getter = urlopen_http_get if http_get is None else http_get
        source = WikipediaEnrichedMetadataSource(
            build_tvmaze_metadata_source(
                resolved_library / METADATA_CACHE_FILENAME,
                writable=writable,
                http_get=getter,
            ),
            WikipediaPlotIndex(),
        )
    return resolved_library, library.episodes(), source, packaged_keyword_rules()


def _write_plot_count(stdout: TextIO, source: EpisodeMetadataSource) -> None:
    count = getattr(source, "packaged_plot_count", None)
    if not callable(count):
        return
    loaded = count()
    if isinstance(loaded, int):
        stdout.write(f"Plots: {loaded} packaged descriptions\n")


def _run_index(
    library_directory: Path | None,
    stdout: TextIO,
    media_prober: MediaProber | None,
) -> int:
    resolved_library = _resolve_library_directory(library_directory)
    library = FilesystemLibrarySource(resolved_library)
    prober = media_prober or build_ffprobe_media_prober()
    index_path = resolved_library / DURATION_INDEX_FILENAME
    result = index_library_durations(
        _library_media_paths(resolved_library, library),
        prober,
        index_path,
        write_duration_index,
    )
    stdout.write(
        f"{INDEX_WROTE_PREFIX}{len(result.written_filenames)}"
        f"{INDEX_WROTE_MIDDLE}{index_path}\n"
    )
    if result.failed_filenames:
        stdout.write(f"{INDEX_FAILED_HEADER}\n")
        for filename in result.failed_filenames:
            stdout.write(f"{filename}\n")
    return SUCCESS_EXIT_CODE


def _library_media_paths(
    library_directory: Path, library: FilesystemLibrarySource
) -> tuple[Path, ...]:
    names = [episode.filename for episode in library.episodes()]
    names.extend(library.unrecognized_filenames())
    return tuple(library_directory / name for name in names)


def _resolve_library_directory(library_directory: Path | None) -> Path:
    if library_directory is None:
        return DEFAULT_SAMPLE_LIBRARY_DIRECTORY
    return library_directory


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
