from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from tv90.adapters.fake_clock import FakeClock
from tv90.adapters.fake_duration import FakeDurationIndex
from tv90.adapters.fake_library import FakeLibrarySource
from tv90.adapters.fake_player import (
    FadeJoinCommand,
    FakePlayer,
    LoadCommand,
    SetVolumeCommand,
    ShowChannelBannerCommand,
    ShowVolumeBarCommand,
    TunerChangeCommand,
)
from tv90.adapters.fake_tv_power import FakeTvPower
from tv90.application.duration_lookup import DurationLookup
from tv90.application.television import (
    HDMI_LOAD_RETRY_COUNT,
    HDMI_RETRY_WAIT_SECONDS,
    NOW_PLAYING_CLOCK_NOT_SYNCED,
    NOW_PLAYING_OFF_AIR,
    NOW_PLAYING_SLATE,
    TICK_INTERVAL_SECONDS,
    VOLUME_STEP,
    TelevisionCollaborators,
    TelevisionController,
    decimal_clock_hour,
)
from tv90.config import (
    COMMAND_COOLDOWN_MILLISECONDS,
    DEFAULT_CLOCK_TRUST_TIMEOUT_SECONDS,
    HARRY_CHANNEL_NUMBER,
    LITTLE_BEAR_CHANNEL_NUMBER,
    OSWALD_CHANNEL_NUMBER,
    VOLUME_CEILING,
    VOLUME_DEFAULT,
    Settings,
    load_settings,
)
from tv90.domain.airing import Airing, Station, resolve_airing
from tv90.domain.duration import ProbeFailedError
from tv90.domain.episode import Episode
from tv90.domain.filename import parse_filename
from tv90.domain.holiday_calendar import HolidayCalendar
from tv90.domain.timeline import SECONDS_PER_HOUR, Timeline
from tv90.ports.duration import DurationIndex
from tv90.ports.library import LibrarySource
from tv90.ports.player import VOLUME_BAR_SEGMENT_COUNT, format_channel_banner

VANCOUVER = ZoneInfo("America/Vancouver")
JULY_MORNING = datetime(2024, 7, 15, 7, 0, tzinfo=VANCOUVER)
JULY_SIGN_ON = datetime(2024, 7, 15, 6, 30, tzinfo=VANCOUVER)
JULY_BEFORE_SIGN_ON = datetime(2024, 7, 15, 5, 0, tzinfo=VANCOUVER)
JULY_NIGHT_LOCK = datetime(2024, 7, 15, 21, 0, tzinfo=VANCOUVER)
NEXT_SIGN_ON = datetime(2024, 7, 16, 6, 30, tzinfo=VANCOUVER)
HALLOWEEN_MORNING = datetime(2024, 10, 31, 7, 0, tzinfo=VANCOUVER)
HALLOWEEN_NIGHT_LOCK = datetime(2024, 10, 31, 21, 0, tzinfo=VANCOUVER)
NOVEMBER_SIGN_ON = datetime(2024, 11, 1, 6, 30, tzinfo=VANCOUVER)
ONE_HOUR_SECONDS = float(SECONDS_PER_HOUR)
COOLDOWN = timedelta(milliseconds=COMMAND_COOLDOWN_MILLISECONDS)
JUST_UNDER_COOLDOWN = timedelta(milliseconds=COMMAND_COOLDOWN_MILLISECONDS - 1)

LITTLE_BEAR_ONE = parse_filename("LittleBear_S01E01.mp4")
LITTLE_BEAR_TWO = parse_filename("LittleBear_S01E02.mp4")
OSWALD_ONE = parse_filename("Oswald_S01E01.mp4")
HARRY_ONE = parse_filename("Harry_S01E01.mp4")
HALLOWEEN_MOVIE = parse_filename("Holiday_GreatPumpkin_HALLOWEEN.mp4")

DAYTIME_LIBRARY = (LITTLE_BEAR_ONE, LITTLE_BEAR_TWO, OSWALD_ONE, HARRY_ONE)
HOUR_DURATIONS = {episode.filename: ONE_HOUR_SECONDS for episode in DAYTIME_LIBRARY}


class RecordingLogger:
    def __init__(self) -> None:
        self.errors: list[BaseException] = []

    def log_exception(self, error: BaseException) -> None:
        self.errors.append(error)


class RecordingWait:
    def __init__(self) -> None:
        self.calls: list[float] = []

    def __call__(self, seconds: float) -> None:
        self.calls.append(seconds)


class FiniteRun(Exception):
    """Stops TelevisionController.run after a bounded number of waits."""


