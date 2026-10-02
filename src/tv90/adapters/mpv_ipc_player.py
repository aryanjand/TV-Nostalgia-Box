"""mpv JSON IPC player. Tests inject a sender; this module never starts mpv."""

from __future__ import annotations

import json
import socket
import subprocess
import time
from collections.abc import Callable, Mapping
from typing import Protocol

from tv90.config import CALM_SLATE_COLOR, Settings
from tv90.ports.player import (
    format_channel_banner,
    format_volume_bar,
    require_player_volume,
)

MpvIpcCommandSender = Callable[[Mapping[str, object]], Mapping[str, object]]
MpvIpcEventReader = Callable[[], Mapping[str, object] | None]
DurationWait = Callable[[float], None]

MPV_BINARY = "mpv"
MPV_NO_CONFIG_FLAG = "--no-config"
MPV_NO_RESUME_PLAYBACK_FLAG = "--no-resume-playback"
MPV_WATCH_LATER_DIRECTORY_FLAG = "--watch-later-directory=/dev/null"
MPV_CACHE_PAUSE_FLAG = "--cache-pause=no"
MPV_CACHE_ON_DISK_FLAG = "--cache-on-disk=no"
MPV_IDLE_FLAG = "--idle=yes"
MPV_VO_DRM_FLAG = "--vo=drm"
MPV_HWDEC_FLAG = "--hwdec=v4l2m2m-copy"
MPV_FRAMEDROP_FLAG = "--framedrop=vo"
MPV_MSG_LEVEL_FLAG = "--msg-level=all=error"
MPV_FORCE_WINDOW_FLAG = "--force-window=yes"
MPV_FULLSCREEN_FLAG = "--fullscreen"
MPV_OSC_OFF_FLAG = "--osc=no"
MPV_KEEP_OPEN_OFF_FLAG = "--keep-open=no"
MPV_INPUT_IPC_SERVER_PREFIX = "--input-ipc-server="
MPV_OSD_COLOR_PREFIX = "--osd-color="
MPV_OSD_FONT_PREFIX = "--osd-font="

OSD_FONT_NAME = "monospace"
MPV_PERCENT_VOLUME_SCALE = 100.0
MILLISECONDS_PER_SECOND = 1000
EOF_OBSERVE_REQUEST_ID = 1
EOF_REACHED_PROPERTY = "eof-reached"
PROPERTY_CHANGE_EVENT = "property-change"
END_FILE_EVENT = "end-file"
EOF_REASON = "eof"

LOADFILE_COMMAND = "loadfile"
LOADFILE_REPLACE_FLAG = "replace"
# mpv 0.38+ takes insert-at index before options. A map in that slot
# errors with "argument index has incompatible type" and never plays.
LOADFILE_REPLACE_INDEX = -1
LOADFILE_OPTIONS_SEPARATOR = ","
LOADFILE_OPTION_ASSIGN = "="
LOADFILE_START_OPTION = "start"
LOADFILE_VF_OPTION = "vf"
LOADFILE_AF_OPTION = "af"
SET_PROPERTY_COMMAND = "set_property"
SHOW_TEXT_COMMAND = "show-text"
STOP_COMMAND = "stop"
OSD_OVERLAY_COMMAND = "osd-overlay"
OBSERVE_PROPERTY_COMMAND = "observe_property"
VOLUME_PROPERTY = "volume"
OSD_COLOR_PROPERTY = "osd-color"
OSD_FONT_PROPERTY = "osd-font"
OSD_ALIGN_X_PROPERTY = "osd-align-x"
OSD_ALIGN_Y_PROPERTY = "osd-align-y"
OSD_FONT_SIZE_PROPERTY = "osd-font-size"
OSD_BOLD_PROPERTY = "osd-bold"
OSD_MARGIN_X_PROPERTY = "osd-margin-x"
OSD_MARGIN_Y_PROPERTY = "osd-margin-y"
CHANNEL_OSD_ALIGN_X = "right"
CHANNEL_OSD_ALIGN_Y = "top"
CHANNEL_OSD_FONT_SIZE = 80
VOLUME_OSD_ALIGN_X = "left"
VOLUME_OSD_ALIGN_Y = "bottom"
VOLUME_OSD_FONT_SIZE = 40
OSD_MARGIN_PIXELS = 40
OSD_BOLD_ON = "yes"

