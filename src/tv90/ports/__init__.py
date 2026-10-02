"""Ports that domain and application depend on. Adapters implement these."""

from tv90.ports.clock import Clock
from tv90.ports.duration import DurationIndex, MediaProber
from tv90.ports.interstitial import InterstitialCatalog
from tv90.ports.library import LibrarySource
from tv90.ports.metadata import EpisodeMetadataSource
from tv90.ports.player import Player
from tv90.ports.tv_power import TvPower

__all__ = [
    "Clock",
    "DurationIndex",
    "EpisodeMetadataSource",
    "InterstitialCatalog",
    "LibrarySource",
    "MediaProber",
    "Player",
    "TvPower",
]
