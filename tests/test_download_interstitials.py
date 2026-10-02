from __future__ import annotations

import importlib.util
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "download-interstitials.py"

CARTOON_SLUGS = ("kipper", "oswald", "harry")
CARTOON_FOLDERS = ("ch01", "ch02", "ch03")


def _load_script() -> Any:
    spec = importlib.util.spec_from_file_location("download_interstitials", SCRIPT)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _kind_tokens(relatives: set[str], folder: str, slug: str) -> set[str]:
    tokens: set[str] = set()
    prefix = f"{folder}/{slug}_"
    suffix = "s.mp4"
    for name in relatives:
        if not name.startswith(prefix) or not name.endswith(suffix):
            continue
        middle = name[len(prefix) : -len(suffix)]
        kind, _duration = middle.rsplit("_", 1)
        tokens.add(kind)
    return tokens


def test_planner_lays_out_channel_folders_and_durations() -> None:
    script = _load_script()
    plans = script.planned_bumpers()
    labels = {pack.label for pack in script.CHANNEL_PACKS}

    assert labels == {"Kipper", "Oswald", "Harry", "Holiday"}
    assert script.DURATIONS_SECONDS == (16, 19, 23, 28, 32)
    assert min(script.DURATIONS_SECONDS) >= 15
    assert max(script.DURATIONS_SECONDS) > 30
    relatives = {plan.relative_dest for plan in plans}
    assert any(name.startswith("ch01/") for name in relatives)
    assert any(name.startswith("ch02/") for name in relatives)
    assert any(name.startswith("ch03/") for name in relatives)
    assert any(name.startswith("ch04/") for name in relatives)
    assert any("kipper" in name for name in relatives)
    assert any("oswald" in name for name in relatives)
    assert any("harry" in name for name in relatives)
    assert any("holiday" in name for name in relatives)
    for folder, slug in zip(CARTOON_FOLDERS, CARTOON_SLUGS, strict=True):
        kinds = _kind_tokens(relatives, folder, slug)
        assert len(kinds) >= 2


def test_size_cap_is_two_and_a_half_gigabytes() -> None:
    script = _load_script()

    assert script.MAX_TOTAL_BYTES == 2_500_000_000
    assert script.planned_byte_budget(script.planned_bumpers()) < script.MAX_TOTAL_BYTES


def _video_filter(script: Any, plan: Any) -> str:
    argv = script.ffmpeg_arguments(plan, Path("bumper.mp4"))
    return str(argv[argv.index("-vf") + 1])


def test_cartoon_packs_animate_and_are_not_duration_clones() -> None:
    script = _load_script()
    kipper = next(plan for plan in script.planned_bumpers() if plan.slug == "kipper")
    oswald = next(plan for plan in script.planned_bumpers() if plan.slug == "oswald")
    harry = next(plan for plan in script.planned_bumpers() if plan.slug == "harry")
    kipper_filter = _video_filter(script, kipper)
    oswald_filter = _video_filter(script, oswald)
    harry_filter = _video_filter(script, harry)

    assert kipper.color != oswald.color
    assert oswald.color != harry.color
    assert kipper.color != harry.color
    assert kipper.accent != oswald.accent
    assert oswald.accent != harry.accent
    assert kipper.accent != harry.accent
    assert "hue=" in kipper_filter
    assert "fade=" in kipper_filter
    assert "drawtext=" in kipper_filter
    assert kipper_filter != oswald_filter
    assert oswald_filter != harry_filter
    assert kipper_filter != harry_filter
    assert "Kipper" in kipper_filter
    assert "Oswald" in oswald_filter
    assert "Harry" in harry_filter


