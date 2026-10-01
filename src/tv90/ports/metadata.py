"""Port for fetching cartoon episode titles and descriptions. Maintenance only."""

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Protocol

HttpHeaders = Mapping[str, str]
# Injected GET: tests pass a fake (url, headers) -> body. Production uses urllib.
HttpGetter = Callable[[str, HttpHeaders], str]


class EpisodeMetadataNotFoundError(Exception):
    """The metadata source has no title/description for this cartoon identity."""

    def __init__(self, show_stem: str, season_number: int, episode_number: int) -> None:
        self.show_stem = show_stem
        self.season_number = season_number
        self.episode_number = episode_number
        super().__init__(
            f"{show_stem} S{season_number:02d}E{episode_number:02d}: "
            "episode metadata not found"
        )


@dataclass(frozen=True)
class EpisodeMetadata:
    title: str
    description: str


class EpisodeMetadataSource(Protocol):
    def lookup(
        self, show_stem: str, season_number: int, episode_number: int
    ) -> EpisodeMetadata:
        """Return title and description, or raise EpisodeMetadataNotFoundError."""
        ...