SLATE_OVERLAY_ID = 1
TUNER_OVERLAY_ID = 2
OVERLAY_FORMAT_ASS = "ass-events"
OVERLAY_FORMAT_NONE = "none"
OVERLAY_WIDTH = 3840
OVERLAY_HEIGHT = 2160
BLACK_HEX_COLOR = "#000000"
HEX_COLOR_PREFIX = "#"
ASS_COLOR_PREFIX = "&H"
ASS_COLOR_SUFFIX = "&"
RED_HEX_SLICE = slice(0, 2)
GREEN_HEX_SLICE = slice(2, 4)
BLUE_HEX_SLICE = slice(4, 6)
VIDEO_FADE_IN_TEMPLATE = "fade=t=in:st=0:d={fade_seconds}"
AUDIO_FADE_IN_TEMPLATE = "afade=t=in:st=0:d={fade_seconds}"
IPC_NEWLINE = "\n"
TEXT_ENCODING = "utf-8"
SOCKET_RECV_CHUNK_BYTES = 4096


class MpvIpcError(Exception):
    """The injected or unix-socket IPC transport returned an unusable payload."""


class MpvByteTransport(Protocol):
    def sendall(self, data: bytes) -> None:
        """Write one IPC request. Does not close the connection."""
        ...

    def recv(self, max_bytes: int) -> bytes:
        """Blocking read used while waiting for a command reply."""
        ...

    def try_recv(self, max_bytes: int) -> bytes:
        """Non-blocking read so T12 can poll events without sending a command."""
        ...


class MpvUnixSocketTransport:
    def __init__(self, socket_path: str) -> None:
        self._client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self._client.connect(socket_path)

    def sendall(self, data: bytes) -> None:
        self._client.sendall(data)

    def recv(self, max_bytes: int) -> bytes:
        return self._client.recv(max_bytes)

    def try_recv(self, max_bytes: int) -> bytes:
        self._client.setblocking(False)
        try:
            return self._client.recv(max_bytes)
        except BlockingIOError:
            return b""
        finally:
            self._client.setblocking(True)

    def close(self) -> None:
        self._client.close()


class MpvIpcSession:
    """Long-lived IPC client. One connection; leftover bytes stay in the buffer."""

    def __init__(self, transport: MpvByteTransport) -> None:
        self._transport = transport
        self._buffer = bytearray()
        self._events: list[dict[str, object]] = []

    def send(self, payload: Mapping[str, object]) -> dict[str, object]:
        self._transport.sendall(encode_mpv_ipc_payload(payload))
        while True:
            message = self._read_message()
            if _is_ipc_event(message):
                self._events.append(message)
                continue
            return message

    def read_event(self) -> dict[str, object] | None:
        if self._events:
            return self._events.pop(0)
        if not self._has_complete_line():
            piece = self._transport.try_recv(SOCKET_RECV_CHUNK_BYTES)
            if piece:
                self._buffer.extend(piece)
        if not self._has_complete_line():
            return None
        message = self._consume_line_object()
        if _is_ipc_event(message):
            return message
        return None

    def close(self) -> None:
        if isinstance(self._transport, MpvUnixSocketTransport):
            self._transport.close()

    def _read_message(self) -> dict[str, object]:
        while not self._has_complete_line():
            piece = self._transport.recv(SOCKET_RECV_CHUNK_BYTES)
            if piece == b"":
                raise MpvIpcError("mpv IPC socket closed")
            self._buffer.extend(piece)
        return self._consume_line_object()

    def _has_complete_line(self) -> bool:
        return IPC_NEWLINE.encode(TEXT_ENCODING) in self._buffer

    def _consume_line_object(self) -> dict[str, object]:
        newline = IPC_NEWLINE.encode(TEXT_ENCODING)
        line, remainder = bytes(self._buffer).split(newline, 1)
        self._buffer[:] = remainder
        return decode_mpv_ipc_response(line.decode(TEXT_ENCODING))


