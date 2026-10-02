"""End-to-end broadcast week with fakes. No Pi, no mpv, no network."""

from __future__ import annotations

import shutil
from dataclasses import fields
from datetime import date, datetime, timedelta
from http import HTTPStatus
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
from flask.testing import FlaskClient

from tv90.adapters.fake_clock import FakeClock
from tv90.adapters.fake_duration import FakeDurationIndex
from tv90.adapters.fake_interstitial_catalog import FakeInterstitialCatalog
from tv90.adapters.fake_library import FakeLibrarySource
from tv90.adapters.fake_player import (
    FakePlayer,
    LoadCommand,
    TunerChangeCommand,
)
from tv90.adapters.fake_tv_power import FakeTvPower
from tv90.adapters.filesystem_library import FilesystemLibrarySource
from tv90.adapters.tvmaze_metadata import METADATA_CACHE_FILENAME
from tv90.application.simulate import (
    CARTOON_FALLBACK_DURATION_SECONDS,
    HOLIDAY_MOVIE_FALLBACK_DURATION_SECONDS,
)
from tv90.application.television import (
    NOW_PLAYING_CLOCK_NOT_SYNCED,
    NOW_PLAYING_OFF_AIR,
    NOW_PLAYING_SLATE,
    TelevisionCollaborators,
    TelevisionController,
)
from tv90.config import (
    COMMAND_COOLDOWN_MILLISECONDS,
    HARRY_CHANNEL_NUMBER,
    HARRY_SHOW_STEM,
    HOLIDAY_CHANNEL_NUMBER,
    HOLIDAY_SHOW_STEM,
    LAYER_A_EVENT_MULTIPLIER,
    LITTLE_BEAR_CHANNEL_NUMBER,
    LITTLE_BEAR_SHOW_STEM,
    OSWALD_CHANNEL_NUMBER,
    OSWALD_SHOW_STEM,
    WRONG_SEASON_WEIGHT,
    Settings,
    load_settings,
)
from tv90.domain.episode import Daypart, Episode, HolidayTag
from tv90.domain.filename import parse_filename
from tv90.domain.holiday_calendar import HolidayCalendar, load_holiday_calendar
from tv90.interface.remote import create_remote_app
from tv90.ports.player import format_channel_banner

VANCOUVER = ZoneInfo("America/Vancouver")
SAMPLE_LIBRARY = Path(__file__).resolve().parent / "fixtures" / "sample_library"
JULY_WEEK_START = date(2024, 7, 15)
JULY_WEEK_DAYS = 7
HALLOWEEN = date(2024, 10, 31)
DAY_AFTER_HALLOWEEN = date(2024, 11, 1)
COOLDOWN = timedelta(milliseconds=COMMAND_COOLDOWN_MILLISECONDS)
SHORT_CLOCK_TRUST_TIMEOUT_SECONDS = "5"
SHORT_CLOCK_TRUST_TIMEOUT = timedelta(seconds=5)

SHOW_STEM_BY_CHANNEL = {
    LITTLE_BEAR_CHANNEL_NUMBER: LITTLE_BEAR_SHOW_STEM,
    OSWALD_CHANNEL_NUMBER: OSWALD_SHOW_STEM,
    HARRY_CHANNEL_NUMBER: HARRY_SHOW_STEM,
    HOLIDAY_CHANNEL_NUMBER: HOLIDAY_SHOW_STEM,
}
REMOTE_BUTTONS = (
    "CHANNEL UP",
    "CHANNEL DOWN",
    "VOLUME UP",
    "VOLUME DOWN",
)
ALLOWED_REMOTE_ACTIONS = {
    ("/", "GET"),
    ("/channel/up", "POST"),
    ("/channel/down", "POST"),
    ("/volume/up", "POST"),
    ("/volume/down", "POST"),
}
PASSIVE_HTTP_METHODS = frozenset({"HEAD", "OPTIONS"})
ABSENT_MENU_PATHS = (
    "/episodes",
    "/search",
    "/catalog",
    "/catalog.json",
    "/files",
    "/ws",
    "/thumbnails",
    "/up-next",
    "/api/episodes",
    "/static/",
)
RUNTIME_WRITE_NAMES = frozenset(
    {"duration-index.json", ".tv90-metadata-cache.json", ".tv90-maintenance"}
)
PLAYBACK_COLLABORATOR_FIELDS = frozenset(
    {
        "clock",
        "player",
        "tv_power",
        "library",
        "interstitial_catalog",
        "duration_index",
        "settings",
        "holiday_calendar",
        "library_root",
        "wait",
        "logger",
    }
)


