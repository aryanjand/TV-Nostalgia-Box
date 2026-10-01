import io
from pathlib import Path

import pytest

from tv90.adapters.file_duration_index import write_duration_index
from tv90.interface.cli import main

SAMPLE_LIBRARY = Path(__file__).resolve().parent / "fixtures" / "sample_library"
HALLOWEEN_DATE = "2024-10-31"
JULY_DATE = "2024-07-15"


def _run(argv: list[str], environ: dict[str, str] | None = None) -> tuple[int, str]:
    stdout = io.StringIO()
    exit_code = main(argv, {} if environ is None else environ, stdout)
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
