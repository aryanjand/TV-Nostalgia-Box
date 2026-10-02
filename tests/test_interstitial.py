from datetime import date
from pathlib import Path

from tv90.adapters.fake_interstitial_catalog import FakeInterstitialCatalog
from tv90.adapters.filesystem_interstitial_catalog import (
    FilesystemInterstitialCatalog,
    channel_folder_name,
)
from tv90.domain.interstitial import interstitial_pick_seed, pick_interstitial
from tv90.ports import InterstitialCatalog


def test_pick_interstitial_returns_none_when_empty() -> None:
    assert pick_interstitial((), seed=1, recently_played=()) is None


def test_pick_interstitial_is_seeded() -> None:
    candidates = ("a.mp4", "b.mp4", "c.mp4")

    first = pick_interstitial(candidates, seed=42, recently_played=())
    second = pick_interstitial(candidates, seed=42, recently_played=())

    assert first == second
    assert first in candidates


def test_pick_interstitial_skips_last_played_when_another_exists() -> None:
    candidates = ("a.mp4", "b.mp4")

    picked = pick_interstitial(candidates, seed=7, recently_played=("a.mp4",))

    assert picked == "b.mp4"


def test_pick_interstitial_keeps_only_candidate_even_if_recent() -> None:
    assert pick_interstitial(("solo.mp4",), seed=1, recently_played=("solo.mp4",)) == (
        "solo.mp4"
    )


def test_interstitial_pick_seed_changes_with_clock_hour() -> None:
    on_date = date(2024, 7, 15)

    morning = interstitial_pick_seed(on_date, 1, 7.0)
    later = interstitial_pick_seed(on_date, 1, 9.0)

    assert morning != later
    assert morning == interstitial_pick_seed(on_date, 1, 7.0)


def test_fake_catalog_returns_injected_names() -> None:
    catalog = FakeInterstitialCatalog({1: ("a.mp4", "b.mp4")})

    assert catalog.filenames_for(1) == ("a.mp4", "b.mp4")
    assert catalog.filenames_for(2) == ()


def test_fake_catalog_empty_default() -> None:
    catalog = FakeInterstitialCatalog()

    assert catalog.filenames_for(1) == ()


def test_filesystem_catalog_lists_channel_folder_without_recursion(
    tmp_path: Path,
) -> None:
    ch01 = tmp_path / "ch01"
    nested = ch01 / "nested"
    nested.mkdir(parents=True)
    (ch01 / "break_a.mp4").write_bytes(b"a")
    (ch01 / "break_b.mkv").write_bytes(b"b")
    (ch01 / ".hidden.mp4").write_bytes(b"h")
    (ch01 / "notes.txt").write_bytes(b"n")
    (nested / "ignored.mp4").write_bytes(b"i")
    (tmp_path / "ch02" / "other.avi").parent.mkdir()
    (tmp_path / "ch02" / "other.avi").write_bytes(b"o")
    (tmp_path / "ch03" / "harry_ident.mp4").parent.mkdir()
    (tmp_path / "ch03" / "harry_ident.mp4").write_bytes(b"h")

    catalog = FilesystemInterstitialCatalog(tmp_path)

    assert catalog.filenames_for(1) == ("ch01/break_a.mp4", "ch01/break_b.mkv")
    assert catalog.filenames_for(2) == ("ch02/other.avi",)
    assert catalog.filenames_for(3) == ("ch03/harry_ident.mp4",)


def test_filesystem_catalog_unknown_or_missing_is_empty(tmp_path: Path) -> None:
    catalog = FilesystemInterstitialCatalog(tmp_path / "missing")

    assert catalog.filenames_for(1) == ()
    assert catalog.filenames_for(99) == ()


def test_filesystem_catalog_skips_uppercase_extensions_only_if_media(
    tmp_path: Path,
) -> None:
    ch03 = tmp_path / "ch03"
    ch03.mkdir()
    (ch03 / "break.MP4").write_bytes(b"a")
    (ch03 / "break.AVI").write_bytes(b"b")

    catalog = FilesystemInterstitialCatalog(tmp_path)

    assert catalog.filenames_for(3) == ("ch03/break.AVI", "ch03/break.MP4")


def test_channel_folder_name_is_two_digits() -> None:
    assert channel_folder_name(1) == "ch01"
    assert channel_folder_name(4) == "ch04"


def test_catalogs_satisfy_interstitial_catalog_protocol(tmp_path: Path) -> None:
    (tmp_path / "ch01").mkdir()
    catalogs: list[InterstitialCatalog] = [
        FakeInterstitialCatalog(),
        FilesystemInterstitialCatalog(tmp_path),
    ]

    for catalog in catalogs:
        names = catalog.filenames_for(1)
        assert isinstance(names, tuple)