class YankablePlayer(FakePlayer):
    """Pretend a library file vanished mid-week. Raises like a missing disk read."""

    def __init__(self, settings: Settings) -> None:
        super().__init__(settings)
        self._yanked: set[str] = set()

    def yank(self, filename: str) -> None:
        self._yanked.add(filename)

    def load(self, filename: str, offset_seconds: float) -> None:
        self._reject_if_yanked(filename)
        super().load(filename, offset_seconds)

    def fade_to_next(self, filename: str, offset_seconds: float) -> None:
        self._reject_if_yanked(filename)
        super().fade_to_next(filename, offset_seconds)

    def tune_to(self, filename: str, offset_seconds: float) -> None:
        self._reject_if_yanked(filename)
        super().tune_to(filename, offset_seconds)

    def play_interstitial(self, filename: str, offset_seconds: float) -> None:
        self._reject_if_yanked(filename)
        super().play_interstitial(filename, offset_seconds)

    def _reject_if_yanked(self, filename: str) -> None:
        if filename in self._yanked:
            raise OSError(f"yanked {filename}")


def _noop_wait(_seconds: float) -> None:
    return None


def _sample_episodes() -> tuple[Episode, ...]:
    return FilesystemLibrarySource(SAMPLE_LIBRARY).episodes()


def _durations_for(episodes: tuple[Episode, ...]) -> dict[str, float]:
    return {
        episode.filename: (
            HOLIDAY_MOVIE_FALLBACK_DURATION_SECONDS
            if episode.show_stem == HOLIDAY_SHOW_STEM
            else CARTOON_FALLBACK_DURATION_SECONDS
        )
        for episode in episodes
    }


def _at(on_date: date, hour: int, minute: int = 0) -> datetime:
    return datetime(
        on_date.year, on_date.month, on_date.day, hour, minute, tzinfo=VANCOUVER
    )


def _advance_to(clock: FakeClock, moment: datetime) -> None:
    delta = moment - clock.now()
    assert delta >= timedelta(0)
    if delta:
        clock.advance_time(delta)


def _fingerprint(directory: Path) -> dict[str, tuple[int, int]]:
    return {
        path.name: (path.stat().st_size, path.stat().st_mtime_ns)
        for path in sorted(directory.iterdir())
        if path.is_file()
    }


def _make_read_only(directory: Path) -> None:
    for path in directory.iterdir():
        if path.is_file():
            path.chmod(0o444)
    directory.chmod(0o555)


def _make_writable(directory: Path) -> None:
    directory.chmod(0o755)
    for path in directory.iterdir():
        if path.is_file():
            path.chmod(0o644)


def _copy_library(source: Path, dest: Path) -> Path:
    shutil.copytree(
        source,
        dest,
        ignore=shutil.ignore_patterns(METADATA_CACHE_FILENAME),
    )
    return dest


def _copy_read_only_library(tmp_path: Path) -> Path:
    library_dir = _copy_library(SAMPLE_LIBRARY, tmp_path / "library")
    _make_read_only(library_dir)
    return library_dir


def _controller(
    library_root: Path,
    *,
    clock: FakeClock,
    player: FakePlayer | None = None,
    tv_power: FakeTvPower | None = None,
    settings: Settings | None = None,
    library: FakeLibrarySource | FilesystemLibrarySource | None = None,
) -> tuple[
    TelevisionController,
    FakeClock,
    FakePlayer,
    FakeTvPower,
    HolidayCalendar,
]:
    resolved_settings = settings if settings is not None else load_settings({})
    calendar = load_holiday_calendar({}, resolved_settings)
    episodes = _sample_episodes()
    resolved_library: FakeLibrarySource | FilesystemLibrarySource = (
        library if library is not None else FakeLibrarySource(episodes=episodes)
    )
    resolved_player = player if player is not None else FakePlayer(resolved_settings)
    resolved_power = tv_power if tv_power is not None else FakeTvPower()
    controller = TelevisionController(
        TelevisionCollaborators(
            clock=clock,
            player=resolved_player,
            tv_power=resolved_power,
            library=resolved_library,
            interstitial_catalog=FakeInterstitialCatalog(),
            duration_index=FakeDurationIndex(_durations_for(episodes)),
            settings=resolved_settings,
            holiday_calendar=calendar,
            library_root=library_root,
            wait=_noop_wait,
        )
    )
    return controller, clock, resolved_player, resolved_power, calendar


