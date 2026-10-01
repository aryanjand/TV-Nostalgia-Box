"""Port for listing local library episodes. Adapters implement this."""

from typing import Protocol

from tv90.domain.episode import Episode


class LibrarySource(Protocol):
    def episodes(self) -> tuple[Episode, ...]:
        """Return recognized episodes in the library. Never writes."""
        ...

    def unrecognized_filenames(self) -> tuple[str, ...]:
        """Return media filenames that do not match the tag scheme."""
        ...
