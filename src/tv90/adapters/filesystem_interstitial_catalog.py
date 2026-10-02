"""Flat per-channel bumper listing. Read-only; missing folders are empty."""

from pathlib import Path

from tv90.adapters.filesystem_library import is_media_file

CHANNEL_FOLDER_PREFIX = "ch"
CHANNEL_FOLDER_NUMBER_WIDTH = 2
RELATIVE_NAME_SEPARATOR = "/"


def channel_folder_name(channel_number: int) -> str:
    return f"{CHANNEL_FOLDER_PREFIX}{channel_number:0{CHANNEL_FOLDER_NUMBER_WIDTH}d}"


class FilesystemInterstitialCatalog:
    def __init__(self, root: Path) -> None:
        self._root = root

    def filenames_for(self, channel_number: int) -> tuple[str, ...]:
        folder = self._root / channel_folder_name(channel_number)
        if not folder.is_dir():
            return ()
        names = [
            _relative_name(folder.name, path.name)
            for path in folder.iterdir()
            if is_media_file(path)
        ]
        names.sort()
        return tuple(names)


def _relative_name(folder_name: str, filename: str) -> str:
    return f"{folder_name}{RELATIVE_NAME_SEPARATOR}{filename}"