class MpvIpcPlayer:
    def __init__(
        self,
        settings: Settings,
        send_command: MpvIpcCommandSender,
        read_event: MpvIpcEventReader | None = None,
        *,
        wait: DurationWait = time.sleep,
    ) -> None:
        self._settings = settings
        self._send_command = send_command
        self._read_event = read_event
        # Production waits the tuner burst; tests inject a recorder that does not sleep.
        self._wait = wait
        self._playback_ended = False
        self._send(
            [
                OBSERVE_PROPERTY_COMMAND,
                EOF_OBSERVE_REQUEST_ID,
                EOF_REACHED_PROPERTY,
            ]
        )

    def load(self, filename: str, offset_seconds: float) -> None:
        self._begin_playback()
        self._clear_overlays()
        self._send_loadfile(filename, offset_seconds, {})

    def fade_to_next(self, filename: str, offset_seconds: float) -> None:
        # Fade-in on the incoming file so T12 is not blocked waiting for fade-out.
        self._begin_playback()
        self._clear_overlays()
        fade_seconds = self._settings.episode_join_fade_seconds
        self._send_loadfile(
            filename,
            offset_seconds,
            {
                LOADFILE_VF_OPTION: VIDEO_FADE_IN_TEMPLATE.format(
                    fade_seconds=fade_seconds
                ),
                LOADFILE_AF_OPTION: AUDIO_FADE_IN_TEMPLATE.format(
                    fade_seconds=fade_seconds
                ),
            },
        )

    def tune_to(self, filename: str, offset_seconds: float) -> None:
        self._begin_playback()
        self._clear_overlay(SLATE_OVERLAY_ID)
        self._send_overlay(TUNER_OVERLAY_ID, _black_ass())
        self._wait(self._settings.tuner_burst_milliseconds / MILLISECONDS_PER_SECOND)
        self._clear_overlay(TUNER_OVERLAY_ID)
        self._send_loadfile(filename, offset_seconds, {})

    def show_slate(self) -> None:
        self._begin_playback()
        self._send([STOP_COMMAND])
        self._clear_overlay(TUNER_OVERLAY_ID)
        self._send_overlay(SLATE_OVERLAY_ID, _slate_ass(CALM_SLATE_COLOR))

    def show_channel_banner(self, channel_number: int) -> None:
        # osd-duration is on the show-text command; this method must not sleep.
        self._prepare_osd(
            CHANNEL_OSD_ALIGN_X, CHANNEL_OSD_ALIGN_Y, CHANNEL_OSD_FONT_SIZE
        )
        self._send(
            [
                SHOW_TEXT_COMMAND,
                format_channel_banner(channel_number),
                _osd_duration_milliseconds(self._settings.osd_banner_seconds),
            ]
        )

    def show_volume_bar(self, volume: float) -> None:
        require_player_volume(volume)
        self._prepare_osd(VOLUME_OSD_ALIGN_X, VOLUME_OSD_ALIGN_Y, VOLUME_OSD_FONT_SIZE)
        self._send(
            [
                SHOW_TEXT_COMMAND,
                format_volume_bar(volume),
                _osd_duration_milliseconds(self._settings.osd_banner_seconds),
            ]
        )

    def set_volume(self, volume: float) -> None:
        require_player_volume(volume)
        self._send(
            [
                SET_PROPERTY_COMMAND,
                VOLUME_PROPERTY,
                volume * MPV_PERCENT_VOLUME_SCALE,
            ]
        )

    def stop(self) -> None:
        self._begin_playback()
        self._send([STOP_COMMAND])
        self._clear_overlays()

    def playback_has_ended(self) -> bool:
        self._collect_end_events()
        return self._playback_ended

    def _begin_playback(self) -> None:
        self._collect_end_events()
        self._playback_ended = False

    def _collect_end_events(self) -> None:
        if self._read_event is None:
            return
        while True:
            event = self._read_event()
            if event is None:
                return
            if _event_reports_playback_ended(event):
                self._playback_ended = True

    def _prepare_osd(self, align_x: str, align_y: str, font_size: int) -> None:
        self._send([SET_PROPERTY_COMMAND, OSD_COLOR_PROPERTY, self._settings.osd_color])
        self._send([SET_PROPERTY_COMMAND, OSD_FONT_PROPERTY, OSD_FONT_NAME])
        self._send([SET_PROPERTY_COMMAND, OSD_BOLD_PROPERTY, OSD_BOLD_ON])
        self._send([SET_PROPERTY_COMMAND, OSD_ALIGN_X_PROPERTY, align_x])
        self._send([SET_PROPERTY_COMMAND, OSD_ALIGN_Y_PROPERTY, align_y])
        self._send([SET_PROPERTY_COMMAND, OSD_FONT_SIZE_PROPERTY, font_size])
        self._send([SET_PROPERTY_COMMAND, OSD_MARGIN_X_PROPERTY, OSD_MARGIN_PIXELS])
        self._send([SET_PROPERTY_COMMAND, OSD_MARGIN_Y_PROPERTY, OSD_MARGIN_PIXELS])

    def _send_loadfile(
        self,
        filename: str,
        offset_seconds: float,
        extra_options: Mapping[str, object],
    ) -> None:
        options: dict[str, object] = {
            LOADFILE_START_OPTION: offset_seconds,
            **extra_options,
        }
        # Bookworm mpv wants options as start=1.5,vf=... not a JSON object.
        self._send(
            [
                LOADFILE_COMMAND,
                filename,
                LOADFILE_REPLACE_FLAG,
                LOADFILE_REPLACE_INDEX,
                _loadfile_options_argument(options),
            ]
        )

    def _clear_overlays(self) -> None:
        self._clear_overlay(SLATE_OVERLAY_ID)
        self._clear_overlay(TUNER_OVERLAY_ID)

    def _clear_overlay(self, overlay_id: int) -> None:
        # Named object: array form treats the first osd-overlay argument as integer id.
        self._send(
            {
                "name": OSD_OVERLAY_COMMAND,
                "id": overlay_id,
                "format": OVERLAY_FORMAT_NONE,
                "data": "",
            }
        )

    def _send_overlay(self, overlay_id: int, data: str) -> None:
        self._send(
            {
                "name": OSD_OVERLAY_COMMAND,
                "id": overlay_id,
                "format": OVERLAY_FORMAT_ASS,
                "data": data,
            }
        )

    def _send(self, command: list[object] | dict[str, object]) -> Mapping[str, object]:
        return self._send_command({"command": command})


