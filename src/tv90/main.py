"""Composition root for the Pi TV service. python3 -m tv90.main.

Nothing else constructs production adapters. CLI simulate/tag/index stay on
python -m tv90 so argparse is untouched.
"""

from __future__ import annotations

import os
import signal
import threading
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path

from flask import Flask

from tv90.adapters.ffprobe_prober import build_ffprobe_media_prober
from tv90.adapters.file_duration_index import FileDurationIndex
from tv90.adapters.filesystem_interstitial_catalog import FilesystemInterstitialCatalog
from tv90.adapters.filesystem_library import FilesystemLibrarySource
from tv90.adapters.mpv_ipc_player import (
    MpvIpcPlayer,
    connect_mpv_unix_socket,
    spawn_mpv_process,
)
from tv90.adapters.null_tv_power import NullTvPower
from tv90.adapters.system_clock import build_system_clock
from tv90.application.duration_lookup import DurationLookup
from tv90.application.simulate import DURATION_INDEX_FILENAME
from tv90.application.television import (
    TICK_INTERVAL_SECONDS,
    TelevisionCollaborators,
    TelevisionController,
    Wait,
)
from tv90.config import (
    Settings,
    load_interstitials_path,
    load_library_path,
    load_settings,
)
from tv90.domain.duration import DurationUnknownError
from tv90.domain.holiday_calendar import HolidayCalendar, load_holiday_calendar
from tv90.interface.remote import (
    REMOTE_BIND_HOST,
    REMOTE_BIND_PORT,
    create_remote_app,
)
from tv90.ports.clock import Clock
from tv90.ports.duration import DurationIndex, MediaProber
from tv90.ports.interstitial import InterstitialCatalog
from tv90.ports.library import LibrarySource
from tv90.ports.player import Player
from tv90.ports.tv_power import TvPower

MPV_IPC_SOCKET_PATH = Path("/run/90stv/mpv.sock")
MPV_SOCKET_WAIT_SECONDS = 0.05
MPV_SOCKET_TIMEOUT_SECONDS = 10.0
REMOTE_THREAD_NAME = "tv90-remote"
StartRemote = Callable[[Flask], None]


class LibraryPathPlayer:
    """Resolve library and interstitial names to absolute paths for mpv loadfile."""

    def __init__(
        self, player: Player, library_root: Path, interstitials_root: Path
    ) -> None:
        self._player = player
        self._library_root = library_root
        self._interstitials_root = interstitials_root

    def load(self, filename: str, offset_seconds: float) -> None:
        self._player.load(self._resolve_library(filename), offset_seconds)

    def fade_to_next(self, filename: str, offset_seconds: float) -> None:
        self._player.fade_to_next(self._resolve_library(filename), offset_seconds)

    def tune_to(self, filename: str, offset_seconds: float) -> None:
        self._player.tune_to(self._resolve_library(filename), offset_seconds)

    def play_interstitial(self, filename: str, offset_seconds: float) -> None:
        self._player.play_interstitial(
            self._resolve_interstitial(filename), offset_seconds
        )

    def show_slate(self) -> None:
        self._player.show_slate()

    def show_channel_banner(self, channel_number: int) -> None:
        self._player.show_channel_banner(channel_number)

    def show_volume_bar(self, volume: float) -> None:
        self._player.show_volume_bar(volume)

    def set_volume(self, volume: float) -> None:
        self._player.set_volume(volume)

    def stop(self) -> None:
        self._player.stop()

    def playback_has_ended(self) -> bool:
        return self._player.playback_has_ended()

    def _resolve_library(self, filename: str) -> str:
        return _resolve_under_root(filename, self._library_root)

    def _resolve_interstitial(self, filename: str) -> str:
        return _resolve_under_root(filename, self._interstitials_root)


class LibraryPathProber:
    """ffprobe needs the mount path; the index key stays the basename."""

    def __init__(self, prober: MediaProber, library_root: Path) -> None:
        self._prober = prober
        self._library_root = library_root

    def duration_seconds(self, filename: str) -> float:
        return self._prober.duration_seconds(str(self._library_root / filename))


class AbsentFileDurationIndex:
    """Missing duration-index.json is a miss so DurationLookup can probe."""

    def __init__(self, index_path: Path) -> None:
        self._index_path = index_path
        self._inner = FileDurationIndex(index_path)

    def duration_seconds(self, filename: str) -> float:
        if not self._index_path.is_file():
            raise DurationUnknownError(filename)
        return self._inner.duration_seconds(filename)


@dataclass(frozen=True)
class Runtime:
    controller: TelevisionController
    remote_app: Flask
    settings: Settings
    holiday_calendar: HolidayCalendar
    library_path: Path
    interstitials_path: Path


