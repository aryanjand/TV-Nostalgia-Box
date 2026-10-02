from datetime import datetime, timedelta
from http import HTTPStatus
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
from flask.testing import FlaskClient

from tv90.adapters.fake_clock import FakeClock
from tv90.adapters.fake_duration import FakeDurationIndex
from tv90.adapters.fake_library import FakeLibrarySource
from tv90.adapters.fake_player import (
    FakePlayer,
    SetVolumeCommand,
    ShowVolumeBarCommand,
    TunerChangeCommand,
)
from tv90.adapters.fake_tv_power import FakeTvPower
from tv90.application.television import (
    NOW_PLAYING_CLOCK_NOT_SYNCED,
    VOLUME_STEP,
    TelevisionCollaborators,
    TelevisionController,
)
from tv90.config import (
    COMMAND_COOLDOWN_MILLISECONDS,
    HARRY_CHANNEL_NUMBER,
    LITTLE_BEAR_CHANNEL_NUMBER,
    OSWALD_CHANNEL_NUMBER,
    VOLUME_DEFAULT,
    load_settings,
)
from tv90.domain.filename import parse_filename
from tv90.domain.holiday_calendar import HolidayCalendar
from tv90.domain.timeline import SECONDS_PER_HOUR
from tv90.interface.remote import create_remote_app
from tv90.ports.player import format_channel_banner

VANCOUVER = ZoneInfo("America/Vancouver")
JULY_MORNING = datetime(2024, 7, 15, 7, 0, tzinfo=VANCOUVER)
COOLDOWN = timedelta(milliseconds=COMMAND_COOLDOWN_MILLISECONDS)
ONE_HOUR_SECONDS = float(SECONDS_PER_HOUR)

LITTLE_BEAR_ONE = parse_filename("LittleBear_S01E01.mp4")
LITTLE_BEAR_TWO = parse_filename("LittleBear_S01E02.mp4")
OSWALD_ONE = parse_filename("Oswald_S01E01.mp4")
HARRY_ONE = parse_filename("Harry_S01E01.mp4")
DAYTIME_LIBRARY = (LITTLE_BEAR_ONE, LITTLE_BEAR_TWO, OSWALD_ONE, HARRY_ONE)
HOUR_DURATIONS = {episode.filename: ONE_HOUR_SECONDS for episode in DAYTIME_LIBRARY}

REMOTE_BUTTONS = (
    "CHANNEL UP",
    "CHANNEL DOWN",
    "VOLUME UP",
    "VOLUME DOWN",
)
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
ALLOWED_ACTIONS = {
    ("/", "GET"),
    ("/channel/up", "POST"),
    ("/channel/down", "POST"),
    ("/volume/up", "POST"),
    ("/volume/down", "POST"),
}
PASSIVE_HTTP_METHODS = frozenset({"HEAD", "OPTIONS"})


def _noop_wait(_seconds: float) -> None:
    return None


def _controller(
    tmp_path: Path,
    *,
    clock: FakeClock | None = None,
    player: FakePlayer | None = None,
) -> tuple[TelevisionController, FakeClock, FakePlayer]:
    settings = load_settings({})
    resolved_clock = clock if clock is not None else FakeClock.trusted(JULY_MORNING)
    resolved_player = player if player is not None else FakePlayer(settings)
    controller = TelevisionController(
        TelevisionCollaborators(
            clock=resolved_clock,
            player=resolved_player,
            tv_power=FakeTvPower(),
            library=FakeLibrarySource(episodes=DAYTIME_LIBRARY),
            duration_index=FakeDurationIndex(HOUR_DURATIONS),
            settings=settings,
            holiday_calendar=HolidayCalendar.from_defaults(settings),
            library_root=tmp_path,
            wait=_noop_wait,
        )
    )
    return controller, resolved_clock, resolved_player


def _wake(controller: TelevisionController) -> None:
    controller.tick()
    controller.channel_up()


def _playing_client(
    tmp_path: Path,
) -> tuple[TelevisionController, FakeClock, FakePlayer, FlaskClient]:
    controller, clock, player = _controller(tmp_path)
    _wake(controller)
    clock.advance_time(COOLDOWN)
    return controller, clock, player, create_remote_app(controller).test_client()


def _page_text(client: FlaskClient) -> str:
    response = client.get("/")
    assert response.status_code == HTTPStatus.OK
    return response.get_data(as_text=True)


def _tune_filenames(player: FakePlayer) -> tuple[str, ...]:
    return tuple(
        command.filename
        for command in player.commands
        if isinstance(command, TunerChangeCommand)
    )


def test_home_page_has_four_buttons_and_now_playing(tmp_path: Path) -> None:
    controller, _, _, client = _playing_client(tmp_path)

    html = _page_text(client)

    for label in REMOTE_BUTTONS:
        assert label in html
    assert "Now Playing" in html
    assert controller.now_playing() in html
    assert format_channel_banner(LITTLE_BEAR_CHANNEL_NUMBER) in html
    assert 'class="channel-bug"' in html
    assert "Volume" in html
    assert 'class="volume-track"' in html
    assert any(
        episode.filename in html for episode in (LITTLE_BEAR_ONE, LITTLE_BEAR_TWO)
    )


