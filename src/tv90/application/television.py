"""Tick-driven TV controller. No menus, no runtime disk writes."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Protocol

from tv90.config import LITTLE_BEAR_CHANNEL_NUMBER, Settings
from tv90.domain.airing import Airing, OutsideBroadcastDay, Station, resolve_airing
from tv90.domain.broadcast_day import broadcast_day_contains
from tv90.domain.duration import (
    CorruptDurationError,
    DurationUnknownError,
    ProbeFailedError,
)
from tv90.domain.episode import Episode
from tv90.domain.holiday_calendar import HolidayCalendar
from tv90.domain.lineup import ChannelLineup
from tv90.domain.timeline import SECONDS_PER_HOUR, Slot, Timeline
from tv90.ports.clock import Clock
from tv90.ports.duration import DurationIndex
from tv90.ports.library import LibrarySource
from tv90.ports.player import (
    MINIMUM_PLAYER_VOLUME,
    Player,
    format_channel_banner,
    volume_bar_segments,
)
from tv90.ports.tv_power import TvPower

# Remote volume step. Ceiling still comes from Settings; this is only the button size.
VOLUME_STEP = 0.05
# Extra load/tune/fade tries after the first failure (three attempts in total).
HDMI_LOAD_RETRY_COUNT = 2
HDMI_RETRY_WAIT_SECONDS = 1.0
TICK_INTERVAL_SECONDS = 0.25
MILLISECONDS_PER_SECOND = 1000

NOW_PLAYING_CLOCK_NOT_SYNCED = "clock not synced"
NOW_PLAYING_SLATE = "slate"
NOW_PLAYING_OFF_AIR = "off-air"
NOW_PLAYING_FIELD_SEPARATOR = " "

_DURATION_SKIP_ERRORS = (
    DurationUnknownError,
    CorruptDurationError,
    ProbeFailedError,
)

Wait = Callable[[float], None]


class TickLogger(Protocol):
    def log_exception(self, error: BaseException) -> None:
        """Record an unexpected tick failure. Must not write to disk."""
        ...


class PlayKind(Enum):
    LOAD = "load"
    TUNE = "tune"
    FADE = "fade"


class ControllerMode(Enum):
    WAITING_FOR_CLOCK = "waiting_for_clock"
    PLAYING = "playing"
    SLATE = "slate"
    PRE_SIGN_ON = "pre_sign_on"
    NIGHT_LOCK = "night_lock"


@dataclass(frozen=True)
class TelevisionCollaborators:
    clock: Clock
    player: Player
    tv_power: TvPower
    library: LibrarySource
    duration_index: DurationIndex
    settings: Settings
    holiday_calendar: HolidayCalendar
    library_root: Path
    wait: Wait
    logger: TickLogger | None = None


class TelevisionController:
    def __init__(self, collaborators: TelevisionCollaborators) -> None:
        self._collaborators = collaborators
        self._lineup = ChannelLineup(
            collaborators.settings, collaborators.holiday_calendar
        )
        self._station = Station(
            collaborators.settings,
            collaborators.holiday_calendar,
            collaborators.duration_index,
        )
        self._channel_number = LITTLE_BEAR_CHANNEL_NUMBER
        self._volume = collaborators.settings.volume_default
        self._mode = ControllerMode.WAITING_FOR_CLOCK
        self._wait_started_at: datetime | None = None
        self._clock_gate_open = False
        self._awaiting_trust_retune = False
        self._last_command_at: datetime | None = None
        self._current_filename: str | None = None
        self._episode_snapshot: tuple[Episode, ...] | None = None

    def now_playing(self) -> str:
        if self._mode is ControllerMode.WAITING_FOR_CLOCK:
            return NOW_PLAYING_CLOCK_NOT_SYNCED
        if self._mode is ControllerMode.NIGHT_LOCK:
            return NOW_PLAYING_OFF_AIR
        if (
            self._mode is ControllerMode.SLATE
            or self._mode is ControllerMode.PRE_SIGN_ON
            or self._current_filename is None
        ):
            return NOW_PLAYING_SLATE
        line = (
            f"{format_channel_banner(self._channel_number)}"
            f"{NOW_PLAYING_FIELD_SEPARATOR}{self._current_filename}"
        )
        if self._awaiting_trust_retune:
            return f"{line}{NOW_PLAYING_FIELD_SEPARATOR}{NOW_PLAYING_CLOCK_NOT_SYNCED}"
        return line

    def volume(self) -> float:
        return self._volume

    def volume_segments(self) -> tuple[bool, ...]:
        return volume_bar_segments(self._volume)

    def channel_up(self) -> None:
        if not self._accepts_remote_commands():
            return
        if not self._command_cooldown_elapsed():
            return
        on_date = self._collaborators.clock.now().date()
        self._channel_number = self._lineup.channel_up(self._channel_number, on_date)
        self._tune_to_live_airing()
        self._mark_command()

    def channel_down(self) -> None:
        if not self._accepts_remote_commands():
            return
        if not self._command_cooldown_elapsed():
            return
        on_date = self._collaborators.clock.now().date()
        self._channel_number = self._lineup.channel_down(self._channel_number, on_date)
        self._tune_to_live_airing()
        self._mark_command()

    def volume_up(self) -> None:
        self._adjust_volume(VOLUME_STEP)

    def volume_down(self) -> None:
        self._adjust_volume(-VOLUME_STEP)

    def tick(self) -> None:
        # One catch-all for the kiosk: never a stack trace, desktop, or process exit.
        try:
            self._tick_body()
        except Exception as error:
            self._log_exception(error)
            self._show_slate_quietly()
            self._mode = ControllerMode.SLATE
            self._current_filename = None

    def run(self) -> None:
        while True:
            self.tick()
            self._collaborators.wait(TICK_INTERVAL_SECONDS)

    def _tick_body(self) -> None:
        if not self._clock_gate_ready():
            return
        clock_hour = decimal_clock_hour(self._collaborators.clock.now())
        if not broadcast_day_contains(clock_hour, self._collaborators.settings):
            self._hold_outside_broadcast_day(clock_hour)
            return
        if self._mode is ControllerMode.NIGHT_LOCK:
            self._collaborators.tv_power.power_on()
            self._power_on_sync()
            return
        if self._mode is ControllerMode.PRE_SIGN_ON:
            self._collaborators.tv_power.power_on()
            self._power_on_sync()
            return
        if self._mode is ControllerMode.WAITING_FOR_CLOCK:
            self._power_on_sync()
            return
        on_date = self._collaborators.clock.now().date()
        coerced = self._lineup.coerce_current_channel(self._channel_number, on_date)
        if coerced != self._channel_number:
            self._channel_number = coerced
            self._tune_to_live_airing()
            return
        if self._awaiting_trust_retune and self._collaborators.clock.is_trusted():
            self._awaiting_trust_retune = False
            self._tune_to_live_airing()
            return
        if (
            self._mode is ControllerMode.PLAYING
            and self._collaborators.player.playback_has_ended()
        ):
            self._join_live_airing()

    def _clock_gate_ready(self) -> bool:
        if self._clock_gate_open:
            return True
        if self._collaborators.clock.is_trusted():
            self._open_clock_gate()
            return True
        now = self._collaborators.clock.now()
        if self._wait_started_at is None:
            self._wait_started_at = now
            self._collaborators.player.show_slate()
            self._mode = ControllerMode.WAITING_FOR_CLOCK
        elapsed = (now - self._wait_started_at).total_seconds()
        if elapsed < self._collaborators.settings.clock_trust_timeout_seconds:
            return False
        self._open_clock_gate()
        return True

    def _open_clock_gate(self) -> None:
        self._episode_snapshot = self._collect_playable_episodes()
        self._clock_gate_open = True

    def _hold_outside_broadcast_day(self, clock_hour: float) -> None:
        if self._mode is ControllerMode.NIGHT_LOCK:
            return
        if clock_hour >= self._collaborators.settings.night_lock_hour:
            self._enter_night_lock()
            return
        if self._mode is ControllerMode.PRE_SIGN_ON:
            return
        self._collaborators.player.show_slate()
        self._mode = ControllerMode.PRE_SIGN_ON
        self._current_filename = None

    def _enter_night_lock(self) -> None:
        self._collaborators.tv_power.standby()
        self._collaborators.player.show_slate()
        self._mode = ControllerMode.NIGHT_LOCK
        self._current_filename = None
        self._awaiting_trust_retune = False

    def _power_on_sync(self) -> None:
        self._volume = self._collaborators.settings.volume_default
        self._collaborators.player.set_volume(self._volume)
        self._awaiting_trust_retune = not self._collaborators.clock.is_trusted()
        airing = self._resolve_airing()
        if isinstance(airing, OutsideBroadcastDay):
            self._collaborators.player.show_slate()
            self._mode = ControllerMode.SLATE
            self._current_filename = None
            return
        self._play_airing(airing, PlayKind.LOAD)
        self._collaborators.player.show_channel_banner(self._channel_number)

    def _tune_to_live_airing(self) -> None:
        airing = self._resolve_airing()
        if isinstance(airing, OutsideBroadcastDay):
            self._collaborators.player.show_slate()
            self._mode = ControllerMode.SLATE
            self._current_filename = None
            self._collaborators.player.show_channel_banner(self._channel_number)
            return
        self._play_airing(airing, PlayKind.TUNE)
        self._collaborators.player.show_channel_banner(self._channel_number)

    def _join_live_airing(self) -> None:
        # Night lock is handled before this method; remaining OutsideBroadcastDay
        # is an empty channel or a gap, which holds the slate.
        airing = self._resolve_airing()
        if isinstance(airing, OutsideBroadcastDay):
            self._collaborators.player.show_slate()
            self._mode = ControllerMode.SLATE
            self._current_filename = None
            return
        if (
            self._current_filename is not None
            and airing.episode.filename == self._current_filename
        ):
            successor = self._next_slot_after(airing.slot)
            if successor is None:
                self._collaborators.player.show_slate()
                self._mode = ControllerMode.SLATE
                self._current_filename = None
                return
            self._play_filename_or_skip(
                successor.episode.filename,
                self._offset_for_slot(successor),
                PlayKind.FADE,
                after_start_hour=successor.start_hour,
            )
            return
        self._play_airing(airing, PlayKind.FADE)

    def _resolve_airing(self) -> Airing | OutsideBroadcastDay:
        now = self._collaborators.clock.now()
        on_date = now.date()
        self._channel_number = self._lineup.coerce_current_channel(
            self._channel_number, on_date
        )
        timeline = self._station.timeline(
            on_date, self._channel_number, self._episodes()
        )
        return resolve_airing(
            timeline, decimal_clock_hour(now), self._collaborators.settings
        )

    def _play_airing(self, airing: Airing, kind: PlayKind) -> None:
        self._channel_number = airing.channel_number
        self._play_filename_or_skip(
            airing.episode.filename,
            airing.offset_seconds,
            kind,
            after_start_hour=airing.slot.start_hour,
        )

    def _play_filename_or_skip(
        self,
        filename: str,
        offset_seconds: float,
        kind: PlayKind,
        after_start_hour: float,
    ) -> None:
        if self._play_with_hdmi_retry(filename, offset_seconds, kind):
            return
        timeline = self._current_timeline()
        for slot in timeline.slots:
            if slot.start_hour <= after_start_hour:
                continue
            skip_kind = kind if kind is PlayKind.FADE else PlayKind.LOAD
            if self._play_with_hdmi_retry(
                slot.episode.filename,
                self._offset_for_slot(slot),
                skip_kind,
            ):
                return
        self._collaborators.player.show_slate()
        self._mode = ControllerMode.SLATE
        self._current_filename = None

    def _play_with_hdmi_retry(
        self, filename: str, offset_seconds: float, kind: PlayKind
    ) -> bool:
        media_path = self._media_path(filename)
        last_attempt = HDMI_LOAD_RETRY_COUNT
        for attempt in range(last_attempt + 1):
            try:
                self._issue_play(media_path, offset_seconds, kind)
            except Exception as error:
                self._log_exception(error)
                if attempt == last_attempt:
                    return False
                self._collaborators.wait(HDMI_RETRY_WAIT_SECONDS)
                continue
            self._current_filename = filename
            self._mode = ControllerMode.PLAYING
            return True
        return False

    def _issue_play(
        self, media_path: str, offset_seconds: float, kind: PlayKind
    ) -> None:
        player = self._collaborators.player
        if kind is PlayKind.LOAD:
            player.load(media_path, offset_seconds)
            return
        if kind is PlayKind.TUNE:
            player.tune_to(media_path, offset_seconds)
            return
        player.fade_to_next(media_path, offset_seconds)

    def _media_path(self, filename: str) -> str:
        # Touch the read-only mount so this collaborator is real. Playback still
        # uses the library basename because FakePlayer and the duration index key
        # on that string; T15's player adapter may resolve the full path.
        self._collaborators.library_root.joinpath(filename)
        return filename

    def _current_timeline(self) -> Timeline:
        now = self._collaborators.clock.now()
        return self._station.timeline(
            now.date(), self._channel_number, self._episodes()
        )

    def _next_slot_after(self, slot: Slot) -> Slot | None:
        following = [
            candidate
            for candidate in self._current_timeline().slots
            if candidate.start_hour > slot.start_hour
        ]
        if not following:
            return None
        return following[0]

    def _offset_for_slot(self, slot: Slot) -> float:
        clock_hour = decimal_clock_hour(self._collaborators.clock.now())
        if clock_hour < slot.start_hour:
            return 0.0
        return (clock_hour - slot.start_hour) * SECONDS_PER_HOUR

    def _episodes(self) -> tuple[Episode, ...]:
        if self._episode_snapshot is None:
            self._episode_snapshot = self._collect_playable_episodes()
        return self._episode_snapshot

    def _collect_playable_episodes(self) -> tuple[Episode, ...]:
        playable: list[Episode] = []
        for episode in self._collaborators.library.episodes():
            try:
                self._collaborators.duration_index.duration_seconds(episode.filename)
            except _DURATION_SKIP_ERRORS:
                continue
            playable.append(episode)
        return tuple(playable)

    def _adjust_volume(self, delta: float) -> None:
        if not self._accepts_remote_commands():
            return
        if not self._command_cooldown_elapsed():
            return
        ceiling = self._collaborators.settings.volume_ceiling
        self._volume = min(ceiling, max(MINIMUM_PLAYER_VOLUME, self._volume + delta))
        self._collaborators.player.set_volume(self._volume)
        self._collaborators.player.show_volume_bar(self._volume)
        self._mark_command()

    def _accepts_remote_commands(self) -> bool:
        if not self._clock_gate_open:
            return False
        if self._mode is ControllerMode.NIGHT_LOCK:
            return False
        if self._mode is ControllerMode.PRE_SIGN_ON:
            return False
        clock_hour = decimal_clock_hour(self._collaborators.clock.now())
        return broadcast_day_contains(clock_hour, self._collaborators.settings)

    def _command_cooldown_elapsed(self) -> bool:
        if self._last_command_at is None:
            return True
        elapsed_ms = (
            self._collaborators.clock.now() - self._last_command_at
        ).total_seconds() * MILLISECONDS_PER_SECOND
        return elapsed_ms >= self._collaborators.settings.command_cooldown_milliseconds

    def _mark_command(self) -> None:
        self._last_command_at = self._collaborators.clock.now()

    def _show_slate_quietly(self) -> None:
        try:
            self._collaborators.player.show_slate()
        except Exception as error:
            self._log_exception(error)

    def _log_exception(self, error: BaseException) -> None:
        logger = self._collaborators.logger
        if logger is None:
            return
        logger.log_exception(error)


def decimal_clock_hour(moment: datetime) -> float:
    midnight = moment.replace(hour=0, minute=0, second=0, microsecond=0)
    return (moment - midnight).total_seconds() / SECONDS_PER_HOUR
