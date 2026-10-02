from collections.abc import Mapping
from pathlib import Path

import pytest

from tv90.adapters.fake_duration import FakeMediaProber
from tv90.adapters.file_duration_index import FileDurationIndex, write_duration_index
from tv90.application.indexing import index_library_durations
from tv90.domain.duration import DurationUnknownError, ProbeFailedError

KIPPER = "Kipper_S01E01.mp4"
OSWALD = "Oswald_S01E01.mp4"


def test_index_writes_json_using_fake_prober(tmp_path: Path) -> None:
    little = tmp_path / KIPPER
    oswald = tmp_path / OSWALD
    little.write_bytes(b"")
    oswald.write_bytes(b"")
    index_path = tmp_path / "duration-index.json"
    prober = FakeMediaProber({str(little): 125.5, str(oswald): 88.0})

    result = index_library_durations(
        (little, oswald), prober, index_path, write_duration_index
    )

    index = FileDurationIndex(index_path)
    assert index.duration_seconds(KIPPER) == 125.5
    assert index.duration_seconds(OSWALD) == 88.0
    assert result.written_filenames == (KIPPER, OSWALD)
    assert result.failed_filenames == ()


def test_index_does_not_use_real_ffprobe(tmp_path: Path) -> None:
    media = tmp_path / KIPPER
    media.write_bytes(b"")
    index_path = tmp_path / "duration-index.json"

    def forbidden_write(path: Path, durations: Mapping[str, float]) -> None:
        write_duration_index(path, durations)

    result = index_library_durations(
        (media,),
        FakeMediaProber({str(media): 40.0}),
        index_path,
        forbidden_write,
    )

    assert result.written_filenames == (KIPPER,)
    assert FileDurationIndex(index_path).duration_seconds(KIPPER) == 40.0


def test_index_omits_probe_failures_and_lists_them(tmp_path: Path) -> None:
    good = tmp_path / KIPPER
    bad = tmp_path / OSWALD
    good.write_bytes(b"")
    bad.write_bytes(b"")
    index_path = tmp_path / "duration-index.json"
    prober = FakeMediaProber({str(good): 12.0})

    result = index_library_durations(
        (good, bad), prober, index_path, write_duration_index
    )

    assert result.written_filenames == (KIPPER,)
    assert result.failed_filenames == (OSWALD,)
    assert FileDurationIndex(index_path).duration_seconds(KIPPER) == 12.0
    with pytest.raises(DurationUnknownError):
        FileDurationIndex(index_path).duration_seconds(OSWALD)


def test_index_keys_are_basenames_not_full_paths(tmp_path: Path) -> None:
    media = tmp_path / KIPPER
    media.write_bytes(b"")
    index_path = tmp_path / "duration-index.json"

    index_library_durations(
        (media,),
        FakeMediaProber({str(media): 9.0}),
        index_path,
        write_duration_index,
    )

    assert KIPPER in index_path.read_text(encoding="utf-8")
    assert str(tmp_path) not in index_path.read_text(encoding="utf-8")


def test_fake_prober_still_raises_for_missing_files() -> None:
    prober = FakeMediaProber({})

    try:
        prober.duration_seconds("/no/such.mp4")
    except ProbeFailedError as error:
        assert error.filename == "/no/such.mp4"
    else:
        raise AssertionError("expected ProbeFailedError")
