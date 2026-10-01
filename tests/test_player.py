import math
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


def test_format_volume_bar_uses_ten_segments() -> None:
    assert format_volume_bar(0.4) == "████░░░░░░"
    assert format_volume_bar(0.0) == "░░░░░░░░░░"
    assert format_volume_bar(1.0) == "██████████"


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

    assert player.commands == (ShowVolumeBarCommand(volume=0.4, bar_text="████░░░░░░"),)
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
