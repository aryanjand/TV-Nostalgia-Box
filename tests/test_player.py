import json
import math
from collections.abc import Mapping
from dataclasses import replace
from pathlib import Path

import pytest

from tv90.adapters.fake_player import (
    BLACK_FRAME_TUNER_EFFECT,
    FadeJoinCommand,
    FakePlayer,
    LoadCommand,
    SetVolumeCommand,
    ShowChannelBannerCommand,
    ShowSlateCommand,
    ShowVolumeBarCommand,
    StopCommand,
    TunerChangeCommand,
)
from tv90.adapters.mpv_ipc_player import (
    CHANNEL_OSD_FONT_SIZE,
    MILLISECONDS_PER_SECOND,
    MPV_PERCENT_VOLUME_SCALE,
    OSD_FONT_NAME,
    SLATE_OVERLAY_ID,
    TUNER_OVERLAY_ID,
    MpvIpcError,
    MpvIpcPlayer,
    MpvIpcSession,
    ass_bgr_from_hex,
    connect_mpv_unix_socket,
    decode_mpv_ipc_response,
    encode_mpv_ipc_payload,
    mpv_spawn_arguments,
)
from tv90.config import CALM_SLATE_COLOR, load_settings
from tv90.ports import Player
from tv90.ports.player import (
    InvalidVolumeError,
    format_channel_banner,
    format_volume_bar,
)

LITTLE_BEAR_FILENAME = "LittleBear_S01E01.mp4"
LITTLE_BEAR_NEXT_FILENAME = "LittleBear_S01E02.mp4"
OSWALD_FILENAME = "Oswald_S01E01.mp4"
LIBRARY_EPISODE_BYTES = b"episode-bytes"


def _player() -> FakePlayer:
    return FakePlayer(load_settings({}))


def _library_snapshot(library: Path) -> dict[str, bytes]:
    return {path.name: path.read_bytes() for path in sorted(library.iterdir())}


def test_format_channel_banner_zero_pads_two_digits() -> None:
    assert format_channel_banner(3) == "CH 03"
    assert format_channel_banner(1) == "CH 01"


def test_format_volume_bar_uses_twenty_classic_segments() -> None:
    assert format_volume_bar(0.4) == "Volume\n█ █ █ █ █ █ █ █ · · · · · · · · · · · ·"
    assert format_volume_bar(0.0) == "Volume\n· · · · · · · · · · · · · · · · · · · ·"
    assert format_volume_bar(1.0) == "Volume\n█ █ █ █ █ █ █ █ █ █ █ █ █ █ █ █ █ █ █ █"


def test_fake_player_load_seeks_to_offset_and_records_command() -> None:
    player = _player()

    player.load(LITTLE_BEAR_FILENAME, 17.5)

    assert player.current_filename == LITTLE_BEAR_FILENAME
    assert player.offset_seconds == 17.5
    assert player.showing_slate is False
    assert player.commands == (LoadCommand(LITTLE_BEAR_FILENAME, 17.5),)


def test_fake_player_fade_to_next_and_tune_to_are_different_events() -> None:
    player = _player()
    settings = load_settings({})

    player.fade_to_next(LITTLE_BEAR_NEXT_FILENAME, 0.0)
    player.tune_to(OSWALD_FILENAME, 8.25)

    fade_command, tuner_command = player.commands
    assert fade_command == FadeJoinCommand(
        filename=LITTLE_BEAR_NEXT_FILENAME,
        offset_seconds=0.0,
        fade_seconds=settings.episode_join_fade_seconds,
    )
    assert tuner_command == TunerChangeCommand(
        filename=OSWALD_FILENAME,
        offset_seconds=8.25,
        burst_milliseconds=settings.tuner_burst_milliseconds,
        effect=BLACK_FRAME_TUNER_EFFECT,
    )
    assert isinstance(fade_command, FadeJoinCommand)
    assert isinstance(tuner_command, TunerChangeCommand)
    assert player.current_filename == OSWALD_FILENAME
    assert player.offset_seconds == 8.25