def test_home_page_shows_clock_not_synced_while_waiting(tmp_path: Path) -> None:
    controller, _, _ = _controller(tmp_path, clock=FakeClock.untrusted(JULY_MORNING))
    controller.tick()
    client = create_remote_app(controller).test_client()

    html = _page_text(client)

    assert controller.now_playing() == NOW_PLAYING_CLOCK_NOT_SYNCED
    assert NOW_PLAYING_CLOCK_NOT_SYNCED in html
    for label in REMOTE_BUTTONS:
        assert label in html


def test_channel_up_post_tunes_and_redirects_to_updated_page(tmp_path: Path) -> None:
    controller, _, player, client = _playing_client(tmp_path)

    response = client.post("/channel/up")

    assert response.status_code == HTTPStatus.SEE_OTHER
    assert response.headers["Location"].endswith("/")
    assert _tune_filenames(player)[-1] == OSWALD_ONE.filename
    followed = client.get("/")
    page = followed.get_data(as_text=True)
    assert controller.now_playing() in page
    assert format_channel_banner(OSWALD_CHANNEL_NUMBER) in page
    assert OSWALD_ONE.filename in page


def test_channel_down_post_wraps_to_harry(tmp_path: Path) -> None:
    controller, _, player, client = _playing_client(tmp_path)

    response = client.post("/channel/down", follow_redirects=True)

    assert response.status_code == HTTPStatus.OK
    assert _tune_filenames(player)[-1] == HARRY_ONE.filename
    page = response.get_data(as_text=True)
    assert controller.now_playing() in page
    assert format_channel_banner(HARRY_CHANNEL_NUMBER) in page
    assert HARRY_ONE.filename in page


def test_volume_up_post_steps_player_volume(tmp_path: Path) -> None:
    _, _, player, client = _playing_client(tmp_path)

    response = client.post("/volume/up")

    assert response.status_code == HTTPStatus.SEE_OTHER
    assert player.volume == pytest.approx(VOLUME_DEFAULT + VOLUME_STEP)
    assert any(isinstance(command, SetVolumeCommand) for command in player.commands)
    assert any(isinstance(command, ShowVolumeBarCommand) for command in player.commands)


def test_volume_down_post_steps_player_volume(tmp_path: Path) -> None:
    _, clock, player, client = _playing_client(tmp_path)
    clock.advance_time(COOLDOWN)

    response = client.post("/volume/down")

    assert response.status_code == HTTPStatus.SEE_OTHER
    assert player.volume == pytest.approx(VOLUME_DEFAULT - VOLUME_STEP)


def test_untrusted_wait_posts_still_call_controller_which_ignores(
    tmp_path: Path,
) -> None:
    controller, _, player = _controller(
        tmp_path, clock=FakeClock.untrusted(JULY_MORNING)
    )
    controller.tick()
    client = create_remote_app(controller).test_client()

    client.post("/channel/up")
    client.post("/volume/up")

    assert _tune_filenames(player) == ()
    assert player.volume == VOLUME_DEFAULT
    assert NOW_PLAYING_CLOCK_NOT_SYNCED in _page_text(client)


def test_remote_exposes_only_home_and_four_command_posts(tmp_path: Path) -> None:
    app = create_remote_app(_controller(tmp_path)[0])

    actions = {
        (rule.rule, method)
        for rule in app.url_map.iter_rules()
        for method in (rule.methods or set())
        if method not in PASSIVE_HTTP_METHODS
    }

    assert actions == ALLOWED_ACTIONS


@pytest.mark.parametrize("path", ABSENT_MENU_PATHS)
def test_catalog_search_and_listing_routes_are_absent(
    tmp_path: Path, path: str
) -> None:
    client = create_remote_app(_controller(tmp_path)[0]).test_client()

    assert client.get(path).status_code == HTTPStatus.NOT_FOUND
    assert client.post(path).status_code == HTTPStatus.NOT_FOUND


def test_home_is_html_even_when_client_asks_for_json(tmp_path: Path) -> None:
    client = create_remote_app(_controller(tmp_path)[0]).test_client()

    response = client.get("/", headers={"Accept": "application/json"})

    assert response.status_code == HTTPStatus.OK
    assert "text/html" in response.content_type
    assert not response.is_json


def test_page_is_not_an_episode_menu(tmp_path: Path) -> None:
    controller, _, _, client = _playing_client(tmp_path)

    html = _page_text(client)
    lowered = html.lower()
    playing = controller.now_playing()

    assert playing in html
    for episode in DAYTIME_LIBRARY:
        if episode.filename not in playing:
            assert episode.filename not in html
    assert "<select" not in lowered
    assert "<video" not in lowered
    assert "<img" not in lowered
    assert "<script" not in lowered
    assert "cdn" not in lowered
    assert "up next" not in lowered
    assert "search" not in lowered