class CountingWait:
    def __init__(self, stop_after: int) -> None:
        self.calls = 0
        self.stop_after = stop_after
        self.last_seconds = 0.0

    def __call__(self, seconds: float) -> None:
        self.calls += 1
        self.last_seconds = seconds
        if self.calls >= self.stop_after:
            raise FiniteRun()


class ExplodingLibrary:
    def episodes(self) -> tuple[Episode, ...]:
        raise RuntimeError("library exploded")

    def unrecognized_filenames(self) -> tuple[str, ...]:
        return ()


class FailingProber:
    def duration_seconds(self, filename: str) -> float:
        raise ProbeFailedError(filename, "media file is missing")


class FailListedPlayer(FakePlayer):
    def __init__(self, settings: Settings, failing_filenames: frozenset[str]) -> None:
        super().__init__(settings)
        self._failing_filenames = failing_filenames

    def load(self, filename: str, offset_seconds: float) -> None:
        if filename in self._failing_filenames:
            raise OSError("corrupt file")
        super().load(filename, offset_seconds)

    def tune_to(self, filename: str, offset_seconds: float) -> None:
        if filename in self._failing_filenames:
            raise OSError("corrupt file")
        super().tune_to(filename, offset_seconds)

    def fade_to_next(self, filename: str, offset_seconds: float) -> None:
        if filename in self._failing_filenames:
            raise OSError("corrupt file")
        super().fade_to_next(filename, offset_seconds)


class FlakyLoadPlayer(FakePlayer):
    def __init__(self, settings: Settings, failures_before_success: int) -> None:
        super().__init__(settings)
        self._failures_remaining = failures_before_success

    def load(self, filename: str, offset_seconds: float) -> None:
        if self._failures_remaining > 0:
            self._failures_remaining -= 1
            raise OSError("hdmi lost")
        super().load(filename, offset_seconds)


class SlateThenBoomPlayer(FakePlayer):
    def show_slate(self) -> None:
        super().show_slate()
        raise RuntimeError("osd overlay failed")


def _noop_wait(_seconds: float) -> None:
    return None


def _little_bear_timeline(on_date: date) -> Timeline:
    settings = load_settings({})
    index: DurationIndex = FakeDurationIndex(HOUR_DURATIONS)
    station = Station(settings, HolidayCalendar.from_defaults(settings), index)
    return station.timeline(on_date, LITTLE_BEAR_CHANNEL_NUMBER, DAYTIME_LIBRARY)


def _airing_at(
    moment: datetime,
    channel_number: int = LITTLE_BEAR_CHANNEL_NUMBER,
    episodes: tuple[Episode, ...] = DAYTIME_LIBRARY,
    durations: dict[str, float] | None = None,
) -> Airing:
    settings = load_settings({})
    index: DurationIndex = FakeDurationIndex(
        durations if durations is not None else HOUR_DURATIONS
    )
    station = Station(settings, HolidayCalendar.from_defaults(settings), index)
    timeline = station.timeline(moment.date(), channel_number, episodes)
    result = resolve_airing(timeline, decimal_clock_hour(moment), settings)
    assert isinstance(result, Airing)
    return result


def _controller(
    tmp_path: Path,
    *,
    clock: FakeClock | None = None,
    player: FakePlayer | None = None,
    tv_power: FakeTvPower | None = None,
    library: LibrarySource | None = None,
    duration_index: FakeDurationIndex | DurationLookup | None = None,
    wait: RecordingWait | CountingWait | None = None,
    logger: RecordingLogger | None = None,
    library_root: Path | None = None,
) -> tuple[TelevisionController, FakeClock, FakePlayer, FakeTvPower]:
    settings = load_settings({})
    resolved_clock = clock if clock is not None else FakeClock.trusted(JULY_MORNING)
    resolved_player = player if player is not None else FakePlayer(settings)
    resolved_power = tv_power if tv_power is not None else FakeTvPower()
    resolved_library: LibrarySource = (
        library if library is not None else FakeLibrarySource(episodes=DAYTIME_LIBRARY)
    )
    resolved_index = (
        duration_index
        if duration_index is not None
        else FakeDurationIndex(HOUR_DURATIONS)
    )
    controller = TelevisionController(
        TelevisionCollaborators(
            clock=resolved_clock,
            player=resolved_player,
            tv_power=resolved_power,
            library=resolved_library,
            duration_index=resolved_index,
            settings=settings,
            holiday_calendar=HolidayCalendar.from_defaults(settings),
            library_root=library_root if library_root is not None else tmp_path,
            wait=wait if wait is not None else _noop_wait,
            logger=logger,
        )
    )
    return controller, resolved_clock, resolved_player, resolved_power


