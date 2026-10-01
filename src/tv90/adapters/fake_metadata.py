"""In-memory episode metadata. Tests never hit the network."""

from collections.abc import Mapping

from tv90.ports.metadata import (
    EpisodeMetadata,
    EpisodeMetadataNotFoundError,
)

MetadataKey = tuple[str, int, int]


class FakeEpisodeMetadataSource:
    def __init__(self, records: Mapping[MetadataKey, EpisodeMetadata]) -> None:
        self._records = dict(records)

    def lookup(
        self, show_stem: str, season_number: int, episode_number: int
    ) -> EpisodeMetadata:
        key = (show_stem, season_number, episode_number)
        if key not in self._records:
            raise EpisodeMetadataNotFoundError(show_stem, season_number, episode_number)
        return self._records[key]
