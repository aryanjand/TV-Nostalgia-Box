#!/usr/bin/env python3
"""Generate local channel bumpers with ffmpeg lavfi. No network.

Files land under --dest (default downloads/interstitials/ch0N), never the episode
library. Total output must stay under 2.5 GB.
"""

from __future__ import annotations

import argparse
import math
import subprocess
import sys
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

SUCCESS_EXIT_CODE = 0
FAILURE_EXIT_CODE = 1
MAX_TOTAL_BYTES = 2_500_000_000
BYTES_PER_SECOND_BUDGET = 1_000_000
VIDEO_WIDTH = 640
VIDEO_HEIGHT = 360
VIDEO_FRAME_RATE = 24
AUDIO_SAMPLE_RATE = 44100
HUE_SATURATION = 1.15
DRAWTEXT_FONT_SIZE = 32
DRAWTEXT_BOX_ALPHA = "0.50"
DRAWTEXT_BOX_BORDER = 12
DEFAULT_DEST = Path("downloads/interstitials")
DURATIONS_SECONDS = (16, 19, 23, 28, 32)
HOLIDAY_DURATIONS_SECONDS = (19, 28)
CHANNEL_FOLDER_PREFIX = "ch"
CHANNEL_FOLDER_NUMBER_WIDTH = 2

FfmpegRunner = Callable[[Sequence[str]], None]
DurationProber = Callable[[Path], float]


class InterstitialBuildError(Exception):
    """A bumper could not be planned, probed, or rendered."""


@dataclass(frozen=True)
class BumperKind:
    token: str
    message_template: str
    hue_scale: float
    fade_seconds: float
    text_y_offset: int


@dataclass(frozen=True)
class ChannelPack:
    channel_number: int
    label: str
    slug: str
    color: str
    accent: str
    hue_degrees_per_second: float
    kinds: tuple[BumperKind, ...]
    durations_seconds: tuple[int, ...]


KIND_IDENT = BumperKind(
    token="ident",
    message_template="{banner} {label}",
    hue_scale=1.0,
    fade_seconds=1.2,
    text_y_offset=0,
)
KIND_WOODS_BREAK = BumperKind(
    token="be_right_back",
    message_template="Woods break",
    hue_scale=2.0,
    fade_seconds=0.8,
    text_y_offset=-36,
)
KIND_CITY_BREAK = BumperKind(
    token="be_right_back",
    message_template="City break",
    hue_scale=2.2,
    fade_seconds=0.7,
    text_y_offset=-40,
)
KIND_DINO_BREAK = BumperKind(
    token="be_right_back",
    message_template="Dino break",
    hue_scale=1.8,
    fade_seconds=0.9,
    text_y_offset=-28,
)
KIND_HOLIDAY_BREAK = BumperKind(
    token="be_right_back",
    message_template="Holiday break",
    hue_scale=1.6,
    fade_seconds=0.9,
    text_y_offset=-24,
)
KIND_BACK_TO_SHOW = BumperKind(
    token="back_to_show",
    message_template="Back to {label}",
    hue_scale=0.45,
    fade_seconds=1.6,
    text_y_offset=40,
)

CHANNEL_PACKS: tuple[ChannelPack, ...] = (
    ChannelPack(
        channel_number=1,
        label="Little Bear",
        slug="little_bear",
        color="0x6B8E4E",
        accent="0xD5E6B8",
        hue_degrees_per_second=8.0,
        kinds=(KIND_IDENT, KIND_WOODS_BREAK, KIND_BACK_TO_SHOW),
        durations_seconds=DURATIONS_SECONDS,
    ),
    ChannelPack(
        channel_number=2,
        label="Oswald",
        slug="oswald",
        color="0x4A7FB5",
        accent="0xB8DCF0",
        hue_degrees_per_second=-14.0,
        kinds=(KIND_IDENT, KIND_CITY_BREAK, KIND_BACK_TO_SHOW),
        durations_seconds=DURATIONS_SECONDS,
    ),
    ChannelPack(
        channel_number=3,
        label="Harry",
        slug="harry",
        color="0xE0B84A",
        accent="0xF6E2A0",
        hue_degrees_per_second=22.0,
        kinds=(KIND_IDENT, KIND_DINO_BREAK, KIND_BACK_TO_SHOW),
        durations_seconds=DURATIONS_SECONDS,
    ),
    ChannelPack(
        channel_number=4,
        label="Holiday",
        slug="holiday",
        color="0xC45C26",
        accent="0xF0C078",
        hue_degrees_per_second=6.0,
        kinds=(KIND_IDENT, KIND_HOLIDAY_BREAK),
        durations_seconds=HOLIDAY_DURATIONS_SECONDS,
    ),
)