def _wake(controller: TelevisionController) -> None:
    controller.tick()
    controller.channel_up()


def _load_commands(player: FakePlayer) -> tuple[LoadCommand, ...]:
    return tuple(
        command for command in player.commands if isinstance(command, LoadCommand)
    )


def _tune_commands(player: FakePlayer) -> tuple[TunerChangeCommand, ...]:
    return tuple(
        command
        for command in player.commands
        if isinstance(command, TunerChangeCommand)
    )


def _fade_commands(player: FakePlayer) -> tuple[FadeJoinCommand, ...]:
    return tuple(
        command for command in player.commands if isinstance(command, FadeJoinCommand)
    )


def test_decimal_clock_hour_maps_six_thirty_to_sign_on() -> None:
    assert decimal_clock_hour(JULY_SIGN_ON) == pytest.approx(6.5)


def test_untrusted_clock_holds_slate_and_ignores_remote(tmp_path: Path) -> None:
    clock = FakeClock.untrusted(JULY_MORNING)
    controller, _, player, _ = _controller(tmp_path, clock=clock)

    controller.tick()
    controller.channel_up()
    controller.volume_up()

    assert player.showing_slate is True
    assert controller.now_playing() == NOW_PLAYING_CLOCK_NOT_SYNCED
    assert _load_commands(player) == ()
    assert _tune_commands(player) == ()
    assert player.volume == VOLUME_DEFAULT


def test_untrusted_clock_starts_playback_after_timeout_with_unsynced_phrase(
    tmp_path: Path,
) -> None:
    clock = FakeClock.untrusted(JULY_MORNING)
    controller, _, player, _ = _controller(tmp_path, clock=clock)
    controller.tick()

    clock.advance_time(timedelta(seconds=DEFAULT_CLOCK_TRUST_TIMEOUT_SECONDS))
    controller.tick()

    assert player.showing_slate is True
    assert controller.now_playing() == NOW_PLAYING_SLATE
    assert _load_commands(player) == ()

    controller.channel_up()

    expected = _airing_at(clock.now())
    loads = _load_commands(player)
    assert loads
    assert loads[-1].filename == expected.episode.filename
    assert loads[-1].offset_seconds == pytest.approx(expected.offset_seconds)
    assert NOW_PLAYING_CLOCK_NOT_SYNCED in controller.now_playing()
    assert format_channel_banner(LITTLE_BEAR_CHANNEL_NUMBER) in controller.now_playing()
    assert expected.episode.filename in controller.now_playing()


def test_mark_trusted_while_idle_stays_idle(tmp_path: Path) -> None:
    clock = FakeClock.untrusted(JULY_MORNING)
    controller, _, player, _ = _controller(tmp_path, clock=clock)
    controller.tick()
    clock.advance_time(timedelta(seconds=DEFAULT_CLOCK_TRUST_TIMEOUT_SECONDS))
    controller.tick()

    clock.mark_trusted()
    controller.tick()

    assert controller.now_playing() == NOW_PLAYING_SLATE
    assert _load_commands(player) == ()
    assert _tune_commands(player) == ()


def test_mark_trusted_while_playing_retunes_and_drops_unsynced_phrase(
    tmp_path: Path,
) -> None:
    clock = FakeClock.untrusted(JULY_MORNING)
    controller, _, player, _ = _controller(tmp_path, clock=clock)
    controller.tick()
    clock.advance_time(timedelta(seconds=DEFAULT_CLOCK_TRUST_TIMEOUT_SECONDS))
    _wake(controller)

    clock.mark_trusted()
    controller.tick()

    expected = _airing_at(clock.now())
    tunes = _tune_commands(player)
    assert tunes
    assert tunes[-1].filename == expected.episode.filename
    assert tunes[-1].offset_seconds == pytest.approx(expected.offset_seconds)
    assert NOW_PLAYING_CLOCK_NOT_SYNCED not in controller.now_playing()
    banner = format_channel_banner(LITTLE_BEAR_CHANNEL_NUMBER)
    assert controller.now_playing() == f"{banner} {expected.episode.filename}"


def test_trusted_tick_stays_idle_until_channel_wake(tmp_path: Path) -> None:
    controller, _, player, power = _controller(tmp_path)

    controller.tick()

    assert player.showing_slate is True
    assert controller.now_playing() == NOW_PLAYING_SLATE
    assert _load_commands(player) == ()
    assert power.commands == ()


