"""Port for the video player. Adapters implement these methods."""

from __future__ import annotations

import math
from typing import Protocol

MINIMUM_PLAYER_VOLUME = 0.0
MAXIMUM_PLAYER_VOLUME = 1.0
CHANNEL_BANNER_PREFIX = "CH"
CHANNEL_BANNER_NUMBER_WIDTH = 2
VOLUME_BAR_SEGMENT_COUNT = 20
VOLUME_BAR_FILLED_SEGMENT = "█"
VOLUME_BAR_EMPTY_SEGMENT = "·"
VOLUME_BAR_SEGMENT_SEPARATOR = " "
VOLUME_BAR_LABEL = "Volume"


class InvalidVolumeError(ValueError):
    """Volume is not a finite number in the player unit interval [0, 1]."""

    def __init__(self, volume: float) -> None:
        self.volume = volume
        super().__init__("volume must be a finite number between 0 and 1")


class Player(Protocol):
    def load(self, filename: str, offset_seconds: float) -> None:
        """Start the file at the wall-clock airing offset."""
        ...

    def fade_to_next(self, filename: str, offset_seconds: float) -> None:
        """Same-channel join: fade, never the tuner burst."""
        ...

    def tune_to(self, filename: str, offset_seconds: float) -> None:
        """Channel change: tuner burst, never a fade."""
        ...

    def show_slate(self) -> None:
        """Hold a calm color field. Never a desktop, cursor, or terminal."""
        ...

    def show_channel_banner(self, channel_number: int) -> None:
        """Start the CH 0N banner. Do not sleep the requested duration."""
        ...

    def show_volume_bar(self, volume: float) -> None:
        """Show a horizontal segmented volume bar."""
        ...

    def set_volume(self, volume: float) -> None:
        """Set playback volume in 0–1. Invalid values raise."""
        ...

    def stop(self) -> None:
        """Stop playback without writing watch-later state."""
        ...

    def playback_has_ended(self) -> bool:
        """CQS query: True after EOF. Does not clear the flag."""
        ...


def require_player_volume(volume: float) -> float:
    if (
        not math.isfinite(volume)
        or volume < MINIMUM_PLAYER_VOLUME
        or volume > MAXIMUM_PLAYER_VOLUME
    ):
        raise InvalidVolumeError(volume)
    return volume


def format_channel_banner(channel_number: int) -> str:
    padded_number = f"{channel_number:0{CHANNEL_BANNER_NUMBER_WIDTH}d}"
    return f"{CHANNEL_BANNER_PREFIX} {padded_number}"


def volume_bar_filled_count(volume: float) -> int:
    require_player_volume(volume)
    return min(
        VOLUME_BAR_SEGMENT_COUNT,
        max(0, round(volume * VOLUME_BAR_SEGMENT_COUNT)),
    )


def volume_bar_segments(volume: float) -> tuple[bool, ...]:
    filled_count = volume_bar_filled_count(volume)
    return tuple(index < filled_count for index in range(VOLUME_BAR_SEGMENT_COUNT))


def format_volume_bar(volume: float) -> str:
    filled_count = volume_bar_filled_count(volume)
    empty_count = VOLUME_BAR_SEGMENT_COUNT - filled_count
    bar = VOLUME_BAR_SEGMENT_SEPARATOR.join(
        ([VOLUME_BAR_FILLED_SEGMENT] * filled_count)
        + ([VOLUME_BAR_EMPTY_SEGMENT] * empty_count)
    )
    return f"{VOLUME_BAR_LABEL}\n{bar}"