@dataclass(frozen=True)
class BumperPlan:
    pack: ChannelPack
    kind: BumperKind
    duration_seconds: int

    @property
    def channel_number(self) -> int:
        return self.pack.channel_number

    @property
    def label(self) -> str:
        return self.pack.label

    @property
    def slug(self) -> str:
        return self.pack.slug

    @property
    def color(self) -> str:
        return self.pack.color

    @property
    def accent(self) -> str:
        return self.pack.accent

    @property
    def kind_token(self) -> str:
        return self.kind.token

    @property
    def filename(self) -> str:
        return f"{self.slug}_{self.kind_token}_{self.duration_seconds}s.mp4"

    @property
    def relative_dest(self) -> str:
        folder = channel_folder_name(self.channel_number)
        return f"{folder}/{self.filename}"

    @property
    def message(self) -> str:
        return self.kind.message_template.format(
            banner=channel_banner(self.channel_number),
            label=self.label,
        )

    @property
    def hue_degrees_per_second(self) -> float:
        return self.pack.hue_degrees_per_second * self.kind.hue_scale

    @property
    def fade_seconds(self) -> float:
        return self.kind.fade_seconds

    @property
    def text_y_offset(self) -> int:
        return self.kind.text_y_offset


def channel_folder_name(channel_number: int) -> str:
    width = CHANNEL_FOLDER_NUMBER_WIDTH
    return f"{CHANNEL_FOLDER_PREFIX}{channel_number:0{width}d}"


def channel_banner(channel_number: int) -> str:
    return f"CH {channel_number:0{CHANNEL_FOLDER_NUMBER_WIDTH}d}"


def planned_bumpers() -> tuple[BumperPlan, ...]:
    plans: list[BumperPlan] = []
    for pack in CHANNEL_PACKS:
        for kind in pack.kinds:
            for duration_seconds in pack.durations_seconds:
                plans.append(
                    BumperPlan(
                        pack=pack,
                        kind=kind,
                        duration_seconds=duration_seconds,
                    )
                )
    return tuple(plans)


def planned_byte_budget(plans: Sequence[BumperPlan]) -> int:
    return sum(plan.duration_seconds * BYTES_PER_SECOND_BUDGET for plan in plans)


def dest_path(dest_root: Path, plan: BumperPlan) -> Path:
    return dest_root / channel_folder_name(plan.channel_number) / plan.filename


def is_valid_existing(path: Path, probe_duration: DurationProber) -> bool:
    if not path.is_file():
        return False
    if path.stat().st_size <= 0:
        return False
    try:
        duration = probe_duration(path)
    except (OSError, ValueError, subprocess.SubprocessError, InterstitialBuildError):
        return False
    return math.isfinite(duration) and duration > 0


def ffmpeg_arguments(plan: BumperPlan, dest: Path) -> tuple[str, ...]:
    size = f"{VIDEO_WIDTH}x{VIDEO_HEIGHT}"
    color_source = (
        f"color=c={plan.color}:s={size}:d={plan.duration_seconds}:r={VIDEO_FRAME_RATE}"
    )
    audio_source = f"anullsrc=channel_layout=stereo:sample_rate={AUDIO_SAMPLE_RATE}"
    return (
        "ffmpeg",
        "-y",
        "-f",
        "lavfi",
        "-i",
        color_source,
        "-f",
        "lavfi",
        "-i",
        audio_source,
        "-vf",
        _video_filter(plan),
        "-c:v",
        "libx264",
        "-preset",
        "veryfast",
        "-crf",
        "28",
        "-pix_fmt",
        "yuv420p",
        "-c:a",
        "aac",
        "-b:a",
        "64k",
        "-shortest",
        "-movflags",
        "+faststart",
        str(dest),
    )


def _video_filter(plan: BumperPlan) -> str:
    fade_out_start = max(plan.duration_seconds - plan.fade_seconds, 0.0)
    offset = plan.text_y_offset
    y_sign = "+" if offset >= 0 else ""
    text_y = f"(h-text_h)/2{y_sign}{offset}"
    hue = f"{plan.hue_degrees_per_second:g}"
    return (
        f"hue=h={hue}*t:s={HUE_SATURATION},"
        f"fade=t=in:st=0:d={plan.fade_seconds},"
        f"fade=t=out:st={fade_out_start}:d={plan.fade_seconds},"
        f"drawtext=text='{plan.message}':fontsize={DRAWTEXT_FONT_SIZE}:"
        f"fontcolor=white:x=(w-text_w)/2:y={text_y}:box=1:"
        f"boxcolor={plan.accent}@{DRAWTEXT_BOX_ALPHA}:"
        f"boxborderw={DRAWTEXT_BOX_BORDER}"
    )