def build_runtime(
    environ: Mapping[str, str],
    *,
    clock: Clock,
    player: Player,
    tv_power: TvPower,
    library: LibrarySource | None = None,
    interstitial_catalog: InterstitialCatalog | None = None,
    duration_index: DurationIndex | None = None,
    wait: Wait | None = None,
    library_path: Path | None = None,
    interstitials_path: Path | None = None,
) -> Runtime:
    """Wire the controller. Tests inject fakes; production main passes real ones."""
    settings = load_settings(environ)
    holiday_calendar = load_holiday_calendar(environ, settings)
    resolved_library_path = (
        library_path if library_path is not None else load_library_path(environ)
    )
    resolved_interstitials_path = (
        interstitials_path
        if interstitials_path is not None
        else load_interstitials_path(environ)
    )
    resolved_library = (
        library
        if library is not None
        else FilesystemLibrarySource(resolved_library_path)
    )
    resolved_catalog = (
        interstitial_catalog
        if interstitial_catalog is not None
        else FilesystemInterstitialCatalog(resolved_interstitials_path)
    )
    resolved_index = (
        duration_index
        if duration_index is not None
        else _build_runtime_duration_index(resolved_library_path)
    )
    resolved_wait = time.sleep if wait is None else wait
    controller = TelevisionController(
        TelevisionCollaborators(
            clock=clock,
            player=player,
            tv_power=tv_power,
            library=resolved_library,
            interstitial_catalog=resolved_catalog,
            duration_index=resolved_index,
            settings=settings,
            holiday_calendar=holiday_calendar,
            library_root=resolved_library_path,
            wait=resolved_wait,
        )
    )
    return Runtime(
        controller=controller,
        remote_app=create_remote_app(controller),
        settings=settings,
        holiday_calendar=holiday_calendar,
        library_path=resolved_library_path,
        interstitials_path=resolved_interstitials_path,
    )


def build_production_runtime(environ: Mapping[str, str]) -> Runtime:
    """Real adapters only. Tests never call this (would spawn mpv)."""
    settings = load_settings(environ)
    library_path = load_library_path(environ)
    interstitials_path = load_interstitials_path(environ)
    return build_runtime(
        environ,
        clock=build_system_clock(settings.timezone),
        player=_build_production_player(settings, library_path, interstitials_path),
        tv_power=NullTvPower(),
        library=FilesystemLibrarySource(library_path),
        interstitial_catalog=FilesystemInterstitialCatalog(interstitials_path),
        duration_index=_build_runtime_duration_index(library_path),
        wait=time.sleep,
        library_path=library_path,
        interstitials_path=interstitials_path,
    )


def run_service(
    runtime: Runtime,
    stop_event: threading.Event,
    *,
    start_remote: StartRemote | None = None,
) -> None:
    """Tick on this thread; Flask in a daemon thread. Tests inject start_remote."""
    starter = start_remote if start_remote is not None else _start_remote_thread
    starter(runtime.remote_app)
    while not stop_event.is_set():
        runtime.controller.tick()
        stop_event.wait(TICK_INTERVAL_SECONDS)


def install_shutdown_handlers(stop_event: threading.Event) -> None:
    def _handle(_signum: int, _frame: object) -> None:
        stop_event.set()

    signal.signal(signal.SIGTERM, _handle)
    signal.signal(signal.SIGINT, _handle)


def main(environ: Mapping[str, str] | None = None) -> int:
    runtime = build_production_runtime(os.environ if environ is None else environ)
    stop_event = threading.Event()
    install_shutdown_handlers(stop_event)
    run_service(runtime, stop_event)
    return 0


def _build_runtime_duration_index(library_path: Path) -> DurationIndex:
    return DurationLookup(
        AbsentFileDurationIndex(library_path / DURATION_INDEX_FILENAME),
        LibraryPathProber(build_ffprobe_media_prober(), library_path),
    )


def _build_production_player(
    settings: Settings, library_path: Path, interstitials_path: Path
) -> Player:
    socket_path = str(MPV_IPC_SOCKET_PATH)
    spawn_mpv_process(socket_path, settings)
    _wait_for_mpv_socket(MPV_IPC_SOCKET_PATH)
    session = connect_mpv_unix_socket(socket_path)
    return LibraryPathPlayer(
        MpvIpcPlayer(settings, session.send, session.read_event),
        library_path,
        interstitials_path,
    )


def _resolve_under_root(filename: str, root: Path) -> str:
    path = Path(filename)
    if path.is_absolute():
        return str(path)
    return str(root / filename)


def _wait_for_mpv_socket(socket_path: Path) -> None:
    deadline = time.monotonic() + MPV_SOCKET_TIMEOUT_SECONDS
    while time.monotonic() < deadline:
        if socket_path.exists():
            return
        time.sleep(MPV_SOCKET_WAIT_SECONDS)
    raise TimeoutError(f"mpv IPC socket did not appear: {socket_path}")


def _start_remote_thread(app: Flask) -> None:
    thread = threading.Thread(
        target=_run_remote_app,
        args=(app,),
        name=REMOTE_THREAD_NAME,
        daemon=True,
    )
    thread.start()


def _run_remote_app(app: Flask) -> None:
    # threaded=True: two phones can POST without sharing one Werkzeug worker.
    # use_reloader=False: systemd SIGTERM must hit this process, not a child.
    app.run(
        host=REMOTE_BIND_HOST,
        port=REMOTE_BIND_PORT,
        threaded=True,
        use_reloader=False,
    )


if __name__ == "__main__":
    raise SystemExit(main())
