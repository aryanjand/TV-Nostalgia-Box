from pathlib import Path

from tv90.adapters.fake_metadata import FakeEpisodeMetadataSource
from tv90.application.tagging import (
    TagPreview,
    TagPreviewRow,
    apply_tags,
    format_tag_preview,
    packaged_keyword_rules,
    preview_tags,
    proposed_tag_tokens,
)
from tv90.domain.filename import parse_filename
from tv90.ports.metadata import EpisodeMetadata, EpisodeMetadataSource

RULES = packaged_keyword_rules()


class ForbiddenMetadataSource:
    def lookup(
        self, show_stem: str, season_number: int, episode_number: int
    ) -> EpisodeMetadata:
        raise AssertionError(
            f"must not look up {show_stem} S{season_number:02d}E{episode_number:02d}"
        )


def test_dry_run_renames_nothing(tmp_path: Path) -> None:
    path = tmp_path / "LittleBear_S01E01.mp4"
    path.write_bytes(b"video")
    episode = parse_filename(path.name)
    source = FakeEpisodeMetadataSource(
        {("LittleBear", 1, 1): EpisodeMetadata("Snow Day", "ice on the sled")}
    )

    preview = preview_tags((episode,), source, RULES)

    assert path.exists()
    assert path.read_bytes() == b"video"
    assert preview.rows[0].proposed_filename == "LittleBear_S01E01_WINTER.mp4"
    assert preview.rows[0].proposed_tags == ("WINTER",)
    assert "WINTER: snow" not in preview.rows[0].filename
    assert preview.not_found_filenames == ()


def test_apply_renames_to_canonical_tagged_filename(tmp_path: Path) -> None:
    path = tmp_path / "LittleBear_S01E01.mp4"
    path.write_bytes(b"video")
    episode = parse_filename(path.name)
    source = FakeEpisodeMetadataSource(
        {("LittleBear", 1, 1): EpisodeMetadata("Snow Day", "ice on the sled")}
    )

    preview = apply_tags(tmp_path, (episode,), source, RULES)

    assert not path.exists()
    renamed = tmp_path / "LittleBear_S01E01_WINTER.mp4"
    assert renamed.exists()
    assert renamed.read_bytes() == b"video"
    assert preview.rows[0].proposed_filename == renamed.name


def test_existing_tags_are_preserved_when_night_keywords_match(tmp_path: Path) -> None:
    path = tmp_path / "LittleBear_S01E01_MORNING.mp4"
    path.write_bytes(b"")
    episode = parse_filename(path.name)
    source = FakeEpisodeMetadataSource(
        {("LittleBear", 1, 1): EpisodeMetadata("Moon Sleep", "bedtime among the stars")}
    )

    preview = preview_tags((episode,), source, RULES)
    apply_preview = apply_tags(tmp_path, (episode,), source, RULES)

    assert preview.rows[0].proposed_tags == ("MORNING",)
    assert all(match.tag != "NIGHT" for match in preview.rows[0].triggers)
    assert path.exists()
    assert apply_preview.skipped_filenames == ()
    assert (tmp_path / "LittleBear_S01E01_MORNING.mp4").exists()


def test_unmatched_episode_stays_untagged(tmp_path: Path) -> None:
    path = tmp_path / "Oswald_S01E01.mp4"
    path.write_bytes(b"")
    episode = parse_filename(path.name)
    source = FakeEpisodeMetadataSource(
        {("Oswald", 1, 1): EpisodeMetadata("Friends", "a quiet walk in the city")}
    )

    preview = preview_tags((episode,), source, RULES)

    assert preview.rows[0].proposed_tags == ()
    assert preview.rows[0].proposed_filename == path.name
    assert path.exists()
    table = format_tag_preview(preview)
    assert "(untagged)" in table
    assert path.name in table


