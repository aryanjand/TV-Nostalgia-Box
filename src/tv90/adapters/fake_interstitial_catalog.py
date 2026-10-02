"""In-memory InterstitialCatalog for tests. Never reads the filesystem."""

from collections.abc import Mapping, Sequence


class FakeInterstitialCatalog:
    def __init__(
        self, files_by_channel: Mapping[int, Sequence[str]] | None = None
    ) -> None:
        self._files = {
            channel_number: tuple(names)
            for channel_number, names in (files_by_channel or {}).items()
        }

    def filenames_for(self, channel_number: int) -> tuple[str, ...]:
        return self._files.get(channel_number, ())
