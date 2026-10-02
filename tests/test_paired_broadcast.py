from tv90.application.paired_broadcast import (
    HARRY_SEASON_TWO_BROADCAST_TITLES,
    catalog_short_numbers,
    fallback_broadcast_title,
    join_short_metadata,
    uses_paired_shorts,
)
from tv90.config import HARRY_SHOW_STEM, KIPPER_SHOW_STEM, OSWALD_SHOW_STEM
from tv90.ports.metadata import EpisodeMetadata


def test_catalog_short_numbers_map_broadcast_slot_to_two_shorts() -> None:
    assert catalog_short_numbers(1) == (1, 2)
    assert catalog_short_numbers(11) == (21, 22)
    assert catalog_short_numbers(26) == (51, 52)


def test_oswald_and_harry_use_paired_shorts() -> None:
    assert uses_paired_shorts(OSWALD_SHOW_STEM) is True
    assert uses_paired_shorts(HARRY_SHOW_STEM) is True
    assert uses_paired_shorts(KIPPER_SHOW_STEM) is False


def test_join_short_metadata_keeps_both_titles() -> None:
    joined = join_short_metadata(
        (
            EpisodeMetadata("Chasing the Ice-Cream Truck", "a summer treat"),
            EpisodeMetadata("The Camping Trip", ""),
        )
    )

    assert joined.title == "Chasing the Ice-Cream Truck / The Camping Trip"
    assert joined.description == "a summer treat"


def test_harry_season_two_has_every_broadcast_slot() -> None:
    assert tuple(HARRY_SEASON_TWO_BROADCAST_TITLES) == tuple(range(1, 27))
    assert fallback_broadcast_title(HARRY_SHOW_STEM, 2, 10) == (
        "I See a Seashell! / Jump"
    )
    assert fallback_broadcast_title(HARRY_SHOW_STEM, 1, 1) is None
    assert fallback_broadcast_title(OSWALD_SHOW_STEM, 2, 1) is None
