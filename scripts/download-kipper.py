#!/usr/bin/env python3
"""Download Kipper originals from the Internet Archive and rename them.

Source item:
  https://archive.org/details/s-01-e-09-snowy-day_202311

Remote names look like S01E01 - The Visitor.mp4 (season/episode then title).
This script keeps SxxExx and prefixes Kipper_; the title is ignored so tags
come from the tagger.

Usage:
  python3 scripts/download-kipper.py --dry-run
  python3 scripts/download-kipper.py --dest ~/Downloads/kipper
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

IDENTIFIER = "s-01-e-09-snowy-day_202311"
METADATA_URL = f"https://archive.org/metadata/{IDENTIFIER}"
DOWNLOAD_BASE = f"https://archive.org/download/{IDENTIFIER}"
USER_AGENT = "tv90-kipper-download/1.0 (personal library; +https://archive.org)"
CHUNK_SIZE = 1024 * 1024
BROADCAST_NAME = re.compile(r"^S(\d{2})E(\d{2}).*\.mp4$", re.IGNORECASE)
SUCCESS_EXIT_CODE = 0
FAILURE_EXIT_CODE = 1


@dataclass(frozen=True)
class RemoteEpisode:
    remote_name: str
    dest_name: str
    size_bytes: int

    @property
    def download_url(self) -> str:
        quoted = urllib.parse.quote(self.remote_name)
        return f"{DOWNLOAD_BASE}/{quoted}"


class DownloadError(Exception):
    """A file could not be listed or fetched."""


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    dest_dir = args.dest.expanduser().resolve()
    try:
        episodes = list_original_episodes()
    except DownloadError as error:
        print(error, file=sys.stderr)
        return FAILURE_EXIT_CODE

    if not episodes:
        print("no original MPEG4 episodes found on the archive item", file=sys.stderr)
        return FAILURE_EXIT_CODE

    total = sum(episode.size_bytes for episode in episodes)
    print(f"{len(episodes)} original files, {_format_bytes(total)} total")
    if args.dry_run:
        for episode in episodes:
            print(
                f"{episode.dest_name}\t{_format_bytes(episode.size_bytes)}\t"
                f"{episode.remote_name}"
            )
        return SUCCESS_EXIT_CODE

    dest_dir.mkdir(parents=True, exist_ok=True)
    failures = 0
    for index, episode in enumerate(episodes, start=1):
        prefix = f"[{index}/{len(episodes)}]"
        dest = dest_dir / episode.dest_name
        try:
            _download_episode(episode, dest, prefix)
        except DownloadError as error:
            print(f"{prefix} failed {episode.dest_name}: {error}", file=sys.stderr)
            failures += 1
    if failures:
        print(f"{failures} file(s) failed", file=sys.stderr)
        return FAILURE_EXIT_CODE
    print(f"done: {dest_dir}")
    return SUCCESS_EXIT_CODE


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Download Kipper MPEG4 originals from archive.org."
    )
    parser.add_argument(
        "--dest",
        type=Path,
        default=Path("downloads/kipper"),
        help="folder for Kipper_SxxExx.mp4 files (default: downloads/kipper)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="list remote files and destination names without downloading",
    )
    return parser.parse_args(argv)


def list_original_episodes() -> tuple[RemoteEpisode, ...]:
    payload = _get_json(METADATA_URL)
    files = payload.get("files")
    if not isinstance(files, list):
        raise DownloadError("archive.org metadata did not include a file list")
    episodes: list[RemoteEpisode] = []
    seen_dest: set[str] = set()
    for raw in files:
        if not isinstance(raw, dict):
            continue
        if not _is_original_mpeg4(raw):
            continue
        name = raw.get("name")
        size = raw.get("size")
        if not isinstance(name, str):
            continue
        dest_name = _library_filename(name)
        if dest_name is None:
            print(f"skip unrecognized name: {name}", file=sys.stderr)
            continue
        if dest_name in seen_dest:
            raise DownloadError(f"duplicate destination name {dest_name}")
        try:
            size_bytes = int(size)
        except (TypeError, ValueError) as error:
            raise DownloadError(f"missing size for {name}") from error
        seen_dest.add(dest_name)
        episodes.append(
            RemoteEpisode(remote_name=name, dest_name=dest_name, size_bytes=size_bytes)
        )
    return tuple(sorted(episodes, key=lambda item: item.dest_name))


def _is_original_mpeg4(file_info: dict[object, object]) -> bool:
    name = file_info.get("name")
    if not isinstance(name, str) or not name.lower().endswith(".mp4"):
        return False
    if name.lower().endswith(".ia.mp4"):
        return False
    return file_info.get("source") == "original" and file_info.get("format") == "MPEG4"


def _library_filename(remote_name: str) -> str | None:
    match = BROADCAST_NAME.fullmatch(Path(remote_name).name)
    if match is None:
        return None
    season = int(match.group(1))
    episode = int(match.group(2))
    return f"Kipper_S{season:02d}E{episode:02d}.mp4"


def _download_episode(episode: RemoteEpisode, dest: Path, prefix: str) -> None:
    existing = dest.stat().st_size if dest.exists() else 0
    if existing == episode.size_bytes:
        print(f"{prefix} skip {episode.dest_name} (already {_format_bytes(existing)})")
        return
    if existing > episode.size_bytes:
        dest.unlink()
        existing = 0
    mode = "ab" if existing else "wb"
    headers = {"User-Agent": USER_AGENT}
    if existing:
        headers["Range"] = f"bytes={existing}-"
    request = urllib.request.Request(episode.download_url, headers=headers)
    try:
        with urllib.request.urlopen(request) as response:
            status = getattr(response, "status", 200)
            if existing and status == 200:
                dest.unlink(missing_ok=True)
                existing = 0
                mode = "wb"
            expected_remaining = episode.size_bytes - existing
            print(
                f"{prefix} get {episode.dest_name} "
                f"({_format_bytes(existing)}/{_format_bytes(episode.size_bytes)})"
            )
            written = 0
            with dest.open(mode) as handle:
                for chunk in _iter_chunks(response):
                    handle.write(chunk)
                    written += len(chunk)
            if written < expected_remaining and status != 206:
                if dest.stat().st_size != episode.size_bytes:
                    raise DownloadError(
                        f"short download: got {dest.stat().st_size}, "
                        f"expected {episode.size_bytes}"
                    )
    except urllib.error.HTTPError as error:
        raise DownloadError(f"HTTP {error.code} for {episode.remote_name}") from error
    except urllib.error.URLError as error:
        raise DownloadError(f"network error: {error.reason}") from error
    final_size = dest.stat().st_size
    if final_size != episode.size_bytes:
        raise DownloadError(
            f"size mismatch: got {final_size}, expected {episode.size_bytes}"
        )
    print(f"{prefix} ok  {episode.dest_name} ({_format_bytes(final_size)})")


def _iter_chunks(response: object) -> Iterator[bytes]:
    read = getattr(response, "read")
    while True:
        chunk = read(CHUNK_SIZE)
        if not chunk:
            return
        yield chunk


def _get_json(url: str) -> dict[str, object]:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(request) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        raise DownloadError(f"HTTP {error.code} fetching metadata") from error
    except urllib.error.URLError as error:
        raise DownloadError(
            f"network error fetching metadata: {error.reason}"
        ) from error
    except json.JSONDecodeError as error:
        raise DownloadError("archive.org metadata was not JSON") from error
    if not isinstance(payload, dict):
        raise DownloadError("archive.org metadata was not an object")
    return payload


def _format_bytes(size: int) -> str:
    value = float(size)
    for unit in ("B", "KB", "MB", "GB"):
        if value < 1024 or unit == "GB":
            if unit == "B":
                return f"{int(value)} {unit}"
            return f"{value:.1f} {unit}"
        value /= 1024
    return f"{size} B"


if __name__ == "__main__":
    raise SystemExit(main())