def test_fake_player_show_slate_uses_named_calm_color() -> None:
    player = _player()
    player.load(LITTLE_BEAR_FILENAME, 4.0)

    player.show_slate()

    assert player.showing_slate is True
    assert player.current_filename is None
    assert player.commands[-1] == ShowSlateCommand(slate_color=CALM_SLATE_COLOR)


def test_fake_player_banner_uses_channel_format_and_settings() -> None:
    settings = replace(
        load_settings({}),
        osd_banner_seconds=2.5,
        osd_color="#00FF00",
    )
    player = FakePlayer(settings)

    player.show_channel_banner(3)

    assert player.commands == (
        ShowChannelBannerCommand(
            channel_number=3,
            banner_text="CH 03",
            color=settings.osd_color,
            duration_seconds=settings.osd_banner_seconds,
        ),
    )


def test_fake_player_show_channel_banner_does_not_sleep() -> None:
    # Instant so T12 tests can assert the request without waiting OSD_BANNER_SECONDS.
    player = _player()

    player.show_channel_banner(1)

    command = player.commands[0]
    assert isinstance(command, ShowChannelBannerCommand)
    assert command.duration_seconds == load_settings({}).osd_banner_seconds


def test_fake_player_volume_bar_records_segmented_bar() -> None:
    player = _player()

    player.show_volume_bar(0.4)

    assert player.commands == (
        ShowVolumeBarCommand(
            volume=0.4,
            bar_text="Volume\n█ █ █ █ █ █ █ █ · · · · · · · · · · · ·",
        ),
    )
    assert player.volume == load_settings({}).volume_default


def test_fake_player_set_volume_records_and_updates_state() -> None:
    player = _player()

    player.set_volume(0.55)

    assert player.volume == 0.55
    assert player.commands == (SetVolumeCommand(0.55),)


@pytest.mark.parametrize(
    "volume",
    [
        pytest.param(-0.01, id="negative"),
        pytest.param(1.01, id="above-one"),
        pytest.param(math.nan, id="nan"),
        pytest.param(math.inf, id="inf"),
        pytest.param(-math.inf, id="negative-inf"),
    ],
)
def test_fake_player_rejects_invalid_volume(volume: float) -> None:
    player = _player()

    with pytest.raises(InvalidVolumeError) as caught:
        player.set_volume(volume)

    if math.isnan(volume):
        assert math.isnan(caught.value.volume)
    else:
        assert caught.value.volume == volume
    assert player.commands == ()
    assert player.volume == load_settings({}).volume_default


@pytest.mark.parametrize(
    "volume",
    [pytest.param(-0.5, id="negative"), pytest.param(math.nan, id="nan")],
)
def test_fake_player_volume_bar_rejects_invalid_volume(volume: float) -> None:
    player = _player()

    with pytest.raises(InvalidVolumeError):
        player.show_volume_bar(volume)


def test_fake_player_playback_has_ended_query_does_not_clear() -> None:
    player = _player()
    player.load(LITTLE_BEAR_FILENAME, 0.0)

    assert player.playback_has_ended() is False
    player.mark_playback_ended()
    assert player.playback_has_ended() is True
    assert player.playback_has_ended() is True

    player.load(LITTLE_BEAR_NEXT_FILENAME, 1.0)
    assert player.playback_has_ended() is False


def test_fake_player_stop_clears_playback_and_records() -> None:
    player = _player()
    player.load(LITTLE_BEAR_FILENAME, 9.0)
    player.mark_playback_ended()

    player.stop()

    assert player.current_filename is None
    assert player.showing_slate is False
    assert player.playback_has_ended() is False
    assert player.commands[-1] == StopCommand()


def test_fake_player_starts_at_configured_default_volume() -> None:
    settings = replace(load_settings({}), volume_default=0.25)
    player = FakePlayer(settings)

    assert player.volume == 0.25
    assert player.commands == ()


def test_fake_player_satisfies_player_protocol() -> None:
    player: Player = _player()

    player.set_volume(0.4)
    player.load(LITTLE_BEAR_FILENAME, 12.0)
    player.show_channel_banner(3)
    player.show_volume_bar(0.4)
    player.fade_to_next(LITTLE_BEAR_NEXT_FILENAME, 0.0)
    player.tune_to(OSWALD_FILENAME, 5.0)
    player.show_slate()
    player.stop()

    assert isinstance(player.playback_has_ended(), bool)


