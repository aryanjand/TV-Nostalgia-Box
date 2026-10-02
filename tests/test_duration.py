import json
import math
from pathlib import Path

import pytest

from tv90.adapters.fake_duration import FakeDurationIndex, FakeMediaProber
from tv90.adapters.ffprobe_prober import (
    FfprobeMediaProber,
    ffprobe_arguments,
)
from tv90.adapters.file_duration_index import (
    DurationIndexUnreadableError,
    FileDurationIndex,
    write_duration_index,
)
from tv90.application.duration_lookup import DurationLookup
from tv90.domain.duration import (
    CorruptDurationError,
    DurationUnknownError,
    ProbeFailedError,
    require_positive_duration,
)
from tv90.ports import DurationIndex, MediaProber

KIPPER_FILENAME = "Kipper_S01E01.mp4"
OSWALD_FILENAME = "Oswald_S01E09_NIGHT.mp4"


class ForbiddenMediaProber:
    def duration_seconds(self, filename: str) -> float:
        raise AssertionError(f"must not probe {filename} when the index has an answer")


def test_require_positive_duration_returns_finite_positive_seconds() -> None:
    assert require_positive_duration(KIPPER_FILENAME, 12.5) == 12.5


def test_require_positive_duration_coerces_int_to_float() -> None:
    duration_seconds = require_positive_duration(KIPPER_FILENAME, 10)
    assert duration_seconds == 10.0
    assert isinstance(duration_seconds, float)


@pytest.mark.parametrize(
    "duration_seconds",
    [
        pytest.param(0.0, id="zero"),
        pytest.param(-1.0, id="negative"),
        pytest.param(math.nan, id="nan"),
        pytest.param(math.inf, id="inf"),
        pytest.param(-math.inf, id="negative-inf"),
    ],
)
def test_require_positive_duration_rejects_non_positive(
    duration_seconds: float,
) -> None:
    with pytest.raises(CorruptDurationError):
        require_positive_duration(KIPPER_FILENAME, duration_seconds)


def test_fake_duration_index_returns_mapped_seconds() -> None:
    index = FakeDurationIndex({KIPPER_FILENAME: 120.5})

    assert index.duration_seconds(KIPPER_FILENAME) == 120.5


def test_fake_duration_index_raises_when_filename_is_missing() -> None:
    index = FakeDurationIndex({})

    with pytest.raises(DurationUnknownError) as caught:
        index.duration_seconds(KIPPER_FILENAME)

    assert caught.value.filename == KIPPER_FILENAME


def test_fake_duration_index_raises_on_zero_duration() -> None:
    index = FakeDurationIndex({KIPPER_FILENAME: 0.0})

    with pytest.raises(CorruptDurationError):
        index.duration_seconds(KIPPER_FILENAME)


def test_fake_media_prober_returns_mapped_seconds() -> None:
    prober = FakeMediaProber({KIPPER_FILENAME: 88.0})

    assert prober.duration_seconds(KIPPER_FILENAME) == 88.0


def test_fake_media_prober_raises_when_filename_is_missing() -> None:
    prober = FakeMediaProber({})

    with pytest.raises(ProbeFailedError) as caught:
        prober.duration_seconds(KIPPER_FILENAME)

    assert caught.value.filename == KIPPER_FILENAME


def test_fake_media_prober_raises_on_negative_duration() -> None:
    prober = FakeMediaProber({KIPPER_FILENAME: -3.0})

    with pytest.raises(CorruptDurationError):
        prober.duration_seconds(KIPPER_FILENAME)


def test_lookup_index_hit_does_not_probe() -> None:
    lookup = DurationLookup(
        duration_index=FakeDurationIndex({KIPPER_FILENAME: 42.0}),
        media_prober=ForbiddenMediaProber(),
    )

    assert lookup.duration_seconds(KIPPER_FILENAME) == 42.0


def test_lookup_index_miss_probes_in_memory() -> None:
    lookup = DurationLookup(
        duration_index=FakeDurationIndex({}),
        media_prober=FakeMediaProber({KIPPER_FILENAME: 77.25}),
    )

    assert lookup.duration_seconds(KIPPER_FILENAME) == 77.25


def test_lookup_corrupt_index_duration_does_not_probe() -> None:
    lookup = DurationLookup(
        duration_index=FakeDurationIndex({KIPPER_FILENAME: 0.0}),
        media_prober=ForbiddenMediaProber(),
    )

    with pytest.raises(CorruptDurationError):
        lookup.duration_seconds(KIPPER_FILENAME)