def _wake(controller: TelevisionController) -> None:
    controller.tick()
    controller.channel_up()


def _join_live(
    controller: TelevisionController,
    clock: FakeClock,
    player: FakePlayer,
    moment: datetime,
) -> None:
    _advance_to(clock, moment)
    player.mark_playback_ended()
    controller.tick()


def _parse_playing(line: str) -> tuple[int, Episode]:
    body = line.removesuffix(f" {NOW_PLAYING_CLOCK_NOT_SYNCED}")
    banner_channel, filename = body.split(" ", 1)
    assert banner_channel == "CH"
    channel_token, filename = filename.split(" ", 1)
    channel_number = int(channel_token)
    assert format_channel_banner(channel_number) in line
    return channel_number, parse_filename(filename)


def _require_playing(controller: TelevisionController) -> tuple[int, Episode]:
    line = controller.now_playing()
    assert line not in {
        NOW_PLAYING_CLOCK_NOT_SYNCED,
        NOW_PLAYING_OFF_AIR,
        NOW_PLAYING_SLATE,
    }
    return _parse_playing(line)


def _assert_show_isolation(channel_number: int, episode: Episode) -> None:
    assert episode.show_stem == SHOW_STEM_BY_CHANNEL[channel_number]


def _surf_wrap(
    controller: TelevisionController,
    clock: FakeClock,
) -> tuple[int, ...]:
    visited = [_require_playing(controller)[0]]
    for _ in range(5):
        clock.advance_time(COOLDOWN)
        controller.channel_up()
        channel_number, episode = _require_playing(controller)
        _assert_show_isolation(channel_number, episode)
        visited.append(channel_number)
        if len(visited) > 1 and channel_number == LITTLE_BEAR_CHANNEL_NUMBER:
            break
    return tuple(visited)


def _page_text(client: FlaskClient) -> str:
    response = client.get("/")
    assert response.status_code == HTTPStatus.OK
    return response.get_data(as_text=True)


