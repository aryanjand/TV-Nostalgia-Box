#!/usr/bin/env python3
"""Download CH 04 holiday specials from the Internet Archive.

Layer A (Little Bear / Oswald / Harry episodes) is already in the show
downloads. Tag those with `python -m tv90 tag`. This script is Layer B only:
standalone Holiday_*.mp4 files for the ghost channel.

The nine titles match the household list. Sources are compact original MPEG4
files so a 32 GB card can still hold the three cartoon shows.

Usage:
  python3 scripts/download-holiday.py --dry-run
  python3 scripts/download-holiday.py --holiday CHRISTMAS --dest ~/Downloads/holiday
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

USER_AGENT = "tv90-holiday-download/1.0 (personal library; +https://archive.org)"
CHUNK_SIZE = 1024 * 1024
SUCCESS_EXIT_CODE = 0
FAILURE_EXIT_CODE = 1
HOLIDAYS = ("HALLOWEEN", "THANKSGIVING", "CHRISTMAS", "EASTER")


@dataclass(frozen=True)
class HolidayCatalogEntry:
    dest_name: str
    holiday: str
    identifier: str
    remote_name: str


@dataclass(frozen=True)
class RemoteSpecial:
    dest_name: str
    holiday: str
    identifier: str
    remote_name: str
    size_bytes: int

    @property
    def download_url(self) -> str:
        quoted = urllib.parse.quote(self.remote_name)
        return f"https://archive.org/download/{self.identifier}/{quoted}"


CATALOG = (
    HolidayCatalogEntry(
        dest_name="Holiday_CuriousGeorgeAHalloweenBooFest_HALLOWEEN.mp4",
        holiday="HALLOWEEN",
        identifier="curious-george-a-halloween-boofest_202404",
        remote_name="Curious George A Halloween Boofest.mp4",
    ),
    HolidayCatalogEntry(
        dest_name="Holiday_PoohsHeffalumpHalloweenMovie_HALLOWEEN.mp4",
        holiday="HALLOWEEN",
        identifier="disney-presents-poohs-heffalump-halloween-movie",
        remote_name="Disney presents_ Pooh's Heffalump Halloween Movie.mp4",
    ),
    HolidayCatalogEntry(
        dest_name="Holiday_ACharlieBrownThanksgiving_THANKSGIVING.mp4",
        holiday="THANKSGIVING",
        identifier="a-charlie-brown-thanksgiving_202411",
        # Archive filename has a space before the extension.
        remote_name="A Charlie Brown Thanksgiving .mp4",
    ),
    HolidayCatalogEntry(
        dest_name="Holiday_RudolphTheRedNosedReindeer_CHRISTMAS.mp4",
        holiday="CHRISTMAS",
        identifier="RudolphTheRedNosedReindeer1964_201812",
        remote_name="Rudolph The Red Nosed Reindeer 1964.mp4",
    ),
    HolidayCatalogEntry(
        dest_name="Holiday_TheSnowman_CHRISTMAS.mp4",
        holiday="CHRISTMAS",
        identifier="the-snowman-1982",
        remote_name="The Snowman 1982.mp4",
    ),
    HolidayCatalogEntry(
        dest_name="Holiday_AFrostyTheSnowman_CHRISTMAS.mp4",
        holiday="CHRISTMAS",
        identifier=(
            "1969-frosty-the-snowman-christmas-movies-for-kids-animated-cartoons-for-children"
        ),
        remote_name=(
            "1969 Frosty the Snowman (Christmas Movies for Kids - "
            "animated Cartoons for Children).mp4"
        ),
    ),
    HolidayCatalogEntry(
        dest_name="Holiday_ACharlieBrownChristmas_CHRISTMAS.mp4",
        holiday="CHRISTMAS",
        identifier="a-charlie-brown-christmas-original-print",
        remote_name="A Charlie Brown Christmas original print.mp4",
    ),
    HolidayCatalogEntry(
        dest_name="Holiday_TheFirstEasterRabbit_EASTER.mp4",
        holiday="EASTER",
        identifier="the-first-easter-rabbit-480-x-640",
        remote_name="The First Easter Rabbit 480 x 640.mp4",
    ),
    HolidayCatalogEntry(
        dest_name="Holiday_WinnieThePoohSpringtimeWithRoo_EASTER.mp4",
        holiday="EASTER",
        identifier="winnie-the-pooh-springtime-with-roo_360_202607",
        remote_name="winnie-the-pooh-springtime-with-roo_360.mp4",
    ),
)


class DownloadError(Exception):
    """A file could not be listed or fetched."""


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    dest_dir = args.dest.expanduser().resolve()
    try:
        specials = list_specials(args.holiday)
    except DownloadError as error:
        print(error, file=sys.stderr)
        return FAILURE_EXIT_CODE

    if not specials:
        print("no matching holiday specials in the catalog", file=sys.stderr)
        return FAILURE_EXIT_CODE

    total = sum(special.size_bytes for special in specials)
    print(f"{len(specials)} holiday files, {_format_bytes(total)} total")
    if args.dry_run:
        for special in specials:
            print(
                f"{special.dest_name}\t{_format_bytes(special.size_bytes)}\t"
                f"{special.identifier}"
            )
        return SUCCESS_EXIT_CODE

    dest_dir.mkdir(parents=True, exist_ok=True)
    failures = 0
    for index, special in enumerate(specials, start=1):
        prefix = f"[{index}/{len(specials)}]"
        dest = dest_dir / special.dest_name
        try:
            _download_file(special, dest, prefix)
        except DownloadError as error:
            print(f"{prefix} failed {special.dest_name}: {error}", file=sys.stderr)
            failures += 1
    if failures:
        print(f"{failures} file(s) failed", file=sys.stderr)
        return FAILURE_EXIT_CODE
    print(f"done: {dest_dir}")
    return SUCCESS_EXIT_CODE


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Download Holiday_*.mp4 specials from archive.org."
    )
    parser.add_argument(
        "--dest",
        type=Path,
        default=Path("downloads/holiday"),
        help="folder for Holiday_*.mp4 files (default: downloads/holiday)",
    )
    parser.add_argument(
        "--holiday",
        choices=HOLIDAYS,
        help="download only this holiday (default: all four)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="list remote files and destination names without downloading",
    )
    return parser.parse_args(argv)


def list_specials(holiday: str | None) -> tuple[RemoteSpecial, ...]:
    specials: list[RemoteSpecial] = []
    for entry in CATALOG:
        if holiday is not None and entry.holiday != holiday:
            continue
        payload = _get_json(f"https://archive.org/metadata/{entry.identifier}")
        size_bytes = _original_mpeg4_size(payload, entry)
        specials.append(
            RemoteSpecial(
                dest_name=entry.dest_name,
                holiday=entry.holiday,
                identifier=entry.identifier,
                remote_name=entry.remote_name,
                size_bytes=size_bytes,
            )
        )
    return tuple(specials)


def _original_mpeg4_size(payload: dict[str, object], entry: HolidayCatalogEntry) -> int:
    files = payload.get("files")
    if not isinstance(files, list):
        raise DownloadError(f"{entry.identifier}: metadata did not include a file list")
    for raw in files:
        if not isinstance(raw, dict):
            continue
        if raw.get("name") != entry.remote_name:
            continue
        if raw.get("source") != "original" or raw.get("format") != "MPEG4":
            raise DownloadError(
                f"{entry.identifier}: {entry.remote_name} is not an original MPEG4"
            )
        try:
            return int(raw.get("size"))
        except (TypeError, ValueError) as error:
            raise DownloadError(f"missing size for {entry.remote_name}") from error
    raise DownloadError(f"{entry.identifier}: missing {entry.remote_name}")


def _download_file(special: RemoteSpecial, dest: Path, prefix: str) -> None:
    existing = dest.stat().st_size if dest.exists() else 0
    if existing == special.size_bytes:
        print(f"{prefix} skip {special.dest_name} (already {_format_bytes(existing)})")
        return
    if existing > special.size_bytes:
        dest.unlink()
        existing = 0
    mode = "ab" if existing else "wb"
    headers = {"User-Agent": USER_AGENT}
    if existing:
        headers["Range"] = f"bytes={existing}-"
    request = urllib.request.Request(special.download_url, headers=headers)
    try:
        with urllib.request.urlopen(request) as response:
            status = getattr(response, "status", 200)
            if existing and status == 200:
                dest.unlink(missing_ok=True)
                existing = 0
                mode = "wb"
            expected_remaining = special.size_bytes - existing
            print(
                f"{prefix} get {special.dest_name} "
                f"({_format_bytes(existing)}/{_format_bytes(special.size_bytes)})"
            )
            written = 0
            with dest.open(mode) as handle:
                for chunk in _iter_chunks(response):
                    handle.write(chunk)
                    written += len(chunk)
            if written < expected_remaining and status != 206:
                if dest.stat().st_size != special.size_bytes:
                    raise DownloadError(
                        f"short download: got {dest.stat().st_size}, "
                        f"expected {special.size_bytes}"
                    )
    except urllib.error.HTTPError as error:
        raise DownloadError(f"HTTP {error.code} for {special.remote_name}") from error
    except urllib.error.URLError as error:
        raise DownloadError(f"network error: {error.reason}") from error
    final_size = dest.stat().st_size
    if final_size != special.size_bytes:
        raise DownloadError(
            f"size mismatch: got {final_size}, expected {special.size_bytes}"
        )
    print(f"{prefix} ok  {special.dest_name} ({_format_bytes(final_size)})")


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
        raise DownloadError(f"network error fetching metadata: {error.reason}") from error
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
