"""In-memory Player for tests. No OS, no mpv, and no sleep."""

from __future__ import annotations

from dataclasses import dataclass

from tv90.config import CALM_SLATE_COLOR, Settings
from tv90.ports.player import (
    format_channel_banner,
    format_volume_bar,
    require_player_volume,
)

# Analog tuner flash is a black frame, not generated noise (no extra media file).
BLACK_FRAME_TUNER_EFFECT = "black_frame"


@dataclass(frozen=True)
class LoadCommand:
    filename: str
    offset_seconds: float


@dataclass(frozen=True)
class FadeJoinCommand:
    filename: str
    offset_seconds: float
    fade_seconds: float


@dataclass(frozen=True)
class TunerChangeCommand:
    filename: str
    offset_seconds: float
    burst_milliseconds: int
    effect: str


@dataclass(frozen=True)
class ShowSlateCommand:
    slate_color: str


@dataclass(frozen=True)
class ShowChannelBannerCommand:
    channel_number: int
    banner_text: str
    color: str
    duration_seconds: float


@dataclass(frozen=True)
class ShowVolumeBarCommand:
    volume: float
    bar_text: str


@dataclass(frozen=True)
class SetVolumeCommand:
    volume: float


@dataclass(frozen=True)
class StopCommand:
    pass


PlayerCommand = (
    LoadCommand
    | FadeJoinCommand
    | TunerChangeCommand
    | ShowSlateCommand
    | ShowChannelBannerCommand
    | ShowVolumeBarCommand
    | SetVolumeCommand
    | StopCommand
)


class FakePlayer:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._commands: list[PlayerCommand] = []
        self._current_filename: str | None = None
        self._offset_seconds = 0.0
        self._volume = settings.volume_default
        self._showing_slate = False
        self._playback_ended = False

    @property
    def commands(self) -> tuple[PlayerCommand, ...]:
        return tuple(self._commands)

    @property
    def current_filename(self) -> str | None:
        return self._current_filename

    @property
    def offset_seconds(self) -> float:
        return self._offset_seconds

    @property
    def volume(self) -> float:
        return self._volume

    @property
    def showing_slate(self) -> bool:
        return self._showing_slate

    def load(self, filename: str, offset_seconds: float) -> None:
        self._begin_file(filename, offset_seconds)
        self._commands.append(LoadCommand(filename, offset_seconds))

    def fade_to_next(self, filename: str, offset_seconds: float) -> None:
        self._begin_file(filename, offset_seconds)
        self._commands.append(
            FadeJoinCommand(
                filename=filename,
                offset_seconds=offset_seconds,
                fade_seconds=self._settings.episode_join_fade_seconds,
            )
        )

    def tune_to(self, filename: str, offset_seconds: float) -> None:
        self._begin_file(filename, offset_seconds)
        self._commands.append(
            TunerChangeCommand(
                filename=filename,
                offset_seconds=offset_seconds,
                burst_milliseconds=self._settings.tuner_burst_milliseconds,
                effect=BLACK_FRAME_TUNER_EFFECT,
            )
        )

    def show_slate(self) -> None:
        self._current_filename = None
        self._offset_seconds = 0.0
        self._showing_slate = True
        self._playback_ended = False
        self._commands.append(ShowSlateCommand(slate_color=CALM_SLATE_COLOR))

    def show_channel_banner(self, channel_number: int) -> None:
        # Record the requested duration only; sleeping would freeze T12 tests.
        self._commands.append(
            ShowChannelBannerCommand(
                channel_number=channel_number,
                banner_text=format_channel_banner(channel_number),
                color=self._settings.osd_color,
                duration_seconds=self._settings.osd_banner_seconds,
            )
        )

    def show_volume_bar(self, volume: float) -> None:
        require_player_volume(volume)
        self._commands.append(
            ShowVolumeBarCommand(volume=volume, bar_text=format_volume_bar(volume))
        )

    def set_volume(self, volume: float) -> None:
        self._volume = require_player_volume(volume)
        self._commands.append(SetVolumeCommand(volume))

    def stop(self) -> None:
        self._current_filename = None
        self._offset_seconds = 0.0
        self._showing_slate = False
        self._playback_ended = False
        self._commands.append(StopCommand())

    def playback_has_ended(self) -> bool:
        return self._playback_ended

    def mark_playback_ended(self) -> None:
        self._playback_ended = True

    def _begin_file(self, filename: str, offset_seconds: float) -> None:
        self._current_filename = filename
        self._offset_seconds = offset_seconds
        self._showing_slate = False
        self._playback_ended = False
