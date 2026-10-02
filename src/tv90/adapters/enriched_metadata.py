"""Fill empty TVMaze descriptions from Wikipedia plots. Tests inject both sides."""

from __future__ import annotations

from tv90.adapters.wikipedia_plots import WikipediaPlotIndex
from tv90.ports.metadata import (
    EpisodeMetadata,
    EpisodeMetadataSource,
)


class WikipediaEnrichedMetadataSource:
    def __init__(self, inner: EpisodeMetadataSource, plots: WikipediaPlotIndex) -> None:
        self._inner = inner
        self._plots = plots

    def lookup(
        self, show_stem: str, season_number: int, episode_number: int
    ) -> EpisodeMetadata:
        metadata = self._inner.lookup(show_stem, season_number, episode_number)
        if metadata.description:
            return metadata
        filled = self._plots.description_for_title(show_stem, metadata.title)
        if not filled:
            return metadata
        return EpisodeMetadata(title=metadata.title, description=filled)

    def description_for_title(self, show_stem: str, title: str) -> str:
        return self._plots.description_for_title(show_stem, title)