def test_e2e_library_copy_skips_leftover_metadata_cache(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    (source / "LittleBear_S01E01.mp4").write_bytes(b"")
    (source / METADATA_CACHE_FILENAME).write_text("{}\n", encoding="utf-8")

    dest = _copy_library(source, tmp_path / "library")

    assert (dest / "LittleBear_S01E01.mp4").is_file()
    assert not (dest / METADATA_CACHE_FILENAME).exists()


def test_july_week_cartoon_channels_dayparts_and_show_isolation(
    tmp_path: Path,
) -> None:
    library_dir = _copy_read_only_library(tmp_path)
    before = _fingerprint(library_dir)
    clock = FakeClock.trusted(_at(JULY_WEEK_START, 6, 30))
    controller, clock, player, _power, _calendar = _controller(
        library_dir,
        clock=clock,
        library=FilesystemLibrarySource(library_dir),
    )
    _wake(controller)

    morning_dayparts: list[Daypart] = []
    midday_dayparts: list[Daypart] = []
    evening_dayparts: list[Daypart] = []

    for day_offset in range(JULY_WEEK_DAYS):
        on_date = JULY_WEEK_START + timedelta(days=day_offset)
        for hour, minute, bucket in (
            (7, 0, morning_dayparts),
            (8, 0, morning_dayparts),
            (9, 0, morning_dayparts),
            (11, 0, midday_dayparts),
            (13, 0, midday_dayparts),
            (15, 0, midday_dayparts),
            (19, 0, evening_dayparts),
            (20, 0, evening_dayparts),
            (20, 45, evening_dayparts),
        ):
            _join_live(controller, clock, player, _at(on_date, hour, minute))
            channel_number, episode = _require_playing(controller)
            assert channel_number == LITTLE_BEAR_CHANNEL_NUMBER
            _assert_show_isolation(channel_number, episode)
            assert HOLIDAY_SHOW_STEM not in episode.filename
            bucket.append(episode.daypart)

        wrap = _surf_wrap(controller, clock)
        assert HOLIDAY_CHANNEL_NUMBER not in wrap
        assert wrap == (
            LITTLE_BEAR_CHANNEL_NUMBER,
            OSWALD_CHANNEL_NUMBER,
            HARRY_CHANNEL_NUMBER,
            LITTLE_BEAR_CHANNEL_NUMBER,
        )
        clock.advance_time(COOLDOWN)
        controller.channel_down()
        down_channel, down_episode = _require_playing(controller)
        assert down_channel == HARRY_CHANNEL_NUMBER
        _assert_show_isolation(down_channel, down_episode)
        clock.advance_time(COOLDOWN)
        controller.channel_up()
        assert _require_playing(controller)[0] == LITTLE_BEAR_CHANNEL_NUMBER

    assert morning_dayparts.count(Daypart.MORNING) > morning_dayparts.count(
        Daypart.NIGHT
    )
    assert Daypart.MORNING in morning_dayparts
    assert evening_dayparts.count(Daypart.NIGHT) > evening_dayparts.count(
        Daypart.MORNING
    )
    assert Daypart.NIGHT in evening_dayparts
    assert midday_dayparts.count(Daypart.GENERAL) > midday_dayparts.count(
        Daypart.MORNING
    )
    assert midday_dayparts.count(Daypart.GENERAL) > midday_dayparts.count(Daypart.NIGHT)

    assert _fingerprint(library_dir) == before
    assert RUNTIME_WRITE_NAMES.isdisjoint(_fingerprint(library_dir))
    with pytest.raises(PermissionError):
        (library_dir / "should-not-survive.mp4").write_bytes(b"x")
    _make_writable(library_dir)


def test_halloween_opens_channel_four_with_layer_a_and_holiday_movies(
    tmp_path: Path,
) -> None:
    clock = FakeClock.trusted(_at(HALLOWEEN, 8, 0))
    controller, clock, player, _power, calendar = _controller(tmp_path, clock=clock)
    _wake(controller)

    halloween_cartoon = parse_filename("LittleBear_S01E09_HALLOWEEN.mp4")
    assert calendar.channel_four_open(HALLOWEEN) is True
    assert calendar.active_holiday(HALLOWEEN) is HolidayTag.HALLOWEEN
    assert calendar.layer_a_multiplier(halloween_cartoon, HALLOWEEN) == pytest.approx(
        LAYER_A_EVENT_MULTIPLIER
    )
    assert calendar.layer_a_multiplier(
        halloween_cartoon, JULY_WEEK_START
    ) == pytest.approx(WRONG_SEASON_WEIGHT)

    wrap = _surf_wrap(controller, clock)
    assert wrap == (
        LITTLE_BEAR_CHANNEL_NUMBER,
        OSWALD_CHANNEL_NUMBER,
        HARRY_CHANNEL_NUMBER,
        HOLIDAY_CHANNEL_NUMBER,
        LITTLE_BEAR_CHANNEL_NUMBER,
    )

    clock.advance_time(COOLDOWN)
    controller.channel_down()
    channel_number, episode = _require_playing(controller)
    assert channel_number == HOLIDAY_CHANNEL_NUMBER
    _assert_show_isolation(channel_number, episode)
    assert episode.holiday_tag is HolidayTag.HALLOWEEN
    assert "CHRISTMAS" not in episode.filename
    assert "THANKSGIVING" not in episode.filename
    assert "EASTER" not in episode.filename
    assert episode.show_stem == HOLIDAY_SHOW_STEM

    _join_live(controller, clock, player, _at(HALLOWEEN, 13, 0))
    channel_number, episode = _require_playing(controller)
    assert channel_number == HOLIDAY_CHANNEL_NUMBER
    assert episode.holiday_tag is HolidayTag.HALLOWEEN

    clock.advance_time(COOLDOWN)
    controller.channel_up()
    channel_number, episode = _require_playing(controller)
    assert channel_number == LITTLE_BEAR_CHANNEL_NUMBER
    _assert_show_isolation(channel_number, episode)
    assert episode.show_stem == LITTLE_BEAR_SHOW_STEM


def test_day_after_halloween_drops_channel_four_and_coerces_stale(
    tmp_path: Path,
) -> None:
    clock = FakeClock.trusted(_at(HALLOWEEN, 16, 0))
    controller, clock, player, _power, calendar = _controller(tmp_path, clock=clock)
    _wake(controller)
    wrap = _surf_wrap(controller, clock)
    assert HOLIDAY_CHANNEL_NUMBER in wrap
    clock.advance_time(COOLDOWN)
    controller.channel_down()
    assert _require_playing(controller)[0] == HOLIDAY_CHANNEL_NUMBER

    _advance_to(clock, _at(DAY_AFTER_HALLOWEEN, 7, 0))
    controller.tick()

    assert calendar.channel_four_open(DAY_AFTER_HALLOWEEN) is False
    channel_number, episode = _require_playing(controller)
    assert channel_number == LITTLE_BEAR_CHANNEL_NUMBER
    _assert_show_isolation(channel_number, episode)
    wrap_after = _surf_wrap(controller, clock)
    assert HOLIDAY_CHANNEL_NUMBER not in wrap_after
    assert wrap_after == (
        LITTLE_BEAR_CHANNEL_NUMBER,
        OSWALD_CHANNEL_NUMBER,
        HARRY_CHANNEL_NUMBER,
        LITTLE_BEAR_CHANNEL_NUMBER,
    )


def test_night_lock_off_air_survives_midnight_then_morning_idle_until_wake(
    tmp_path: Path,
) -> None:
    clock = FakeClock.trusted(_at(JULY_WEEK_START, 20, 50))
    controller, clock, player, power, _calendar = _controller(tmp_path, clock=clock)
    _wake(controller)
    assert _require_playing(controller)[0] == LITTLE_BEAR_CHANNEL_NUMBER

    _advance_to(clock, _at(JULY_WEEK_START, 21, 0))
    controller.tick()
    controller.channel_up()
    controller.volume_up()

    assert power.commands == ()
    assert power.is_in_standby() is False
    assert player.showing_slate is True
    assert controller.now_playing() == NOW_PLAYING_OFF_AIR

    next_morning = JULY_WEEK_START + timedelta(days=1)
    _advance_to(clock, _at(next_morning, 0, 15))
    controller.tick()
    controller.channel_down()
    assert power.commands == ()
    assert controller.now_playing() == NOW_PLAYING_OFF_AIR

    _advance_to(clock, _at(next_morning, 5, 0))
    controller.tick()
    assert controller.now_playing() == NOW_PLAYING_OFF_AIR

    _advance_to(clock, _at(next_morning, 6, 30))
    controller.tick()

    assert power.commands == ()
    assert controller.now_playing() == NOW_PLAYING_SLATE
    assert player.showing_slate is True

    controller.channel_up()

    assert power.commands == ()
    channel_number, episode = _require_playing(controller)
    assert channel_number == LITTLE_BEAR_CHANNEL_NUMBER
    _assert_show_isolation(channel_number, episode)
    loads = tuple(
        command for command in player.commands if isinstance(command, LoadCommand)
    )
    assert loads[-1].offset_seconds == pytest.approx(0.0)


def test_trusted_clock_timeout_then_sync_retunes(tmp_path: Path) -> None:
    settings = load_settings(
        {"TV90_CLOCK_TRUST_TIMEOUT_SECONDS": SHORT_CLOCK_TRUST_TIMEOUT_SECONDS}
    )
    clock = FakeClock.untrusted(_at(JULY_WEEK_START, 8, 0))
    controller, clock, player, _power, _calendar = _controller(
        tmp_path, clock=clock, settings=settings
    )

    controller.tick()
    assert controller.now_playing() == NOW_PLAYING_CLOCK_NOT_SYNCED
    assert player.showing_slate is True

    clock.advance_time(SHORT_CLOCK_TRUST_TIMEOUT - timedelta(seconds=1))
    controller.tick()
    assert controller.now_playing() == NOW_PLAYING_CLOCK_NOT_SYNCED

    clock.advance_time(timedelta(seconds=2))
    controller.tick()
    assert controller.now_playing() == NOW_PLAYING_SLATE
    assert player.showing_slate is True
    assert (
        tuple(
            command for command in player.commands if isinstance(command, LoadCommand)
        )
        == ()
    )

    controller.channel_up()
    line = controller.now_playing()
    assert NOW_PLAYING_CLOCK_NOT_SYNCED in line
    channel_number, episode = _parse_playing(line)
    _assert_show_isolation(channel_number, episode)
    loads = tuple(
        command for command in player.commands if isinstance(command, LoadCommand)
    )
    assert loads

    clock.mark_trusted()
    controller.tick()
    trusted_line = controller.now_playing()
    assert NOW_PLAYING_CLOCK_NOT_SYNCED not in trusted_line
    tunes = tuple(
        command
        for command in player.commands
        if isinstance(command, TunerChangeCommand)
    )
    assert tunes
    _require_playing(controller)


def test_yanked_file_fail_soft_controller_keeps_ticking(tmp_path: Path) -> None:
    settings = load_settings({})
    clock = FakeClock.trusted(_at(JULY_WEEK_START, 8, 0))
    player = YankablePlayer(settings)
    controller, clock, _, _power, _calendar = _controller(
        tmp_path, clock=clock, player=player, settings=settings
    )
    _wake(controller)
    _channel, playing = _require_playing(controller)
    assert playing.show_stem == LITTLE_BEAR_SHOW_STEM

    for episode in _sample_episodes():
        if episode.show_stem == LITTLE_BEAR_SHOW_STEM:
            player.yank(episode.filename)

    player.mark_playback_ended()
    controller.tick()
    assert controller.now_playing() == NOW_PLAYING_SLATE

    clock.advance_time(COOLDOWN)
    controller.channel_up()
    channel_number, episode = _require_playing(controller)
    assert channel_number == OSWALD_CHANNEL_NUMBER
    _assert_show_isolation(channel_number, episode)

    _join_live(controller, clock, player, _at(JULY_WEEK_START, 13, 0))
    channel_number, episode = _require_playing(controller)
    assert channel_number == OSWALD_CHANNEL_NUMBER
    _assert_show_isolation(channel_number, episode)

    next_day = JULY_WEEK_START + timedelta(days=2)
    _join_live(controller, clock, player, _at(next_day, 8, 0))
    channel_number, episode = _require_playing(controller)
    assert channel_number == OSWALD_CHANNEL_NUMBER
    controller.tick()
    assert controller.now_playing() != NOW_PLAYING_CLOCK_NOT_SYNCED


def test_e2e_web_remote_has_only_four_buttons_and_now_playing(tmp_path: Path) -> None:
    clock = FakeClock.trusted(_at(JULY_WEEK_START, 8, 0))
    controller, _clock, _player, _power, _calendar = _controller(tmp_path, clock=clock)
    _wake(controller)
    app = create_remote_app(controller)
    client = app.test_client()

    html = _page_text(client)
    playing = controller.now_playing()
    assert playing in html
    for label in REMOTE_BUTTONS:
        assert label in html
    assert html.lower().count("<form") == 4
    assert "<script" not in html.lower()
    assert "<video" not in html.lower()

    actions = {
        (rule.rule, method)
        for rule in app.url_map.iter_rules()
        for method in (rule.methods or set())
        if method not in PASSIVE_HTTP_METHODS
    }
    assert actions == ALLOWED_REMOTE_ACTIONS
    for path in ABSENT_MENU_PATHS:
        assert client.get(path).status_code == HTTPStatus.NOT_FOUND


def test_e2e_playback_collaborators_have_no_metadata_source(tmp_path: Path) -> None:
    clock = FakeClock.trusted(_at(JULY_WEEK_START, 8, 0))
    controller, clock, player, _power, _calendar = _controller(tmp_path, clock=clock)
    _wake(controller)
    _join_live(controller, clock, player, _at(JULY_WEEK_START, 13, 0))
    _surf_wrap(controller, clock)

    collaborator_fields = tuple(fields(TelevisionCollaborators))
    names = {item.name for item in collaborator_fields}
    assert names == PLAYBACK_COLLABORATOR_FIELDS
    annotation_text = " ".join(
        f"{name} {hint}"
        for name, hint in TelevisionCollaborators.__annotations__.items()
    )
    assert "metadata" not in annotation_text.lower()
    assert "EpisodeMetadataSource" not in annotation_text
    assert not any("metadata" in item.name.lower() for item in collaborator_fields)
    assert not any("metadata" in str(item.type).lower() for item in collaborator_fields)
    _require_playing(controller)