def test_channel_wake_from_idle_loads_mid_episode_offset_and_resets_volume(
    tmp_path: Path,
) -> None:
    controller, _, player, power = _controller(tmp_path)

    _wake(controller)

    expected = _airing_at(JULY_MORNING)
    loads = _load_commands(player)
    assert len(loads) == 1
    assert loads[0].filename == expected.episode.filename
    assert loads[0].offset_seconds == pytest.approx(expected.offset_seconds)
    assert loads[0].offset_seconds != 0.0
    assert player.volume == VOLUME_DEFAULT
    assert SetVolumeCommand(VOLUME_DEFAULT) in player.commands
    assert any(
        isinstance(command, ShowChannelBannerCommand)
        and command.channel_number == LITTLE_BEAR_CHANNEL_NUMBER
        for command in player.commands
    )
    assert power.commands == ()
    assert _fade_commands(player) == ()
    assert _tune_commands(player) == ()


def test_channel_up_uses_tune_to_not_fade(tmp_path: Path) -> None:
    controller, clock, player, _ = _controller(tmp_path)
    _wake(controller)
    clock.advance_time(COOLDOWN)

    controller.channel_up()

    tunes = _tune_commands(player)
    assert tunes
    assert tunes[-1].filename == OSWALD_ONE.filename
    assert _fade_commands(player) == ()
    assert any(
        isinstance(command, ShowChannelBannerCommand)
        and command.channel_number == OSWALD_CHANNEL_NUMBER
        for command in player.commands
    )
    clock.advance_time(COOLDOWN)
    controller.channel_up()
    assert _tune_commands(player)[-1].filename == HARRY_ONE.filename
    clock.advance_time(COOLDOWN)
    controller.channel_up()
    expected_home = _airing_at(clock.now())
    assert _tune_commands(player)[-1].filename == expected_home.episode.filename


def test_channel_down_wraps_to_harry(tmp_path: Path) -> None:
    controller, clock, player, _ = _controller(tmp_path)
    _wake(controller)
    clock.advance_time(COOLDOWN)

    controller.channel_down()

    assert _tune_commands(player)[-1].filename == HARRY_ONE.filename
    assert any(
        isinstance(command, ShowChannelBannerCommand)
        and command.channel_number == HARRY_CHANNEL_NUMBER
        for command in player.commands
    )


def test_channel_up_inside_cooldown_is_dropped(tmp_path: Path) -> None:
    controller, clock, player, _ = _controller(tmp_path)
    _wake(controller)
    clock.advance_time(COOLDOWN)
    controller.channel_up()
    first_tune_count = len(_tune_commands(player))

    clock.advance_time(JUST_UNDER_COOLDOWN)
    controller.channel_up()

    assert len(_tune_commands(player)) == first_tune_count
    clock.advance_time(timedelta(milliseconds=1))
    controller.channel_up()
    assert len(_tune_commands(player)) == first_tune_count + 1


def test_volume_never_exceeds_ceiling_and_shows_bar(tmp_path: Path) -> None:
    controller, clock, player, _ = _controller(tmp_path)
    controller.tick()

    steps_to_ceiling = round((VOLUME_CEILING - VOLUME_DEFAULT) / VOLUME_STEP)
    for _ in range(steps_to_ceiling + 2):
        clock.advance_time(COOLDOWN)
        controller.volume_up()

    assert player.volume == pytest.approx(VOLUME_CEILING)
    assert controller.volume() == pytest.approx(VOLUME_CEILING)
    assert player.volume <= VOLUME_CEILING
    assert any(isinstance(command, ShowVolumeBarCommand) for command in player.commands)
    assert controller.volume_segments().count(True) == round(
        VOLUME_CEILING * VOLUME_BAR_SEGMENT_COUNT
    )
    assert _load_commands(player) == ()


def test_volume_down_clamps_to_zero(tmp_path: Path) -> None:
    controller, clock, player, _ = _controller(tmp_path)
    controller.tick()

    steps_to_zero = round(VOLUME_DEFAULT / VOLUME_STEP)
    for _ in range(steps_to_zero + 2):
        clock.advance_time(COOLDOWN)
        controller.volume_down()

    assert player.volume == 0.0


def test_volume_command_inside_cooldown_is_dropped(tmp_path: Path) -> None:
    controller, clock, player, _ = _controller(tmp_path)
    controller.tick()
    controller.volume_up()
    raised = player.volume

    clock.advance_time(JUST_UNDER_COOLDOWN)
    controller.volume_up()

    assert player.volume == pytest.approx(raised)
    clock.advance_time(timedelta(milliseconds=1))
    controller.volume_up()
    assert player.volume == pytest.approx(raised + VOLUME_STEP)