def test_lookup_probe_failure_propagates() -> None:
    lookup = DurationLookup(
        duration_index=FakeDurationIndex({}),
        media_prober=FakeMediaProber({}),
    )

    with pytest.raises(ProbeFailedError):
        lookup.duration_seconds(KIPPER_FILENAME)


def test_lookup_miss_does_not_write_index_file(tmp_path: Path) -> None:
    index_path = tmp_path / "durations.json"
    write_duration_index(index_path, {OSWALD_FILENAME: 90.0})
    before = index_path.read_bytes()
    lookup = DurationLookup(
        duration_index=FileDurationIndex(index_path),
        media_prober=FakeMediaProber({KIPPER_FILENAME: 120.5}),
    )

    seconds = lookup.duration_seconds(KIPPER_FILENAME)

    assert seconds == 120.5
    assert index_path.read_bytes() == before
    assert KIPPER_FILENAME not in json.loads(before)


def test_file_duration_index_reads_json_fixture(tmp_path: Path) -> None:
    index_path = tmp_path / "durations.json"
    index_path.write_text(
        json.dumps({KIPPER_FILENAME: 300, OSWALD_FILENAME: 90.5}),
        encoding="utf-8",
    )
    index = FileDurationIndex(index_path)

    assert index.duration_seconds(KIPPER_FILENAME) == 300.0
    assert index.duration_seconds(OSWALD_FILENAME) == 90.5


def test_file_duration_index_raises_when_filename_is_missing(tmp_path: Path) -> None:
    index_path = tmp_path / "durations.json"
    write_duration_index(index_path, {OSWALD_FILENAME: 90.0})
    index = FileDurationIndex(index_path)

    with pytest.raises(DurationUnknownError):
        index.duration_seconds(KIPPER_FILENAME)


def test_file_duration_index_raises_on_zero_in_file(tmp_path: Path) -> None:
    index_path = tmp_path / "durations.json"
    index_path.write_text(
        json.dumps({KIPPER_FILENAME: 0}),
        encoding="utf-8",
    )
    index = FileDurationIndex(index_path)

    with pytest.raises(CorruptDurationError):
        index.duration_seconds(KIPPER_FILENAME)


def test_write_duration_index_round_trips_through_file_index(tmp_path: Path) -> None:
    index_path = tmp_path / "durations.json"
    write_duration_index(
        index_path,
        {KIPPER_FILENAME: 12.5, OSWALD_FILENAME: 40.0},
    )
    index = FileDurationIndex(index_path)

    assert index.duration_seconds(KIPPER_FILENAME) == 12.5
    assert index.duration_seconds(OSWALD_FILENAME) == 40.0


def test_write_duration_index_rejects_non_positive_duration(tmp_path: Path) -> None:
    index_path = tmp_path / "durations.json"

    with pytest.raises(CorruptDurationError):
        write_duration_index(index_path, {KIPPER_FILENAME: 0.0})
    assert not index_path.exists()


def test_file_duration_index_rejects_missing_file(tmp_path: Path) -> None:
    index = FileDurationIndex(tmp_path / "missing.json")

    with pytest.raises(DurationIndexUnreadableError):
        index.duration_seconds(KIPPER_FILENAME)


def test_file_duration_index_rejects_invalid_json(tmp_path: Path) -> None:
    index_path = tmp_path / "durations.json"
    index_path.write_text("{not json", encoding="utf-8")
    index = FileDurationIndex(index_path)

    with pytest.raises(DurationIndexUnreadableError):
        index.duration_seconds(KIPPER_FILENAME)


def test_file_duration_index_rejects_json_array(tmp_path: Path) -> None:
    index_path = tmp_path / "durations.json"
    index_path.write_text("[1, 2]", encoding="utf-8")
    index = FileDurationIndex(index_path)

    with pytest.raises(DurationIndexUnreadableError):
        index.duration_seconds(KIPPER_FILENAME)


def test_file_duration_index_rejects_non_numeric_values(tmp_path: Path) -> None:
    index_path = tmp_path / "durations.json"
    index_path.write_text(
        json.dumps({KIPPER_FILENAME: "12.5"}),
        encoding="utf-8",
    )
    index = FileDurationIndex(index_path)

    with pytest.raises(DurationIndexUnreadableError):
        index.duration_seconds(KIPPER_FILENAME)


def test_file_duration_index_rejects_boolean_values(tmp_path: Path) -> None:
    index_path = tmp_path / "durations.json"
    index_path.write_text(
        json.dumps({KIPPER_FILENAME: True}),
        encoding="utf-8",
    )
    index = FileDurationIndex(index_path)

    with pytest.raises(DurationIndexUnreadableError):
        index.duration_seconds(KIPPER_FILENAME)