def main(
    argv: list[str] | None = None,
    *,
    run_ffmpeg: FfmpegRunner | None = None,
    probe_duration: DurationProber | None = None,
) -> int:
    args = _parse_args(argv)
    dest_root = args.dest.expanduser().resolve()
    plans = planned_bumpers()
    budget = planned_byte_budget(plans)
    if budget > MAX_TOTAL_BYTES:
        print(
            f"planned size {budget} exceeds {MAX_TOTAL_BYTES} byte cap",
            file=sys.stderr,
        )
        return FAILURE_EXIT_CODE
    if args.dry_run:
        _print_dry_run(dest_root, plans, budget)
        return SUCCESS_EXIT_CODE
    encoder = run_ffmpeg if run_ffmpeg is not None else _run_ffmpeg
    prober = probe_duration if probe_duration is not None else ffprobe_duration
    try:
        _render_plans(dest_root, plans, encoder, prober, force=args.force)
    except InterstitialBuildError as error:
        print(error, file=sys.stderr)
        return FAILURE_EXIT_CODE
    actual = _actual_bytes(dest_root, plans)
    if actual > MAX_TOTAL_BYTES:
        print(
            f"actual size {actual} exceeds {MAX_TOTAL_BYTES} byte cap",
            file=sys.stderr,
        )
        return FAILURE_EXIT_CODE
    print(f"done: {dest_root}")
    return SUCCESS_EXIT_CODE


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate local H.264+AAC channel bumpers with ffmpeg lavfi."
    )
    parser.add_argument(
        "--dest",
        type=Path,
        default=DEFAULT_DEST,
        help="root folder with ch01..ch04 (default: downloads/interstitials)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="print planned destination names and durations without writing",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="re-render every bumper even when a valid file already exists",
    )
    parser.add_argument(
        "--repair",
        action="store_true",
        help="regenerate missing or corrupt files only (same as the default)",
    )
    return parser.parse_args(argv)


def _print_dry_run(dest_root: Path, plans: Sequence[BumperPlan], budget: int) -> None:
    print(f"{len(plans)} bumpers, budget {_format_bytes(budget)}")
    for plan in plans:
        print(f"{dest_path(dest_root, plan)}\t{plan.duration_seconds}s\t{plan.label}")


def _render_plans(
    dest_root: Path,
    plans: Sequence[BumperPlan],
    run_ffmpeg: FfmpegRunner,
    probe_duration: DurationProber,
    *,
    force: bool,
) -> None:
    total = len(plans)
    for index, plan in enumerate(plans, start=1):
        dest = dest_path(dest_root, plan)
        prefix = f"[{index}/{total}]"
        if not force and is_valid_existing(dest, probe_duration):
            print(f"{prefix} skip {dest}")
            continue
        dest.parent.mkdir(parents=True, exist_ok=True)
        print(f"{prefix} write {dest}")
        try:
            run_ffmpeg(ffmpeg_arguments(plan, dest))
        except (OSError, subprocess.SubprocessError) as error:
            raise InterstitialBuildError(
                f"ffmpeg failed for {dest}: {error}"
            ) from error
        if not is_valid_existing(dest, probe_duration):
            raise InterstitialBuildError(f"wrote unreadable bumper: {dest}")


def _actual_bytes(dest_root: Path, plans: Sequence[BumperPlan]) -> int:
    total = 0
    for plan in plans:
        dest = dest_path(dest_root, plan)
        if dest.is_file():
            total += dest.stat().st_size
    return total


def _run_ffmpeg(argv: Sequence[str]) -> None:
    completed = subprocess.run(list(argv), check=False, capture_output=True, text=True)
    if completed.returncode != 0:
        detail = completed.stderr.strip() or f"exit {completed.returncode}"
        raise InterstitialBuildError(detail)


def ffprobe_duration(path: Path) -> float:
    completed = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "csv=p=0",
            str(path),
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0:
        raise InterstitialBuildError(completed.stderr.strip() or "ffprobe failed")
    try:
        duration = float(completed.stdout.strip())
    except ValueError as error:
        raise InterstitialBuildError("ffprobe duration is not a number") from error
    return duration


def _format_bytes(size_bytes: int) -> str:
    if size_bytes < 1024:
        return f"{size_bytes} B"
    kib = size_bytes / 1024
    if kib < 1024:
        return f"{kib:.1f} KiB"
    mib = kib / 1024
    if mib < 1024:
        return f"{mib:.1f} MiB"
    gib = mib / 1024
    return f"{gib:.2f} GiB"


if __name__ == "__main__":
    raise SystemExit(main())