def test_fake_player_does_not_write_library_files(tmp_path: Path) -> None:
    library = tmp_path / "library"
    library.mkdir()
    episode = library / LITTLE_BEAR_FILENAME
    episode.write_bytes(LIBRARY_EPISODE_BYTES)
    before = _library_snapshot(library)
    player = _player()

    player.load(str(episode), 3.0)
    player.fade_to_next(str(episode), 0.0)
    player.tune_to(str(episode), 1.0)
    player.show_slate()
    player.show_channel_banner(1)
    player.show_volume_bar(0.4)
    player.set_volume(0.3)
    player.stop()

    assert _library_snapshot(library) == before
    assert list(library.iterdir()) == [episode]


class RecordingSender:
    def __init__(self) -> None:
        self.payloads: list[dict[str, object]] = []

    def __call__(self, payload: Mapping[str, object]) -> dict[str, object]:
        self.payloads.append(dict(payload))
        return {"error": "success"}


class RecordingWait:
    def __init__(self) -> None:
        self.durations: list[float] = []

    def __call__(self, duration_seconds: float) -> None:
        self.durations.append(duration_seconds)


class ScriptedEventReader:
    def __init__(self, events: list[Mapping[str, object]]) -> None:
        self._events = list(events)

    def __call__(self) -> Mapping[str, object] | None:
        if not self._events:
            return None
        return self._events.pop(0)


def _mpv_player(
    sender: RecordingSender | None = None,
    reader: ScriptedEventReader | None = None,
) -> tuple[MpvIpcPlayer, RecordingSender, RecordingWait]:
    recording = sender if sender is not None else RecordingSender()
    waiter = RecordingWait()
    return (
        MpvIpcPlayer(load_settings({}), recording, reader, wait=waiter),
        recording,
        waiter,
    )


def _command_tokens(payload: Mapping[str, object]) -> list[object]:
    command = payload["command"]
    assert isinstance(command, list)
    return command


def _commands_named(payloads: list[dict[str, object]], name: str) -> list[list[object]]:
    named: list[list[object]] = []
    for payload in payloads:
        command = payload["command"]
        if isinstance(command, list) and command and command[0] == name:
            named.append(command)
    return named


def _overlay_commands(
    payloads: list[dict[str, object]],
) -> list[Mapping[str, object]]:
    overlays: list[Mapping[str, object]] = []
    for payload in payloads:
        command = payload["command"]
        if isinstance(command, Mapping) and command.get("name") == "osd-overlay":
            overlays.append(command)
    return overlays


def _exercise_player(player: Player) -> None:
    player.set_volume(0.4)
    player.load(LITTLE_BEAR_FILENAME, 12.0)
    player.show_channel_banner(3)
    player.show_volume_bar(0.4)
    player.fade_to_next(LITTLE_BEAR_NEXT_FILENAME, 0.0)
    player.tune_to(OSWALD_FILENAME, 5.0)
    player.show_slate()
    player.stop()


def test_mpv_load_sends_loadfile_with_start_offset() -> None:
    player, sender, _waiter = _mpv_player()

    player.load(LITTLE_BEAR_FILENAME, 17.5)

    loadfiles = _commands_named(sender.payloads, "loadfile")
    assert loadfiles == [
        [
            "loadfile",
            LITTLE_BEAR_FILENAME,
            "replace",
            -1,
            "start=17.5",
        ]
    ]


def test_mpv_set_volume_sends_percent_scale() -> None:
    player, sender, _waiter = _mpv_player()

    player.set_volume(0.4)

    assert _commands_named(sender.payloads, "set_property") == [
        ["set_property", "volume", 0.4 * MPV_PERCENT_VOLUME_SCALE]
    ]


def test_mpv_invalid_volume_raises_and_sends_nothing_new() -> None:
    player, sender, _waiter = _mpv_player()
    before = list(sender.payloads)

    with pytest.raises(InvalidVolumeError):
        player.set_volume(-0.1)

    assert sender.payloads == before


