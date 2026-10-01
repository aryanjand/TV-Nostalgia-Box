"""Flat-folder library adapter. Read-only; one bad name cannot blank the TV."""

from pathlib import Path

from tv90.domain.episode import Episode
from tv90.domain.filename import MalformedFilenameError, parse_filename

MEDIA_FILE_EXTENSIONS = frozenset({"mp4", "mkv", "avi"})
HIDDEN_FILENAME_PREFIX = "."
EXTENSION_SEPARATOR = "."


class LibraryDirectoryError(Exception):
    """The library path is missing or is not a directory."""

    def __init__(self, library_directory: Path, reason: str) -> None:
        self.library_directory = library_directory
        self.reason = reason
        super().__init__(f"{library_directory}: {reason}")


class FilesystemLibrarySource:
    def __init__(self, library_directory: Path) -> None:
        self._library_directory = library_directory

    def episodes(self) -> tuple[Episode, ...]:
        recognized, _unrecognized = self._scan()
        return recognized

    def unrecognized_filenames(self) -> tuple[str, ...]:
        _recognized, unrecognized = self._scan()
        return unrecognized

    def _scan(self) -> tuple[tuple[Episode, ...], tuple[str, ...]]:
        recognized: list[Episode] = []
        unrecognized: list[str] = []
        for path in self._media_files():
            try:
                recognized.append(parse_filename(path.name))
            except MalformedFilenameError:
                unrecognized.append(path.name)
        recognized.sort(key=lambda episode: episode.filename)
        unrecognized.sort()
        return tuple(recognized), tuple(unrecognized)

    def _media_files(self) -> tuple[Path, ...]:
        if not self._library_directory.exists():
            raise LibraryDirectoryError(
                self._library_directory, "library directory does not exist"
            )
        if not self._library_directory.is_dir():
            raise LibraryDirectoryError(
                self._library_directory, "library path is not a directory"
            )
        return tuple(
            path
            for path in self._library_directory.iterdir()
            if _is_library_media_file(path)
        )


def _is_library_media_file(path: Path) -> bool:
    if not path.is_file():
        return False
    if path.name.startswith(HIDDEN_FILENAME_PREFIX):
        return False
    return _has_media_extension(path.name)


def _has_media_extension(filename: str) -> bool:
    _filename_without_extension, separator, extension = filename.rpartition(
        EXTENSION_SEPARATOR
    )
    return separator != "" and extension.lower() in MEDIA_FILE_EXTENSIONS
