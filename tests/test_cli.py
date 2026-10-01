import io
import json
from collections.abc import Mapping
from pathlib import Path

import pytest

from tv90.adapters.fake_duration import FakeMediaProber
from tv90.adapters.fake_metadata import FakeEpisodeMetadataSource
from tv90.adapters.file_duration_index import FileDurationIndex, write_duration_index
from tv90.adapters.tvmaze_metadata import METADATA_CACHE_FILENAME
from tv90.interface.cli import main
from tv90.ports.duration import MediaProber
from tv90.ports.metadata import EpisodeMetadata, EpisodeMetadataSource, HttpGetter

SAMPLE_LIBRARY = Path(__file__).resolve().parent / "fixtures" / "sample_library"
HALLOWEEN_DATE = "2024-10-31"
JULY_DATE = "2024-07-15"


LITTLE_BEAR_ONE_JSON = json.dumps(
    [
        {
            "name": "What Will Little Bear Wear?",
            "season": 1,
            "number": 1,
            "summary": None,
        }
    ]
)


class RecordingHttpGetter:
    def __init__(self, body: str) -> None:
        self.body = body
        self.calls: list[tuple[str, dict[str, str]]] = []

    def __call__(self, url: str, headers: Mapping[str, str]) -> str:
        self.calls.append((url, dict(headers)))
        return self.body


def _run(
    argv: list[str],
    environ: dict[str, str] | None = None,
    metadata_source: EpisodeMetadataSource | None = None,
    media_prober: MediaProber | None = None,
    http_get: HttpGetter | None = None,
) -> tuple[int, str]:
    stdout = io.StringIO()
    exit_code = main(
        argv,
        {} if environ is None else environ,
        stdout,
        metadata_source=metadata_source,
        media_prober=media_prober,
        http_get=http_get,
    )
    return exit_code, stdout.getvalue()


def _fingerprint(directory: Path) -> dict[str, tuple[int, int, bytes]]:
    return {
        path.name: (path.stat().st_size, path.stat().st_mtime_ns, path.read_bytes())
        for path in sorted(directory.iterdir())
        if path.is_file()
    }


def test_cli_missing_date_returns_error() -> None:
    exit_code, output = _run(["simulate"])

    assert exit_code != 0
    assert "--date" in output


def test_cli_invalid_command_returns_error() -> None:
    exit_code, output = _run(["not-a-command"])

    assert exit_code != 0
    assert "not-a-command" in output


def test_cli_invalid_date_returns_error() -> None:
    exit_code, output = _run(["simulate", "--date", "31-10-2024"])

    assert exit_code != 0
    assert "YYYY-MM-DD" in output


def test_cli_halloween_sample_library_prints_ch01_and_ch04() -> None:
    exit_code, output = _run(
        ["simulate", "--date", HALLOWEEN_DATE, "--library", str(SAMPLE_LIBRARY)]
    )

    assert exit_code == 0
    assert "CH 01" in output
    assert "CH 04" in output
    assert "6:30 AM" in output
    assert "menu" not in output.lower()
    assert "up next" not in output.lower()


def test_cli_does_not_write_to_the_library_directory(tmp_path: Path) -> None:
    (tmp_path / "LittleBear_S01E01.mp4").write_bytes(b"")
    (tmp_path / "Oswald_S01E01.mp4").write_bytes(b"")
    (tmp_path / "Harry_S01E01.mp4").write_bytes(b"")
    before = _fingerprint(tmp_path)

    exit_code, output = _run(
        ["simulate", "--date", JULY_DATE, "--library", str(tmp_path)]
    )

    assert exit_code == 0
    assert output != ""
    assert _fingerprint(tmp_path) == before