def test_end_of_file_join_uses_fade_to_next_not_tune(tmp_path: Path) -> None:
    clock = FakeClock.trusted(JULY_SIGN_ON)
    controller, _, player, _ = _controller(tmp_path, clock=clock)
    _wake(controller)
    first_slot = _little_bear_timeline(JULY_SIGN_ON.date()).slots[0]
    second_slot = _little_bear_timeline(JULY_SIGN_ON.date()).slots[1]
    assert _load_commands(player)[-1].filename == first_slot.episode.filename
    assert _load_commands(player)[-1].offset_seconds == pytest.approx(0.0)

    player.mark_playback_ended()
    clock.advance_time(timedelta(hours=1))
    controller.tick()

    fades = _fade_commands(player)
    assert fades
    assert fades[-1].filename == second_slot.episode.filename
    assert fades[-1].offset_seconds == pytest.approx(0.0)
    assert _tune_commands(player) == ()


def test_lagged_join_uses_wall_clock_offset(tmp_path: Path) -> None:
    clock = FakeClock.trusted(JULY_SIGN_ON)
    controller, _, player, _ = _controller(tmp_path, clock=clock)
    _wake(controller)
    player.mark_playback_ended()
    clock.advance_time(timedelta(hours=1, minutes=30))
    controller.tick()

    expected = _airing_at(clock.now())
    fades = _fade_commands(player)
    assert fades[-1].filename == expected.episode.filename
    assert fades[-1].offset_seconds == pytest.approx(expected.offset_seconds)


def test_early_eof_skips_to_next_slot_with_fade(tmp_path: Path) -> None:
    clock = FakeClock.trusted(JULY_MORNING)
    controller, _, player, _ = _controller(tmp_path, clock=clock)
    _wake(controller)
    covering = _airing_at(JULY_MORNING)
    later_slots = [
        slot
        for slot in _little_bear_timeline(JULY_MORNING.date()).slots
        if slot.start_hour > covering.slot.start_hour
    ]
    player.mark_playback_ended()
    controller.tick()

    fades = _fade_commands(player)
    assert fades[-1].filename == later_slots[0].episode.filename
    assert fades[-1].offset_seconds == pytest.approx(0.0)


def test_night_lock_ignores_inputs_morning_stays_idle_until_wake(
    tmp_path: Path,
) -> None:
    clock = FakeClock.trusted(JULY_MORNING)
    controller, _, player, power = _controller(tmp_path, clock=clock)
    _wake(controller)
    loads_after_wake = _load_commands(player)

    clock.advance_time(JULY_NIGHT_LOCK - JULY_MORNING)
    controller.tick()
    controller.channel_up()
    controller.volume_up()

    assert power.commands == ()
    assert player.showing_slate is True
    assert controller.now_playing() == NOW_PLAYING_OFF_AIR
    assert _tune_commands(player) == ()

    clock.advance_time(NEXT_SIGN_ON - JULY_NIGHT_LOCK)
    controller.tick()

    assert power.commands == ()
    assert controller.now_playing() == NOW_PLAYING_SLATE
    assert _load_commands(player) == loads_after_wake
    assert player.showing_slate is True

    controller.channel_up()

    assert power.commands == ()
    loads = _load_commands(player)
    assert loads[-1].offset_seconds == pytest.approx(0.0)
    assert player.volume == VOLUME_DEFAULT
    assert controller.now_playing() != NOW_PLAYING_OFF_AIR


def test_episode_is_cut_off_at_night_lock_without_fade(tmp_path: Path) -> None:
    clock = FakeClock.trusted(JULY_NIGHT_LOCK - timedelta(minutes=1))
    controller, _, player, power = _controller(tmp_path, clock=clock)
    _wake(controller)
    player.mark_playback_ended()
    clock.advance_time(timedelta(minutes=1))
    controller.tick()

    assert power.commands == ()
    assert _fade_commands(player) == ()
    assert player.showing_slate is True
    assert controller.now_playing() == NOW_PLAYING_OFF_AIR


def test_empty_library_shows_slate(tmp_path: Path) -> None:
    controller, _, player, _ = _controller(
        tmp_path, library=FakeLibrarySource(episodes=())
    )

    controller.tick()

    assert player.showing_slate is True
    assert controller.now_playing() == NOW_PLAYING_SLATE
    assert _load_commands(player) == ()

    controller.channel_up()

    assert player.showing_slate is True
    assert controller.now_playing() == NOW_PLAYING_SLATE
    assert _load_commands(player) == ()