def test_mpv_channel_banner_sends_osd_without_sleeping() -> None:
    settings = replace(load_settings({}), osd_banner_seconds=2.5, osd_color="#00FF00")
    sender = RecordingSender()
    player = MpvIpcPlayer(settings, sender, wait=RecordingWait())

    player.show_channel_banner(3)

    tokens = [_command_tokens(payload) for payload in sender.payloads]
    assert ["set_property", "osd-color", "#00FF00"] in tokens
    assert ["set_property", "osd-font", OSD_FONT_NAME] in tokens
    assert ["set_property", "osd-align-x", "right"] in tokens
    assert ["set_property", "osd-align-y", "top"] in tokens
    assert ["set_property", "osd-font-size", CHANNEL_OSD_FONT_SIZE] in tokens
    assert ["show-text", "CH 03", 2500] in tokens


def test_mpv_volume_bar_sends_segmented_osd() -> None:
    player, sender, _waiter = _mpv_player()

    player.show_volume_bar(0.4)

    tokens = [_command_tokens(payload) for payload in sender.payloads]
    assert ["set_property", "osd-align-x", "left"] in tokens
    assert ["set_property", "osd-align-y", "bottom"] in tokens
    assert [
        "show-text",
        "Volume\n█ █ █ █ █ █ █ █ · · · · · · · · · · · ·",
        3000,
    ] in tokens


def test_mpv_fade_and_tune_send_different_commands() -> None:
    settings = replace(
        load_settings({}),
        episode_join_fade_seconds=1.5,
        tuner_burst_milliseconds=150,
    )
    sender = RecordingSender()
    waiter = RecordingWait()
    player = MpvIpcPlayer(settings, sender, wait=waiter)

    player.fade_to_next(LITTLE_BEAR_NEXT_FILENAME, 0.0)
    fade_payloads = list(sender.payloads)
    player.tune_to(OSWALD_FILENAME, 8.25)
    tune_payloads = sender.payloads[len(fade_payloads) :]

    fade_load = _commands_named(fade_payloads, "loadfile")[0]
    tune_load = _commands_named(tune_payloads, "loadfile")[0]
    fade_options = fade_load[4]
    tune_options = tune_load[4]
    assert isinstance(fade_options, str)
    assert isinstance(tune_options, str)
    assert "start=0.0" in fade_options
    assert "fade=t=in:st=0:d=1.5" in fade_options
    assert "afade=t=in:st=0:d=1.5" in fade_options
    assert tune_options == "start=8.25"
    assert "vf=" not in tune_options
    overlays = _overlay_commands(tune_payloads)
    shown = [overlay for overlay in overlays if overlay.get("format") == "ass-events"]
    removed = [
        overlay
        for overlay in overlays
        if overlay.get("format") == "none" and overlay.get("id") == TUNER_OVERLAY_ID
    ]
    assert shown
    assert removed
    assert overlays.index(shown[0]) < overlays.index(removed[0])
    assert "\\t(" not in str(shown[0]["data"])
    assert ass_bgr_from_hex("#000000") in str(shown[0]["data"])
    assert waiter.durations == [
        settings.tuner_burst_milliseconds / MILLISECONDS_PER_SECOND
    ]
    assert fade_payloads != sender.payloads[len(fade_payloads) :]


def test_mpv_slate_covers_the_screen_with_named_color() -> None:
    player, sender, _waiter = _mpv_player()

    player.show_slate()

    tokens = [
        _command_tokens(payload)
        for payload in sender.payloads
        if isinstance(payload["command"], list)
    ]
    assert ["stop"] in tokens
    overlays = _overlay_commands(sender.payloads)
    shown = [overlay for overlay in overlays if overlay.get("format") == "ass-events"]
    assert shown
    overlay = shown[-1]
    assert overlay["id"] == SLATE_OVERLAY_ID
    assert overlay["name"] == "osd-overlay"
    assert ass_bgr_from_hex(CALM_SLATE_COLOR) in str(overlay["data"])


def test_mpv_osd_overlay_uses_named_command_object() -> None:
    player, sender, _waiter = _mpv_player()

    player.show_slate()

    overlays = _overlay_commands(sender.payloads)
    assert overlays
    for payload in sender.payloads:
        command = payload["command"]
        if isinstance(command, list):
            assert command[0] != "osd-overlay"


