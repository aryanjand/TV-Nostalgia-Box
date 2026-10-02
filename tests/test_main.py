import ast
import threading
import time
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from flask.testing import FlaskClient

from tv90.adapters.fake_clock import FakeClock
from tv90.adapters.fake_duration import FakeDurationIndex, FakeMediaProber
from tv90.adapters.fake_library import FakeLibrarySource
from tv90.adapters.fake_player import FakePlayer, LoadCommand
from tv90.adapters.fake_tv_power import FakeTvPower
from tv90.application.simulate import DURATION_INDEX_FILENAME
from tv90.application.television import (
    NOW_PLAYING_SLATE,
    TICK_INTERVAL_SECONDS,
)
from tv90.config import DEFAULT_LIBRARY_PATH, load_settings
from tv90.domain.duration import DurationUnknownError
from tv90.domain.filename import parse_filename
from tv90.domain.timeline import SECONDS_PER_HOUR
from tv90.interface.remote import REMOTE_BIND_HOST, REMOTE_BIND_PORT
from tv90.main import (
    REMOTE_THREAD_NAME,
    AbsentFileDurationIndex,
    LibraryPathPlayer,
    LibraryPathProber,
    build_runtime,
    run_service,
)
from tv90.ports.player import format_channel_banner

VANCOUVER = ZoneInfo("America/Vancouver")
JULY_MORNING = datetime(2024, 7, 15, 7, 0, tzinfo=VANCOUVER)
LITTLE_BEAR_ONE = parse_filename("LittleBear_S01E01.mp4")
LITTLE_BEAR_TWO = parse_filename("LittleBear_S01E02.mp4")
OSWALD_ONE = parse_filename("Oswald_S01E01.mp4")
HARRY_ONE = parse_filename("Harry_S01E01.mp4")
DAYTIME_LIBRARY = (LITTLE_BEAR_ONE, LITTLE_BEAR_TWO, OSWALD_ONE, HARRY_ONE)
HOUR_DURATIONS = {
    episode.filename: float(SECONDS_PER_HOUR) for episode in DAYTIME_LIBRARY
}
MAIN_SOURCE = Path(__file__).resolve().parents[1] / "src" / "tv90" / "main.py"
FLASK_ROUTE_NAMES = frozenset(
    {
        "CHANNEL_UP_PATH",
        "CHANNEL_DOWN_PATH",
        "VOLUME_UP_PATH",
        "VOLUME_DOWN_PATH",
        "home",
        "channel_up",
        "channel_down",
        "volume_up",
        "volume_down",
    }
)


def _noop_wait(_seconds: float) -> None:
    return None


def test_build_runtime_with_fakes_now_playing_works() -> None:
    runtime = build_runtime(
        {},
        clock=FakeClock.trusted(JULY_MORNING),
        player=FakePlayer(load_settings({})),
        tv_power=FakeTvPower(),
        library=FakeLibrarySource(DAYTIME_LIBRARY),
        duration_index=FakeDurationIndex(HOUR_DURATIONS),
        wait=_noop_wait,
    )

    assert runtime.controller.now_playing() == "clock not synced"
    runtime.controller.tick()
    assert runtime.controller.now_playing() == NOW_PLAYING_SLATE
    runtime.controller.channel_up()
    playing = runtime.controller.now_playing()
    assert playing.startswith(f"{format_channel_banner(1)} LittleBear_")


def test_build_runtime_defaults_library_path_to_srv_mount() -> None:
    runtime = build_runtime(
        {},
        clock=FakeClock.trusted(JULY_MORNING),
        player=FakePlayer(load_settings({})),
        tv_power=FakeTvPower(),
        library=FakeLibrarySource(DAYTIME_LIBRARY),
        duration_index=FakeDurationIndex(HOUR_DURATIONS),
        wait=_noop_wait,
    )

    assert runtime.library_path == DEFAULT_LIBRARY_PATH


def test_build_runtime_reads_library_path_from_environ(tmp_path: Path) -> None:
    runtime = build_runtime(
        {"TV90_LIBRARY_PATH": str(tmp_path)},
        clock=FakeClock.trusted(JULY_MORNING),
        player=FakePlayer(load_settings({})),
        tv_power=FakeTvPower(),
        library=FakeLibrarySource(DAYTIME_LIBRARY),
        duration_index=FakeDurationIndex(HOUR_DURATIONS),
        wait=_noop_wait,
    )

    assert runtime.library_path == tmp_path