def test_missing_duration_skips_file_and_plays_other_channel(tmp_path: Path) -> None:
    durations = {
        OSWALD_ONE.filename: ONE_HOUR_SECONDS,
        HARRY_ONE.filename: ONE_HOUR_SECONDS,
    }
    controller, clock, player, _ = _controller(
        tmp_path,
        duration_index=FakeDurationIndex(durations),
    )
    controller.tick()
    assert player.showing_slate is True

    controller.channel_up()
    assert player.showing_slate is True
    clock.advance_time(COOLDOWN)
    controller.channel_up()
    assert player.current_filename == OSWALD_ONE.filename
    assert _tune_commands(player)


def test_corrupt_duration_is_skipped_not_fatal(tmp_path: Path) -> None:
    durations = {
        LITTLE_BEAR_ONE.filename: 0.0,
        LITTLE_BEAR_TWO.filename: ONE_HOUR_SECONDS,
        OSWALD_ONE.filename: ONE_HOUR_SECONDS,
        HARRY_ONE.filename: ONE_HOUR_SECONDS,
    }
    controller, _, player, _ = _controller(
        tmp_path, duration_index=FakeDurationIndex(durations)
    )
    _wake(controller)

    loads = _load_commands(player)
    assert loads
    assert loads[0].filename == LITTLE_BEAR_TWO.filename


def test_player_error_skips_to_next_slot_without_exiting(tmp_path: Path) -> None:
    settings = load_settings({})
    covering = _airing_at(JULY_MORNING)
    player = FailListedPlayer(settings, frozenset({covering.episode.filename}))
    controller, _, _, _ = _controller(tmp_path, player=player)

    _wake(controller)

    later_slots = [
        slot
        for slot in _little_bear_timeline(JULY_MORNING.date()).slots
        if slot.start_hour > covering.slot.start_hour
    ]
    loads = _load_commands(player)
    assert loads
    assert loads[-1].filename == later_slots[0].episode.filename
    assert loads[-1].offset_seconds == pytest.approx(0.0)


def test_all_player_errors_hold_slate(tmp_path: Path) -> None:
    settings = load_settings({})
    failing = frozenset(episode.filename for episode in DAYTIME_LIBRARY)
    player = FailListedPlayer(settings, failing)
    controller, _, _, _ = _controller(tmp_path, player=player)

    _wake(controller)

    assert player.showing_slate is True
    assert controller.now_playing() == NOW_PLAYING_SLATE


def test_hdmi_retry_then_plays(tmp_path: Path) -> None:
    settings = load_settings({})
    wait = RecordingWait()
    player = FlakyLoadPlayer(settings, failures_before_success=HDMI_LOAD_RETRY_COUNT)
    controller, _, _, _ = _controller(tmp_path, player=player, wait=wait)

    _wake(controller)

    assert _load_commands(player)
    assert wait.calls == [HDMI_RETRY_WAIT_SECONDS] * HDMI_LOAD_RETRY_COUNT


def test_hdmi_retries_then_skips_file(tmp_path: Path) -> None:
    settings = load_settings({})
    wait = RecordingWait()
    covering = _airing_at(JULY_MORNING)
    player = FailListedPlayer(settings, frozenset({covering.episode.filename}))
    controller, _, _, _ = _controller(tmp_path, player=player, wait=wait)

    _wake(controller)

    later_slots = [
        slot
        for slot in _little_bear_timeline(JULY_MORNING.date()).slots
        if slot.start_hour > covering.slot.start_hour
    ]
    assert wait.calls == [HDMI_RETRY_WAIT_SECONDS] * HDMI_LOAD_RETRY_COUNT
    loads = _load_commands(player)
    assert loads
    assert loads[-1].filename == later_slots[0].episode.filename


def test_duration_lookup_probe_failure_skips(tmp_path: Path) -> None:
    lookup = DurationLookup(
        FakeDurationIndex({OSWALD_ONE.filename: ONE_HOUR_SECONDS}),
        FailingProber(),
    )
    library = FakeLibrarySource(episodes=(LITTLE_BEAR_ONE, OSWALD_ONE, HARRY_ONE))
    controller, clock, player, _ = _controller(
        tmp_path, library=library, duration_index=lookup
    )
    controller.tick()
    assert player.showing_slate is True
    controller.channel_up()
    assert player.showing_slate is True
    clock.advance_time(COOLDOWN)
    controller.channel_up()
    assert player.current_filename == OSWALD_ONE.filename