def test_mpv_spawn_arguments_disable_watch_later_and_disk_cache() -> None:
    socket_path = "/run/tv90/mpv.sock"
    arguments = mpv_spawn_arguments(socket_path, load_settings({}))

    assert arguments[0] == "mpv"
    assert "--no-config" in arguments
    assert "--no-resume-playback" in arguments
    assert "--watch-later-directory=/dev/null" in arguments
    assert "--cache-pause=no" in arguments
    assert "--cache-on-disk=no" in arguments
    assert f"--input-ipc-server={socket_path}" in arguments
    assert "--vo=drm" in arguments


def test_mpv_observes_eof_reached_on_construction() -> None:
    sender = RecordingSender()
    MpvIpcPlayer(load_settings({}), sender, wait=RecordingWait())

    assert ["observe_property", 1, "eof-reached"] in [
        _command_tokens(payload) for payload in sender.payloads
    ]


def test_mpv_playback_has_ended_from_eof_event_does_not_clear() -> None:
    reader = ScriptedEventReader(
        [{"event": "property-change", "name": "eof-reached", "data": True}]
    )
    player, _sender, _waiter = _mpv_player(reader=reader)

    assert player.playback_has_ended() is True
    assert player.playback_has_ended() is True


def test_mpv_playback_has_ended_from_end_file_eof() -> None:
    reader = ScriptedEventReader([{"event": "end-file", "reason": "eof"}])
    player, _sender, _waiter = _mpv_player(reader=reader)

    assert player.playback_has_ended() is True


def test_mpv_load_discards_stale_end_events() -> None:
    reader = ScriptedEventReader(
        [{"event": "property-change", "name": "eof-reached", "data": True}]
    )
    player, _sender, _waiter = _mpv_player(reader=reader)

    player.load(LITTLE_BEAR_FILENAME, 0.0)

    assert player.playback_has_ended() is False


def test_mpv_stop_sends_stop() -> None:
    player, sender, _waiter = _mpv_player()

    player.stop()

    assert _commands_named(sender.payloads, "stop") == [["stop"]]


def test_mpv_payloads_are_json_serializable() -> None:
    player, sender, _waiter = _mpv_player()
    _exercise_player(player)

    for payload in sender.payloads:
        encoded = json.dumps(payload)
        assert isinstance(encoded, str)


def test_fake_and_mpv_satisfy_player_contract() -> None:
    settings = load_settings({})
    fake = FakePlayer(settings)
    sender = RecordingSender()
    mpv = MpvIpcPlayer(settings, sender, wait=RecordingWait())

    for player in (fake, mpv):
        _exercise_player(player)

    assert any(isinstance(command, LoadCommand) for command in fake.commands)
    assert any(isinstance(command, FadeJoinCommand) for command in fake.commands)
    assert any(isinstance(command, TunerChangeCommand) for command in fake.commands)
    assert _commands_named(sender.payloads, "loadfile")
    assert _commands_named(sender.payloads, "show-text")
    assert _commands_named(sender.payloads, "stop")
    assert isinstance(fake.playback_has_ended(), bool)
    assert isinstance(mpv.playback_has_ended(), bool)


def test_mpv_adapter_does_not_write_library_files(tmp_path: Path) -> None:
    library = tmp_path / "library"
    library.mkdir()
    episode = library / LITTLE_BEAR_FILENAME
    episode.write_bytes(LIBRARY_EPISODE_BYTES)
    before = _library_snapshot(library)
    player, _sender, _waiter = _mpv_player()

    player.load(str(episode), 3.0)
    player.fade_to_next(str(episode), 0.0)
    player.tune_to(str(episode), 1.0)
    player.show_slate()
    player.show_channel_banner(1)
    player.show_volume_bar(0.4)
    player.set_volume(0.3)
    player.stop()

    assert _library_snapshot(library) == before
    assert list(library.iterdir()) == [episode]


def test_encode_mpv_ipc_payload_is_one_json_line() -> None:
    encoded = encode_mpv_ipc_payload({"command": ["get_property", "volume"]})

    assert encoded.endswith(b"\n")
    assert json.loads(encoded.decode("utf-8")) == {
        "command": ["get_property", "volume"]
    }