def test_dry_run_prints_dest_names_without_writing(tmp_path: Path, capsys: Any) -> None:
    script = _load_script()
    dest = tmp_path / "interstitials"
    writes: list[tuple[str, ...]] = []

    def run_ffmpeg(argv: Sequence[str]) -> None:
        writes.append(tuple(argv))

    def probe(_path: Path) -> float:
        return 16.0

    exit_code = script.main(
        ["--dest", str(dest), "--dry-run"],
        run_ffmpeg=run_ffmpeg,
        probe_duration=probe,
    )
    output = capsys.readouterr().out

    assert exit_code == 0
    assert writes == []
    assert not dest.exists()
    assert "16s" in output
    assert "Kipper" in output


def test_write_then_skip_valid_existing(tmp_path: Path, capsys: Any) -> None:
    script = _load_script()
    dest = tmp_path / "interstitials"
    encoded: list[str] = []

    def run_ffmpeg(argv: Sequence[str]) -> None:
        path = Path(argv[-1])
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"video")
        encoded.append(path.name)

    def probe(_path: Path) -> float:
        return 16.0

    exit_code = script.main(
        ["--dest", str(dest)],
        run_ffmpeg=run_ffmpeg,
        probe_duration=probe,
    )
    first_count = len(encoded)
    capsys.readouterr()

    exit_code_again = script.main(
        ["--dest", str(dest)],
        run_ffmpeg=run_ffmpeg,
        probe_duration=probe,
    )
    output = capsys.readouterr().out

    assert exit_code == 0
    assert exit_code_again == 0
    assert first_count == len(script.planned_bumpers())
    assert len(encoded) == first_count
    assert "skip" in output
    assert (dest / "ch01").is_dir()
    assert (dest / "ch02").is_dir()
    assert (dest / "ch03").is_dir()
    assert list((dest / "ch01").glob("*.mp4"))
    assert list((dest / "ch02").glob("*.mp4"))
    assert list((dest / "ch03").glob("*.mp4"))


def test_force_rerenders_valid_files(tmp_path: Path) -> None:
    script = _load_script()
    dest = tmp_path / "interstitials"
    encoded: list[str] = []

    def run_ffmpeg(argv: Sequence[str]) -> None:
        path = Path(argv[-1])
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"video")
        encoded.append(path.name)

    def probe(_path: Path) -> float:
        return 16.0

    script.main(
        ["--dest", str(dest)],
        run_ffmpeg=run_ffmpeg,
        probe_duration=probe,
    )
    first_count = len(encoded)
    script.main(
        ["--dest", str(dest), "--force"],
        run_ffmpeg=run_ffmpeg,
        probe_duration=probe,
    )

    assert len(encoded) == first_count * 2


def test_repair_rewrites_empty_and_unreadable(tmp_path: Path) -> None:
    script = _load_script()
    dest = tmp_path / "interstitials"
    plan = script.planned_bumpers()[0]
    broken = script.dest_path(dest, plan)
    broken.parent.mkdir(parents=True)
    broken.write_bytes(b"")
    encoded: list[Path] = []

    def run_ffmpeg(argv: Sequence[str]) -> None:
        path = Path(argv[-1])
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"video")
        encoded.append(path)

    def probe(path: Path) -> float:
        if path.stat().st_size <= 0:
            raise script.InterstitialBuildError("empty")
        return 16.0

    exit_code = script.main(
        ["--dest", str(dest), "--repair"],
        run_ffmpeg=run_ffmpeg,
        probe_duration=probe,
    )

    assert exit_code == 0
    assert broken in encoded
    assert broken.read_bytes() == b"video"


def test_skip_rejects_non_finite_probe(tmp_path: Path) -> None:
    script = _load_script()
    dest = tmp_path / "file.mp4"
    dest.write_bytes(b"video")

    def finite(_path: Path) -> float:
        return 16.0

    def zero(_path: Path) -> float:
        return 0.0

    def infinite(_path: Path) -> float:
        return float("inf")

    assert script.is_valid_existing(dest, infinite) is False
    assert script.is_valid_existing(dest, zero) is False
    assert script.is_valid_existing(dest, finite) is True