def test_unexpected_collaborator_error_shows_slate_and_continues(
    tmp_path: Path,
) -> None:
    logger = RecordingLogger()
    controller, _, player, _ = _controller(
        tmp_path, library=ExplodingLibrary(), logger=logger
    )

    controller.tick()
    controller.tick()

    assert player.showing_slate is True
    assert controller.now_playing() == NOW_PLAYING_SLATE
    assert logger.errors
    assert all(isinstance(error, RuntimeError) for error in logger.errors)


def test_catch_all_survives_show_slate_failure(tmp_path: Path) -> None:
    logger = RecordingLogger()
    player = SlateThenBoomPlayer(load_settings({}))
    controller, _, _, _ = _controller(
        tmp_path, player=player, library=ExplodingLibrary(), logger=logger
    )

    controller.tick()

    assert logger.errors
    assert controller.now_playing() == NOW_PLAYING_SLATE


def test_commands_ignored_before_sign_on(tmp_path: Path) -> None:
    clock = FakeClock.trusted(JULY_BEFORE_SIGN_ON)
    controller, _, player, power = _controller(tmp_path, clock=clock)
    controller.tick()
    controller.tick()
    controller.channel_up()
    controller.volume_up()

    assert player.showing_slate is True
    assert controller.now_playing() == NOW_PLAYING_SLATE
    assert _tune_commands(player) == ()
    assert power.commands == ()

    clock.advance_time(JULY_SIGN_ON - JULY_BEFORE_SIGN_ON)
    controller.tick()

    assert power.commands == ()
    assert controller.now_playing() == NOW_PLAYING_SLATE
    assert _load_commands(player) == ()

    controller.channel_up()

    assert power.commands == ()
    assert _load_commands(player)


def test_stale_channel_four_is_coerced_after_window_closes(tmp_path: Path) -> None:
    halloween_library = DAYTIME_LIBRARY + (HALLOWEEN_MOVIE,)
    durations = {
        **HOUR_DURATIONS,
        HALLOWEEN_MOVIE.filename: ONE_HOUR_SECONDS,
    }
    clock = FakeClock.trusted(HALLOWEEN_MORNING)
    controller, _, player, power = _controller(
        tmp_path,
        clock=clock,
        library=FakeLibrarySource(episodes=halloween_library),
        duration_index=FakeDurationIndex(durations),
    )
    _wake(controller)
    clock.advance_time(COOLDOWN)
    controller.channel_up()
    clock.advance_time(COOLDOWN)
    controller.channel_up()
    clock.advance_time(COOLDOWN)
    controller.channel_up()
    assert player.current_filename == HALLOWEEN_MOVIE.filename

    clock.advance_time(HALLOWEEN_NIGHT_LOCK - clock.now())
    controller.tick()
    assert power.commands == ()
    assert controller.now_playing() == NOW_PLAYING_OFF_AIR

    clock.advance_time(NOVEMBER_SIGN_ON - clock.now())
    controller.tick()

    assert power.commands == ()
    assert controller.now_playing() == NOW_PLAYING_SLATE
    controller.channel_up()

    expected = _airing_at(NOVEMBER_SIGN_ON)
    loads = _load_commands(player)
    assert loads[-1].filename == expected.episode.filename


def test_no_runtime_writes_over_a_simulated_day(tmp_path: Path) -> None:
    library_root = tmp_path / "library"
    library_root.mkdir()
    marker = library_root / "keep.txt"
    marker.write_text("read-only mount", encoding="utf-8")
    marker.chmod(0o444)
    library_root.chmod(0o555)
    clock = FakeClock.trusted(JULY_SIGN_ON)
    controller, _, _, power = _controller(
        tmp_path, clock=clock, library_root=library_root
    )
    try:
        end = JULY_NIGHT_LOCK + timedelta(hours=1)
        while clock.now() <= end:
            controller.tick()
            clock.advance_time(timedelta(minutes=5))
    finally:
        library_root.chmod(0o755)
        marker.chmod(0o644)

    assert marker.read_text(encoding="utf-8") == "read-only mount"
    assert list(library_root.iterdir()) == [marker]
    assert power.commands == ()


def test_run_loops_tick_and_injected_wait(tmp_path: Path) -> None:
    wait = CountingWait(stop_after=2)
    controller, _, player, _ = _controller(tmp_path, wait=wait)

    with pytest.raises(FiniteRun):
        controller.run()

    assert wait.calls == 2
    assert wait.last_seconds == TICK_INTERVAL_SECONDS
    assert _load_commands(player) == ()
    assert controller.now_playing() == NOW_PLAYING_SLATE