def test_decode_mpv_ipc_response_rejects_non_object() -> None:
    with pytest.raises(MpvIpcError):
        decode_mpv_ipc_response("[1]")


def test_ass_bgr_from_hex_swaps_to_mpv_order() -> None:
    assert ass_bgr_from_hex("#3A4A42") == "&H424A3A&"


class ScriptedByteTransport:
    def __init__(
        self,
        recv_chunks: list[bytes],
        try_recv_chunks: list[bytes] | None = None,
    ) -> None:
        self.sent: list[bytes] = []
        self._recv_chunks = list(recv_chunks)
        self._try_recv_chunks = list(try_recv_chunks or [])
        self.recv_calls = 0
        self.try_recv_calls = 0

    def sendall(self, data: bytes) -> None:
        self.sent.append(data)

    def recv(self, max_bytes: int) -> bytes:
        self.recv_calls += 1
        if not self._recv_chunks:
            return b""
        return self._recv_chunks.pop(0)[:max_bytes]

    def try_recv(self, max_bytes: int) -> bytes:
        self.try_recv_calls += 1
        if not self._try_recv_chunks:
            return b""
        return self._try_recv_chunks.pop(0)[:max_bytes]


def test_mpv_session_keeps_bytes_after_first_newline() -> None:
    transport = ScriptedByteTransport(
        recv_chunks=[
            b'{"error":"success"}\n{"event":"end-file","reason":"eof"}\n',
        ]
    )
    session = MpvIpcSession(transport)

    reply = session.send({"command": ["observe_property", 1, "eof-reached"]})

    assert reply == {"error": "success"}
    assert session.read_event() == {"event": "end-file", "reason": "eof"}
    assert transport.recv_calls == 1
    assert transport.try_recv_calls == 0


def test_mpv_session_reuses_transport_for_later_commands() -> None:
    transport = ScriptedByteTransport(
        recv_chunks=[
            b'{"error":"success"}\n',
            b'{"error":"success"}\n',
        ]
    )
    session = MpvIpcSession(transport)

    session.send({"command": ["stop"]})
    session.send({"command": ["stop"]})

    assert len(transport.sent) == 2
    assert transport.recv_calls == 2


def test_connect_mpv_unix_socket_opens_transport_once() -> None:
    transport = ScriptedByteTransport(
        recv_chunks=[
            b'{"error":"success"}\n',
            b'{"error":"success"}\n',
        ]
    )
    opened: list[str] = []

    def open_transport(socket_path: str) -> ScriptedByteTransport:
        opened.append(socket_path)
        return transport

    session = connect_mpv_unix_socket("/run/tv90/mpv.sock", open_transport)
    session.send({"command": ["stop"]})
    session.send({"command": ["stop"]})

    assert opened == ["/run/tv90/mpv.sock"]
    assert len(transport.sent) == 2


def test_mpv_session_queues_events_arriving_before_a_reply() -> None:
    transport = ScriptedByteTransport(
        recv_chunks=[
            b'{"event":"property-change","name":"eof-reached","data":true}\n'
            b'{"error":"success"}\n',
        ]
    )
    session = MpvIpcSession(transport)

    reply = session.send({"command": ["loadfile", LITTLE_BEAR_FILENAME, "replace"]})

    assert reply == {"error": "success"}
    assert session.read_event() == {
        "event": "property-change",
        "name": "eof-reached",
        "data": True,
    }


def test_mpv_session_read_event_uses_nonblocking_recv() -> None:
    transport = ScriptedByteTransport(
        recv_chunks=[b'{"error":"success"}\n'],
        try_recv_chunks=[b'{"event":"end-file","reason":"eof"}\n'],
    )
    session = MpvIpcSession(transport)
    session.send({"command": ["stop"]})

    assert session.read_event() == {"event": "end-file", "reason": "eof"}
    assert transport.try_recv_calls == 1


def test_mpv_session_raises_when_socket_closes() -> None:
    session = MpvIpcSession(ScriptedByteTransport(recv_chunks=[]))

    with pytest.raises(MpvIpcError):
        session.send({"command": ["stop"]})
