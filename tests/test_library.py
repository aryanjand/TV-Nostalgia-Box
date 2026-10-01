from pathlib import Path

import pytest

from tv90.adapters.fake_library import FakeLibrarySource
from tv90.adapters.filesystem_library import (
    FilesystemLibrarySource,
    LibraryDirectoryError,
)
from tv90.domain.filename import parse_filename
from tv90.ports import LibrarySource


def test_fake_library_returns_injected_episodes() -> None:
    morning = parse_filename("LittleBear_S01E01_MORNING.mp4")
    night = parse_filename("Oswald_S01E09_NIGHT.mp4")
    library = FakeLibrarySource(episodes=(morning, night))

    assert library.episodes() == (morning, night)
    assert library.unrecognized_filenames() == ()


def test_fake_library_returns_injected_unrecognized_names() -> None:
    library = FakeLibrarySource(unrecognized_filenames=("garbage.mp4", "notes.mkv"))

    assert library.episodes() == ()
    assert library.unrecognized_filenames() == ("garbage.mp4", "notes.mkv")


def test_filesystem_library_lists_flat_media_files(tmp_path: Path) -> None:
    (tmp_path / "Oswald_S01E09_NIGHT.mp4").write_bytes(b"")
    (tmp_path / "LittleBear_S01E01.mp4").write_bytes(b"")

    library = FilesystemLibrarySource(tmp_path)
    episodes = library.episodes()

    assert [episode.filename for episode in episodes] == [
        "LittleBear_S01E01.mp4",
        "Oswald_S01E09_NIGHT.mp4",
    ]
    assert library.unrecognized_filenames() == ()


def test_filesystem_library_skips_hidden_files(tmp_path: Path) -> None:
    (tmp_path / "LittleBear_S01E01.mp4").write_bytes(b"")
    (tmp_path / ".Harry_S01E01.mp4").write_bytes(b"")

    library = FilesystemLibrarySource(tmp_path)

    assert [episode.filename for episode in library.episodes()] == [
        "LittleBear_S01E01.mp4"
    ]
    assert library.unrecognized_filenames() == ()


def test_filesystem_library_does_not_recurse_into_subfolders(tmp_path: Path) -> None:
    (tmp_path / "LittleBear_S01E01.mp4").write_bytes(b"")
    nested = tmp_path / "nested"
    nested.mkdir()
    (nested / "Oswald_S01E01.mp4").write_bytes(b"")

    library = FilesystemLibrarySource(tmp_path)

    assert [episode.filename for episode in library.episodes()] == [
        "LittleBear_S01E01.mp4"
    ]


def test_filesystem_library_collects_malformed_media_as_unrecognized(
    tmp_path: Path,
) -> None:
    (tmp_path / "LittleBear_S01E01.mp4").write_bytes(b"")
    (tmp_path / "garbage.mp4").write_bytes(b"")
    (tmp_path / "Holiday_S01E01.mkv").write_bytes(b"")

    library = FilesystemLibrarySource(tmp_path)

    assert [episode.filename for episode in library.episodes()] == [
        "LittleBear_S01E01.mp4"
    ]
    assert library.unrecognized_filenames() == ("Holiday_S01E01.mkv", "garbage.mp4")


def test_filesystem_library_ignores_non_media_files(tmp_path: Path) -> None:
    (tmp_path / "LittleBear_S01E01.mp4").write_bytes(b"")
    (tmp_path / "notes.txt").write_bytes(b"")
    (tmp_path / "readme").write_bytes(b"")

    library = FilesystemLibrarySource(tmp_path)

    assert [episode.filename for episode in library.episodes()] == [
        "LittleBear_S01E01.mp4"
    ]
    assert library.unrecognized_filenames() == ()


def test_filesystem_library_accepts_mp4_mkv_avi_case_insensitively(
    tmp_path: Path,
) -> None:
    (tmp_path / "LittleBear_S01E01.MP4").write_bytes(b"")
    (tmp_path / "Oswald_S01E02.mkv").write_bytes(b"")
    (tmp_path / "Harry_S01E03.AVI").write_bytes(b"")

    library = FilesystemLibrarySource(tmp_path)
    filenames = [episode.filename for episode in library.episodes()]

    assert filenames == [
        "Harry_S01E03.AVI",
        "LittleBear_S01E01.MP4",
        "Oswald_S01E02.mkv",
    ]


def test_filesystem_library_skips_directories_named_like_media(tmp_path: Path) -> None:
    (tmp_path / "LittleBear_S01E01.mp4").mkdir()
    (tmp_path / "Oswald_S01E01.mp4").write_bytes(b"")

    library = FilesystemLibrarySource(tmp_path)

    assert [episode.filename for episode in library.episodes()] == ["Oswald_S01E01.mp4"]


def test_filesystem_library_does_not_write(tmp_path: Path) -> None:
    media = tmp_path / "LittleBear_S01E01.mp4"
    media.write_bytes(b"")
    before_names = sorted(path.name for path in tmp_path.iterdir())
    before_mtime = media.stat().st_mtime_ns
    before_bytes = media.read_bytes()

    library = FilesystemLibrarySource(tmp_path)
    library.episodes()
    library.unrecognized_filenames()

    assert sorted(path.name for path in tmp_path.iterdir()) == before_names
    assert media.stat().st_mtime_ns == before_mtime
    assert media.read_bytes() == before_bytes


def test_filesystem_library_empty_directory_has_no_episodes(tmp_path: Path) -> None:
    library = FilesystemLibrarySource(tmp_path)

    assert library.episodes() == ()
    assert library.unrecognized_filenames() == ()


def test_filesystem_library_rejects_missing_directory(tmp_path: Path) -> None:
    missing = tmp_path / "missing"

    library = FilesystemLibrarySource(missing)

    with pytest.raises(LibraryDirectoryError):
        library.episodes()


def test_filesystem_library_rejects_file_path(tmp_path: Path) -> None:
    file_path = tmp_path / "not-a-directory"
    file_path.write_bytes(b"")

    library = FilesystemLibrarySource(file_path)

    with pytest.raises(LibraryDirectoryError):
        library.unrecognized_filenames()


def test_library_adapters_satisfy_library_source_protocol(tmp_path: Path) -> None:
    (tmp_path / "LittleBear_S01E01.mp4").write_bytes(b"")
    libraries: list[LibrarySource] = [
        FakeLibrarySource(),
        FilesystemLibrarySource(tmp_path),
    ]

    for library in libraries:
        episodes = library.episodes()
        unrecognized = library.unrecognized_filenames()
        assert isinstance(episodes, tuple)
        assert isinstance(unrecognized, tuple)