def test_build_runtime_remote_app_uses_controller_now_playing() -> None:
    runtime = build_runtime(
        {},
        clock=FakeClock.trusted(JULY_MORNING),
        player=FakePlayer(load_settings({})),
        tv_power=FakeTvPower(),
        library=FakeLibrarySource(DAYTIME_LIBRARY),
        duration_index=FakeDurationIndex(HOUR_DURATIONS),
        wait=_noop_wait,
    )
    client: FlaskClient = runtime.remote_app.test_client()

    response = client.get("/")

    assert response.status_code == 200
    assert b"clock not synced" in response.data


def test_library_path_player_resolves_basenames_for_mpv() -> None:
    settings = load_settings({})
    inner = FakePlayer(settings)
    player = LibraryPathPlayer(inner, Path("/srv/90stv/library"))

    player.load(LITTLE_BEAR_ONE.filename, 12.0)

    assert inner.commands == (
        LoadCommand("/srv/90stv/library/LittleBear_S01E01.mp4", 12.0),
    )


def test_library_path_prober_resolves_basenames_for_ffprobe() -> None:
    prober = LibraryPathProber(
        FakeMediaProber({"/srv/90stv/library/LittleBear_S01E01.mp4": 420.0}),
        Path("/srv/90stv/library"),
    )

    assert prober.duration_seconds(LITTLE_BEAR_ONE.filename) == 420.0


def test_absent_duration_index_is_unknown_when_file_missing(tmp_path: Path) -> None:
    index = AbsentFileDurationIndex(tmp_path / DURATION_INDEX_FILENAME)

    try:
        index.duration_seconds(LITTLE_BEAR_ONE.filename)
    except DurationUnknownError as error:
        assert error.filename == LITTLE_BEAR_ONE.filename
    else:
        raise AssertionError("missing duration index must be a miss, not a crash")


def test_run_service_ticks_without_binding_flask() -> None:
    settings = load_settings({})
    runtime = build_runtime(
        {},
        clock=FakeClock.trusted(JULY_MORNING),
        player=FakePlayer(settings),
        tv_power=FakeTvPower(),
        library=FakeLibrarySource(DAYTIME_LIBRARY),
        duration_index=FakeDurationIndex(HOUR_DURATIONS),
        wait=_noop_wait,
    )
    stop = threading.Event()
    started: list[str] = []

    def start_remote(app: object) -> None:
        started.append(app.__class__.__name__)

    worker = threading.Thread(
        target=run_service,
        args=(runtime, stop),
        kwargs={"start_remote": start_remote},
        daemon=True,
    )
    worker.start()
    deadline = time.monotonic() + 2.0
    while time.monotonic() < deadline:
        if runtime.controller.now_playing() == NOW_PLAYING_SLATE:
            break
        time.sleep(0.01)
    assert runtime.controller.now_playing() == NOW_PLAYING_SLATE
    runtime.controller.channel_up()
    stop.set()
    worker.join(timeout=2.0)

    assert started == ["Flask"]
    assert runtime.controller.now_playing().startswith("CH 01")
    assert TICK_INTERVAL_SECONDS == 0.25


def test_main_does_not_import_flask_routes_beyond_create_remote_app() -> None:
    source = MAIN_SOURCE.read_text(encoding="utf-8")
    tree = ast.parse(source)
    remote_names: set[str] = set()
    flask_names: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.ImportFrom):
            continue
        imported = {alias.name for alias in node.names}
        if node.module == "tv90.interface.remote":
            remote_names.update(imported)
        if node.module == "flask":
            flask_names.update(imported)

    assert "create_remote_app" in remote_names
    assert remote_names <= {"create_remote_app", "REMOTE_BIND_HOST", "REMOTE_BIND_PORT"}
    assert flask_names <= {"Flask"}
    assert FLASK_ROUTE_NAMES.isdisjoint(remote_names)
    assert "app.run" not in source or "use_reloader=False" in source
    assert REMOTE_BIND_HOST == "0.0.0.0"
    assert REMOTE_BIND_PORT == 5000
    assert REMOTE_THREAD_NAME == "tv90-remote"
