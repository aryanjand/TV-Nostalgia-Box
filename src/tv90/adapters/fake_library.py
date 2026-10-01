"""In-memory LibrarySource for tests. Never reads the filesystem."""

from tv90.domain.episode import Episode


class FakeLibrarySource:
    def __init__(
        self,
        episodes: tuple[Episode, ...] = (),
        unrecognized_filenames: tuple[str, ...] = (),
    ) -> None:
        self._episodes = episodes
        self._unrecognized_filenames = unrecognized_filenames

    def episodes(self) -> tuple[Episode, ...]:
        return self._episodes

    def unrecognized_filenames(self) -> tuple[str, ...]:
        return self._unrecognized_filenames