def test_volume_and_channel_ignored_during_untrusted_wait(tmp_path: Path) -> None:
    clock = FakeClock.untrusted(JULY_MORNING)
    controller, _, player, _ = _controller(tmp_path, clock=clock)
    controller.tick()
    volume_commands_before = sum(
        isinstance(command, SetVolumeCommand | ShowVolumeBarCommand)
        for command in player.commands
    )
    controller.volume_up()
    controller.channel_down()
    assert (
        sum(
            isinstance(command, SetVolumeCommand | ShowVolumeBarCommand)
            for command in player.commands
        )
        == volume_commands_before
    )
    assert _tune_commands(player) == ()


def test_shared_cooldown_drops_volume_after_channel(tmp_path: Path) -> None:
    controller, clock, player, _ = _controller(tmp_path)
    controller.tick()
    controller.channel_up()
    volume_before = player.volume

    clock.advance_time(JUST_UNDER_COOLDOWN)
    controller.volume_up()

    assert player.volume == volume_before
    clock.advance_time(timedelta(milliseconds=1))
    controller.volume_up()
    assert player.volume == pytest.approx(volume_before + VOLUME_STEP)


def test_channel_down_inside_cooldown_is_dropped(tmp_path: Path) -> None:
    controller, clock, player, _ = _controller(tmp_path)
    _wake(controller)
    clock.advance_time(COOLDOWN)
    controller.channel_down()
    first_tune_count = len(_tune_commands(player))

    clock.advance_time(JUST_UNDER_COOLDOWN)
    controller.channel_down()

    assert len(_tune_commands(player)) == first_tune_count


def test_channel_change_to_empty_friend_holds_slate(tmp_path: Path) -> None:
    durations = {
        OSWALD_ONE.filename: ONE_HOUR_SECONDS,
        HARRY_ONE.filename: ONE_HOUR_SECONDS,
    }
    controller, clock, player, _ = _controller(
        tmp_path, duration_index=FakeDurationIndex(durations)
    )
    _wake(controller)
    clock.advance_time(COOLDOWN)
    controller.channel_up()
    assert player.current_filename == OSWALD_ONE.filename

    clock.advance_time(COOLDOWN)
    controller.channel_down()

    assert player.showing_slate is True
    assert controller.now_playing() == NOW_PLAYING_SLATE
    assert any(
        isinstance(command, ShowChannelBannerCommand)
        and command.channel_number == LITTLE_BEAR_CHANNEL_NUMBER
        for command in player.commands
    )


def test_stale_channel_four_is_coerced_while_playing(tmp_path: Path) -> None:
    halloween_library = DAYTIME_LIBRARY + (HALLOWEEN_MOVIE,)
    durations = {**HOUR_DURATIONS, HALLOWEEN_MOVIE.filename: ONE_HOUR_SECONDS}
    clock = FakeClock.trusted(HALLOWEEN_MORNING)
    controller, _, player, _ = _controller(
        tmp_path,
        clock=clock,
        library=FakeLibrarySource(episodes=halloween_library),
        duration_index=FakeDurationIndex(durations),
    )
    _wake(controller)
    clock.advance_time(COOLDOWN)
    controller.channel_up()
    clock.advance_time(COOLDOWN)
    controller.channel_up()
    clock.advance_time(COOLDOWN)
    controller.channel_up()
    assert player.current_filename == HALLOWEEN_MOVIE.filename

    clock.advance_time(NOVEMBER_SIGN_ON + timedelta(minutes=30) - clock.now())
    controller.tick()

    expected = _airing_at(clock.now())
    tunes = _tune_commands(player)
    assert tunes[-1].filename == expected.episode.filename


def test_early_eof_on_last_slot_holds_slate(tmp_path: Path) -> None:
    last_slot = _little_bear_timeline(JULY_MORNING.date()).slots[-1]
    last_start = datetime(
        2024,
        7,
        15,
        int(last_slot.start_hour),
        int(round((last_slot.start_hour % 1) * 60)),
        tzinfo=VANCOUVER,
    )
    clock = FakeClock.trusted(last_start)
    controller, _, player, _ = _controller(tmp_path, clock=clock)
    _wake(controller)
    player.mark_playback_ended()
    controller.tick()

    assert player.showing_slate is True
    assert controller.now_playing() == NOW_PLAYING_SLATE
    assert _fade_commands(player) == ()


def test_television_module_does_not_import_metadata_source() -> None:
    import tv90.application.television as television

    assert television.__file__ is not None
    source = Path(television.__file__).read_text(encoding="utf-8")
    assert "EpisodeMetadata" not in source
    assert "tvmaze" not in source.lower()
    assert "keyword_rules" not in source
    assert "preview_tags" not in source
    assert "index_library_durations" not in source
    assert "write_duration_index" not in source