def test_cli_uses_injected_environ_not_process_environment(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("TV90_SIGN_ON", "6.5")
    (tmp_path / "LittleBear_S01E01.mp4").write_bytes(b"")

    exit_code, output = _run(
        ["simulate", "--date", JULY_DATE, "--library", str(tmp_path)],
        {"TV90_SIGN_ON": "10.0"},
    )

    assert exit_code == 0
    assert "10:00 AM" in output
    assert "6:30 AM" not in output


def test_cli_reads_duration_index_when_present(tmp_path: Path) -> None:
    filename = "LittleBear_S01E01.mp4"
    (tmp_path / filename).write_bytes(b"")
    write_duration_index(tmp_path / "duration-index.json", {filename: 3600.0})

    exit_code, output = _run(
        ["simulate", "--date", JULY_DATE, "--library", str(tmp_path)]
    )

    assert exit_code == 0
    assert "6:30 AM" in output
    assert "7:30 AM" in output


def test_cli_missing_library_directory_returns_error(tmp_path: Path) -> None:
    missing = tmp_path / "no-such-library"

    exit_code, output = _run(
        ["simulate", "--date", JULY_DATE, "--library", str(missing)]
    )

    assert exit_code != 0
    assert str(missing) in output


def test_cli_tag_dry_run_does_not_write_metadata_cache(tmp_path: Path) -> None:
    (tmp_path / "LittleBear_S01E01.mp4").write_bytes(b"")
    http = RecordingHttpGetter(LITTLE_BEAR_ONE_JSON)

    exit_code, _output = _run(["tag", "--library", str(tmp_path)], http_get=http)

    assert exit_code == 0
    assert http.calls
    assert not (tmp_path / METADATA_CACHE_FILENAME).exists()


def test_cli_tag_apply_may_write_metadata_cache(tmp_path: Path) -> None:
    (tmp_path / "LittleBear_S01E01.mp4").write_bytes(b"")
    http = RecordingHttpGetter(LITTLE_BEAR_ONE_JSON)

    exit_code, _output = _run(
        ["tag", "--apply", "--library", str(tmp_path)], http_get=http
    )

    assert exit_code == 0
    assert http.calls
    assert (tmp_path / METADATA_CACHE_FILENAME).is_file()


def test_cli_tag_dry_run_renames_nothing(tmp_path: Path) -> None:
    path = tmp_path / "LittleBear_S01E01.mp4"
    path.write_bytes(b"video")
    source = FakeEpisodeMetadataSource(
        {("LittleBear", 1, 1): EpisodeMetadata("Snow Day", "ice on the sled")}
    )

    exit_code, output = _run(
        ["tag", "--library", str(tmp_path)], metadata_source=source
    )

    assert exit_code == 0
    assert path.exists()
    assert path.read_bytes() == b"video"
    assert "LittleBear_S01E01.mp4" in output
    assert "WINTER" in output
    assert "Snow Day" in output


def test_cli_tag_apply_renames_correctly(tmp_path: Path) -> None:
    path = tmp_path / "LittleBear_S01E01.mp4"
    path.write_bytes(b"video")
    source = FakeEpisodeMetadataSource(
        {("LittleBear", 1, 1): EpisodeMetadata("Snow Day", "ice on the sled")}
    )

    exit_code, output = _run(
        ["tag", "--apply", "--library", str(tmp_path)], metadata_source=source
    )

    assert exit_code == 0
    assert not path.exists()
    renamed = tmp_path / "LittleBear_S01E01_WINTER.mp4"
    assert renamed.exists()
    assert renamed.read_bytes() == b"video"
    assert "WINTER" in output


def test_cli_tag_keeps_existing_morning_when_description_is_bedtime(
    tmp_path: Path,
) -> None:
    path = tmp_path / "LittleBear_S01E01_MORNING.mp4"
    path.write_bytes(b"")
    source = FakeEpisodeMetadataSource(
        {("LittleBear", 1, 1): EpisodeMetadata("Moon", "bedtime sleep stars")}
    )

    exit_code, output = _run(
        ["tag", "--apply", "--library", str(tmp_path)], metadata_source=source
    )

    assert exit_code == 0
    assert path.exists()
    assert "MORNING" in output
    assert "NIGHT" not in output


def test_cli_tag_lists_not_found_at_the_end(tmp_path: Path) -> None:
    missing = tmp_path / "Harry_S01E01.mp4"
    missing.write_bytes(b"")
    source = FakeEpisodeMetadataSource({})

    exit_code, output = _run(
        ["tag", "--apply", "--library", str(tmp_path)], metadata_source=source
    )

    assert exit_code == 0
    assert missing.exists()
    assert "Not found:" in output
    assert "Harry_S01E01.mp4" in output.split("Not found:")[1]


def test_cli_tag_unmatched_stays_untagged(tmp_path: Path) -> None:
    path = tmp_path / "Oswald_S01E01.mp4"
    path.write_bytes(b"")
    source = FakeEpisodeMetadataSource(
        {("Oswald", 1, 1): EpisodeMetadata("Friends", "a quiet walk")}
    )

    exit_code, output = _run(
        ["tag", "--library", str(tmp_path)], metadata_source=source
    )

    assert exit_code == 0
    assert path.exists()
    assert "(untagged)" in output


def test_cli_index_writes_json_without_ffprobe(tmp_path: Path) -> None:
    filename = "LittleBear_S01E01.mp4"
    media = tmp_path / filename
    media.write_bytes(b"")
    prober = FakeMediaProber({str(media): 99.5})

    exit_code, output = _run(["index", "--library", str(tmp_path)], media_prober=prober)

    assert exit_code == 0
    index_path = tmp_path / "duration-index.json"
    assert index_path.is_file()
    assert FileDurationIndex(index_path).duration_seconds(filename) == 99.5
    assert "Wrote 1 durations" in output
    assert str(index_path) in output


def test_cli_index_lists_probe_failures(tmp_path: Path) -> None:
    good = tmp_path / "LittleBear_S01E01.mp4"
    bad = tmp_path / "Oswald_S01E01.mp4"
    good.write_bytes(b"")
    bad.write_bytes(b"")
    prober = FakeMediaProber({str(good): 10.0})

    exit_code, output = _run(["index", "--library", str(tmp_path)], media_prober=prober)

    assert exit_code == 0
    assert "Failed:" in output
    assert "Oswald_S01E01.mp4" in output.split("Failed:")[1]
    assert (
        FileDurationIndex(tmp_path / "duration-index.json").duration_seconds(
            "LittleBear_S01E01.mp4"
        )
        == 10.0
    )


def test_cli_tag_missing_library_directory_returns_error(tmp_path: Path) -> None:
    missing = tmp_path / "no-such-library"
    source = FakeEpisodeMetadataSource({})

    exit_code, output = _run(["tag", "--library", str(missing)], metadata_source=source)

    assert exit_code != 0
    assert str(missing) in output