def test_not_found_is_listed_and_not_renamed(tmp_path: Path) -> None:
    missing = tmp_path / "Harry_S01E01.mp4"
    found = tmp_path / "LittleBear_S01E01.mp4"
    missing.write_bytes(b"harry")
    found.write_bytes(b"bear")
    source = FakeEpisodeMetadataSource(
        {("LittleBear", 1, 1): EpisodeMetadata("Breakfast", "wake at sunrise")}
    )
    episodes = (
        parse_filename(missing.name),
        parse_filename(found.name),
    )

    preview = preview_tags(episodes, source, RULES)
    apply_tags(tmp_path, episodes, source, RULES)
    table = format_tag_preview(preview)

    assert preview.not_found_filenames == ("Harry_S01E01.mp4",)
    assert missing.exists()
    assert missing.read_bytes() == b"harry"
    assert not found.exists()
    assert (tmp_path / "LittleBear_S01E01_MORNING.mp4").exists()
    assert "Not found:" in table
    assert "Harry_S01E01.mp4" in table.split("Not found:")[1]


def test_holiday_movie_skips_metadata_lookup() -> None:
    source: EpisodeMetadataSource = ForbiddenMetadataSource()
    episode = parse_filename("Holiday_Rudolph_CHRISTMAS.mp4")

    preview = preview_tags((episode,), source, RULES)

    assert preview.rows[0].title == "Rudolph"
    assert preview.rows[0].proposed_tags == ("CHRISTMAS",)
    assert preview.not_found_filenames == ()


def test_holiday_slug_can_match_christmas_keywords() -> None:
    episode = parse_filename("Holiday_A_Christmas_Carol.mp4")

    preview = preview_tags((episode,), ForbiddenMetadataSource(), RULES)

    assert preview.rows[0].title == "A Christmas Carol"
    assert (
        preview.rows[0].proposed_filename == "Holiday_A_Christmas_Carol_CHRISTMAS.mp4"
    )


def test_apply_skips_when_destination_already_exists(tmp_path: Path) -> None:
    source_path = tmp_path / "LittleBear_S01E01.mp4"
    destination = tmp_path / "LittleBear_S01E01_WINTER.mp4"
    source_path.write_bytes(b"new")
    destination.write_bytes(b"old")
    episode = parse_filename(source_path.name)
    metadata = FakeEpisodeMetadataSource(
        {("LittleBear", 1, 1): EpisodeMetadata("Snow", "sled")}
    )

    preview = apply_tags(tmp_path, (episode,), metadata, RULES)

    assert source_path.exists()
    assert destination.read_bytes() == b"old"
    assert preview.skipped_filenames == ("LittleBear_S01E01.mp4",)


def test_proposed_tag_tokens_cover_each_kind() -> None:
    night = parse_filename("Oswald_S01E01_NIGHT_SPRING_THANKSGIVING.mp4")
    summer = parse_filename("Oswald_S01E02_SUMMER.mp4")
    autumn = parse_filename("Oswald_S01E03_AUTUMN_EASTER.mp4")

    assert proposed_tag_tokens(night) == ("NIGHT", "SPRING", "THANKSGIVING")
    assert proposed_tag_tokens(summer) == ("SUMMER",)
    assert proposed_tag_tokens(autumn) == ("AUTUMN", "EASTER")
    assert proposed_tag_tokens(parse_filename("Holiday_Rudolph_CHRISTMAS.mp4")) == (
        "CHRISTMAS",
    )
    assert proposed_tag_tokens(parse_filename("Harry_S01E01_HALLOWEEN.mp4")) == (
        "HALLOWEEN",
    )


def test_format_table_lists_skipped_destinations() -> None:
    preview = TagPreview(
        rows=(
            TagPreviewRow(
                filename="LittleBear_S01E01.mp4",
                title="Snow",
                proposed_filename="LittleBear_S01E01_WINTER.mp4",
                proposed_tags=("WINTER",),
                triggers=(),
            ),
        ),
        not_found_filenames=(),
        skipped_filenames=("LittleBear_S01E01.mp4",),
    )

    table = format_tag_preview(preview)

    assert "Skipped (destination exists):" in table
    assert "LittleBear_S01E01.mp4" in table.split("Skipped")[1]


def test_format_table_includes_file_title_tags_and_keywords() -> None:
    episode = parse_filename("LittleBear_S01E01.mp4")
    source = FakeEpisodeMetadataSource(
        {("LittleBear", 1, 1): EpisodeMetadata("Snow Day", "the sled")}
    )

    table = format_tag_preview(preview_tags((episode,), source, RULES))

    assert "FILE" in table
    assert "LittleBear_S01E01.mp4" in table
    assert "Snow Day" in table
    assert "WINTER" in table
    assert "snow" in table or "sled" in table