def _loadfile_options_argument(options: Mapping[str, object]) -> str:
    return LOADFILE_OPTIONS_SEPARATOR.join(
        f"{key}{LOADFILE_OPTION_ASSIGN}{value}" for key, value in options.items()
    )


def ass_bgr_from_hex(hex_color: str) -> str:
    rgb = hex_color.removeprefix(HEX_COLOR_PREFIX)
    return (
        f"{ASS_COLOR_PREFIX}{rgb[BLUE_HEX_SLICE]}{rgb[GREEN_HEX_SLICE]}"
        f"{rgb[RED_HEX_SLICE]}{ASS_COLOR_SUFFIX}"
    )


def mpv_spawn_arguments(socket_path: str, settings: Settings) -> tuple[str, ...]:
    return (
        MPV_BINARY,
        MPV_NO_CONFIG_FLAG,
        MPV_NO_RESUME_PLAYBACK_FLAG,
        MPV_WATCH_LATER_DIRECTORY_FLAG,
        MPV_CACHE_PAUSE_FLAG,
        MPV_CACHE_ON_DISK_FLAG,
        f"{MPV_INPUT_IPC_SERVER_PREFIX}{socket_path}",
        MPV_IDLE_FLAG,
        MPV_VO_DRM_FLAG,
        MPV_HWDEC_FLAG,
        MPV_FRAMEDROP_FLAG,
        MPV_MSG_LEVEL_FLAG,
        MPV_FORCE_WINDOW_FLAG,
        MPV_FULLSCREEN_FLAG,
        MPV_OSC_OFF_FLAG,
        MPV_KEEP_OPEN_OFF_FLAG,
        f"{MPV_OSD_COLOR_PREFIX}{settings.osd_color}",
        f"{MPV_OSD_FONT_PREFIX}{OSD_FONT_NAME}",
    )


def spawn_mpv_process(socket_path: str, settings: Settings) -> subprocess.Popen[bytes]:
    """T15 starts mpv. Tests never call this; development has no mpv binary."""
    # Inherit stdio so --vo=drm can use the service TTY (HDMI). DEVNULL
    # made IPC work while the set stayed black.
    return subprocess.Popen(mpv_spawn_arguments(socket_path, settings))


def connect_mpv_unix_socket(
    socket_path: str,
    open_transport: Callable[[str], MpvByteTransport] = MpvUnixSocketTransport,
) -> MpvIpcSession:
    """T15 opens one persistent client. Tests inject a transport factory."""
    return MpvIpcSession(open_transport(socket_path))


def encode_mpv_ipc_payload(payload: Mapping[str, object]) -> bytes:
    return (json.dumps(dict(payload)) + IPC_NEWLINE).encode(TEXT_ENCODING)


def decode_mpv_ipc_response(raw_line: str) -> dict[str, object]:
    try:
        loaded: object = json.loads(raw_line)
    except json.JSONDecodeError as error:
        raise MpvIpcError("mpv IPC response is not JSON") from error
    if not isinstance(loaded, dict):
        raise MpvIpcError("mpv IPC response is not a JSON object")
    return loaded


def _osd_duration_milliseconds(seconds: float) -> int:
    return int(seconds * MILLISECONDS_PER_SECOND)


def _is_ipc_event(message: Mapping[str, object]) -> bool:
    return "event" in message


def _event_reports_playback_ended(event: Mapping[str, object]) -> bool:
    name = event.get("event")
    if name == PROPERTY_CHANGE_EVENT:
        return event.get("name") == EOF_REACHED_PROPERTY and event.get("data") is True
    if name == END_FILE_EVENT:
        return event.get("reason") == EOF_REASON
    return False


def _slate_ass(hex_color: str) -> str:
    return _ass_rectangle(ass_bgr_from_hex(hex_color))


def _black_ass() -> str:
    return _ass_rectangle(ass_bgr_from_hex(BLACK_HEX_COLOR))


def _ass_rectangle(ass_color: str) -> str:
    # an7 pins the drawing to the top-left so a 4K rectangle covers 1080p and 4K.
    # Hold this field; do not use ASS \t — osd-overlay ignores event timing.
    return (
        f"{{\\an7\\p1\\bord0\\shad0\\1c{ass_color}\\1a&H00&}}"
        f"m 0 0 l {OVERLAY_WIDTH} 0 {OVERLAY_WIDTH} {OVERLAY_HEIGHT} "
        f"0 {OVERLAY_HEIGHT}"
    )