def test_ffprobe_arguments_match_documented_invocation() -> None:
    assert ffprobe_arguments(KIPPER_FILENAME) == (
        "ffprobe",
        "-v",
        "quiet",
        "-print_format",
        "json",
        "-show_format",
        "--",
        KIPPER_FILENAME,
    )


def test_ffprobe_prober_parses_string_duration() -> None:
    def run_command(arguments: tuple[str, ...]) -> str:
        assert arguments == ffprobe_arguments(KIPPER_FILENAME)
        return json.dumps({"format": {"duration": "123.456"}})

    prober = FfprobeMediaProber(run_command)

    assert prober.duration_seconds(KIPPER_FILENAME) == 123.456


def test_ffprobe_prober_parses_numeric_duration() -> None:
    def run_command(_arguments: tuple[str, ...]) -> str:
        return json.dumps({"format": {"duration": 88}})

    prober = FfprobeMediaProber(run_command)

    assert prober.duration_seconds(KIPPER_FILENAME) == 88.0


def test_ffprobe_prober_raises_when_command_fails() -> None:
    def run_command(_arguments: tuple[str, ...]) -> str:
        raise OSError("ffprobe missing")

    prober = FfprobeMediaProber(run_command)

    with pytest.raises(ProbeFailedError):
        prober.duration_seconds(KIPPER_FILENAME)


def test_ffprobe_prober_raises_on_invalid_json() -> None:
    prober = FfprobeMediaProber(lambda _arguments: "not-json")

    with pytest.raises(ProbeFailedError):
        prober.duration_seconds(KIPPER_FILENAME)


def test_ffprobe_prober_raises_on_json_array() -> None:
    prober = FfprobeMediaProber(lambda _arguments: "[1]")

    with pytest.raises(ProbeFailedError):
        prober.duration_seconds(KIPPER_FILENAME)


def test_ffprobe_prober_raises_when_format_is_missing() -> None:
    prober = FfprobeMediaProber(lambda _arguments: json.dumps({"streams": []}))

    with pytest.raises(ProbeFailedError):
        prober.duration_seconds(KIPPER_FILENAME)


def test_ffprobe_prober_raises_when_duration_is_missing() -> None:
    prober = FfprobeMediaProber(lambda _arguments: json.dumps({"format": {}}))

    with pytest.raises(ProbeFailedError):
        prober.duration_seconds(KIPPER_FILENAME)


def test_ffprobe_prober_raises_when_duration_is_not_numeric() -> None:
    prober = FfprobeMediaProber(
        lambda _arguments: json.dumps({"format": {"duration": "N/A"}})
    )

    with pytest.raises(ProbeFailedError):
        prober.duration_seconds(KIPPER_FILENAME)


def test_ffprobe_prober_raises_when_duration_is_an_object() -> None:
    prober = FfprobeMediaProber(
        lambda _arguments: json.dumps({"format": {"duration": {"seconds": 1}}})
    )

    with pytest.raises(ProbeFailedError):
        prober.duration_seconds(KIPPER_FILENAME)


def test_ffprobe_prober_raises_when_duration_is_boolean() -> None:
    prober = FfprobeMediaProber(
        lambda _arguments: json.dumps({"format": {"duration": True}})
    )

    with pytest.raises(ProbeFailedError):
        prober.duration_seconds(KIPPER_FILENAME)


def test_ffprobe_prober_raises_on_zero_duration() -> None:
    prober = FfprobeMediaProber(
        lambda _arguments: json.dumps({"format": {"duration": "0"}})
    )

    with pytest.raises(CorruptDurationError):
        prober.duration_seconds(KIPPER_FILENAME)


def test_duration_adapters_satisfy_ports(tmp_path: Path) -> None:
    index_path = tmp_path / "durations.json"
    write_duration_index(index_path, {KIPPER_FILENAME: 15.0})
    indexes: list[DurationIndex] = [
        FakeDurationIndex({KIPPER_FILENAME: 15.0}),
        FileDurationIndex(index_path),
    ]
    probers: list[MediaProber] = [
        FakeMediaProber({KIPPER_FILENAME: 15.0}),
        FfprobeMediaProber(
            lambda _arguments: json.dumps({"format": {"duration": "15.0"}})
        ),
    ]

    for index in indexes:
        assert index.duration_seconds(KIPPER_FILENAME) == 15.0
    for prober in probers:
        assert prober.duration_seconds(KIPPER_FILENAME) == 15.0
