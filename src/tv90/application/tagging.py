"""Plan and apply filename tags from episode metadata. Maintenance only."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from importlib import resources
from pathlib import Path

from tv90.application.paired_broadcast import (
    catalog_short_numbers,
    fallback_broadcast_title,
    join_short_metadata,
    uses_paired_shorts,
)
from tv90.config import HOLIDAY_SHOW_STEM
from tv90.domain.episode import (
    DAYPART_TAG_MORNING,
    DAYPART_TAG_NIGHT,
    HOLIDAY_TAG_CHRISTMAS,
    HOLIDAY_TAG_EASTER,
    HOLIDAY_TAG_HALLOWEEN,
    HOLIDAY_TAG_THANKSGIVING,
    SEASON_TAG_AUTUMN,
    SEASON_TAG_SPRING,
    SEASON_TAG_SUMMER,
    SEASON_TAG_WINTER,
    Daypart,
    Episode,
    HolidayTag,
    SeasonTag,
)
from tv90.domain.keyword_tags import (
    KeywordMatch,
    KeywordTagRule,
    match_keywords,
    parse_keyword_rules,
    propose_tagged_episode,
)
from tv90.ports.metadata import (
    EpisodeMetadataNotFoundError,
    EpisodeMetadataSource,
)

KEYWORD_RULES_PACKAGE = "tv90.data"
KEYWORD_RULES_FILENAME = "keyword_rules.toml"
TEXT_ENCODING = "utf-8"
HOLIDAY_SLUG_SPACE = " "
COLUMN_SEPARATOR = "  "
UNTAGGED_LABEL = "(untagged)"
EMPTY_KEYWORDS_LABEL = "-"
NOT_FOUND_SECTION_HEADER = "Not found:"
SKIPPED_SECTION_HEADER = "Skipped (destination exists):"
TABLE_HEADERS = ("FILE", "TITLE", "PROPOSED TAGS", "KEYWORDS")
TRIGGER_TAG_SEPARATOR = "; "
TRIGGER_KEYWORD_SEPARATOR = ", "
TRIGGER_TAG_KEYWORD_SEPARATOR = ": "


@dataclass(frozen=True)
class TagPreviewRow:
    filename: str
    title: str
    proposed_filename: str
    proposed_tags: tuple[str, ...]
    triggers: tuple[KeywordMatch, ...]


@dataclass(frozen=True)
class TagPreview:
    rows: tuple[TagPreviewRow, ...]
    not_found_filenames: tuple[str, ...]
    skipped_filenames: tuple[str, ...]


def packaged_keyword_rules() -> tuple[KeywordTagRule, ...]:
    rules_file = resources.files(KEYWORD_RULES_PACKAGE).joinpath(KEYWORD_RULES_FILENAME)
    return parse_keyword_rules(rules_file.read_text(encoding=TEXT_ENCODING))


def preview_tags(
    episodes: Sequence[Episode],
    metadata_source: EpisodeMetadataSource,
    rules: Sequence[KeywordTagRule],
) -> TagPreview:
    return _plan_tags(episodes, metadata_source, rules)


def apply_tags(
    library_directory: Path,
    episodes: Sequence[Episode],
    metadata_source: EpisodeMetadataSource,
    rules: Sequence[KeywordTagRule],
) -> TagPreview:
    preview = _plan_tags(episodes, metadata_source, rules)
    skipped: list[str] = []
    for row in preview.rows:
        if row.filename == row.proposed_filename:
            continue
        source_path = library_directory / row.filename
        destination_path = library_directory / row.proposed_filename
        if destination_path.exists():
            skipped.append(row.filename)
            continue
        source_path.rename(destination_path)
    return TagPreview(
        rows=preview.rows,
        not_found_filenames=preview.not_found_filenames,
        skipped_filenames=tuple(skipped),
    )


def format_tag_preview(preview: TagPreview) -> str:
    table_rows = [
        (
            row.filename,
            row.title,
            _format_proposed_tags(row.proposed_tags),
            _format_triggers(row.triggers),
        )
        for row in preview.rows
    ]
    widths = _column_widths(table_rows)
    lines = [_format_table_line(TABLE_HEADERS, widths)]
    lines.extend(_format_table_line(row, widths) for row in table_rows)
    if preview.not_found_filenames:
        lines.append("")
        lines.append(NOT_FOUND_SECTION_HEADER)
        lines.extend(preview.not_found_filenames)
    if preview.skipped_filenames:
        lines.append("")
        lines.append(SKIPPED_SECTION_HEADER)
        lines.extend(preview.skipped_filenames)
    return "\n".join(lines) + "\n"


def proposed_tag_tokens(episode: Episode) -> tuple[str, ...]:
    tokens: list[str] = []
    if episode.daypart is Daypart.MORNING:
        tokens.append(DAYPART_TAG_MORNING)
    elif episode.daypart is Daypart.NIGHT:
        tokens.append(DAYPART_TAG_NIGHT)
    if episode.season_tag is SeasonTag.SPRING:
        tokens.append(SEASON_TAG_SPRING)
    elif episode.season_tag is SeasonTag.SUMMER:
        tokens.append(SEASON_TAG_SUMMER)
    elif episode.season_tag is SeasonTag.AUTUMN:
        tokens.append(SEASON_TAG_AUTUMN)
    elif episode.season_tag is SeasonTag.WINTER:
        tokens.append(SEASON_TAG_WINTER)
    if episode.holiday_tag is HolidayTag.HALLOWEEN:
        tokens.append(HOLIDAY_TAG_HALLOWEEN)
    elif episode.holiday_tag is HolidayTag.THANKSGIVING:
        tokens.append(HOLIDAY_TAG_THANKSGIVING)
    elif episode.holiday_tag is HolidayTag.CHRISTMAS:
        tokens.append(HOLIDAY_TAG_CHRISTMAS)
    elif episode.holiday_tag is HolidayTag.EASTER:
        tokens.append(HOLIDAY_TAG_EASTER)
    return tuple(tokens)


def _plan_tags(
    episodes: Sequence[Episode],
    metadata_source: EpisodeMetadataSource,
    rules: Sequence[KeywordTagRule],
) -> TagPreview:
    rows: list[TagPreviewRow] = []
    not_found: list[str] = []
    for episode in episodes:
        title, description = _title_and_description(episode, metadata_source, not_found)
        if title is None:
            continue
        matches = match_keywords(title, description, rules)
        proposal = propose_tagged_episode(episode, matches)
        rows.append(
            TagPreviewRow(
                filename=episode.filename,
                title=title,
                proposed_filename=proposal.episode.filename,
                proposed_tags=proposed_tag_tokens(proposal.episode),
                triggers=proposal.applied_matches,
            )
        )
    return TagPreview(
        rows=tuple(rows),
        not_found_filenames=tuple(not_found),
        skipped_filenames=(),
    )


def _title_and_description(
    episode: Episode,
    metadata_source: EpisodeMetadataSource,
    not_found: list[str],
) -> tuple[str | None, str]:
    if episode.show_stem == HOLIDAY_SHOW_STEM:
        # Holiday movies have a title slug, not SxxExx, so there is nothing to look up.
        return episode.holiday_title_slug().replace("_", HOLIDAY_SLUG_SPACE), ""
    season_number, episode_number = episode.cartoon_season_and_episode()
    if uses_paired_shorts(episode.show_stem):
        return _paired_title_and_description(
            episode, season_number, episode_number, metadata_source, not_found
        )
    try:
        metadata = metadata_source.lookup(
            episode.show_stem, season_number, episode_number
        )
    except EpisodeMetadataNotFoundError:
        not_found.append(episode.filename)
        return None, ""
    return metadata.title, metadata.description


def _paired_title_and_description(
    episode: Episode,
    season_number: int,
    episode_number: int,
    metadata_source: EpisodeMetadataSource,
    not_found: list[str],
) -> tuple[str | None, str]:
    parts = []
    for short_number in catalog_short_numbers(episode_number):
        try:
            parts.append(
                metadata_source.lookup(episode.show_stem, season_number, short_number)
            )
        except EpisodeMetadataNotFoundError:
            continue
    if parts:
        joined = join_short_metadata(parts)
        return joined.title, joined.description
    fallback = fallback_broadcast_title(
        episode.show_stem, season_number, episode_number
    )
    if fallback is not None:
        return fallback, ""
    not_found.append(episode.filename)
    return None, ""


def _format_proposed_tags(tags: tuple[str, ...]) -> str:
    if not tags:
        return UNTAGGED_LABEL
    return TRIGGER_KEYWORD_SEPARATOR.join(tags)


def _format_triggers(triggers: Sequence[KeywordMatch]) -> str:
    if not triggers:
        return EMPTY_KEYWORDS_LABEL
    return TRIGGER_TAG_SEPARATOR.join(
        f"{match.tag}{TRIGGER_TAG_KEYWORD_SEPARATOR}"
        f"{TRIGGER_KEYWORD_SEPARATOR.join(match.keywords)}"
        for match in triggers
    )


def _column_widths(
    rows: Sequence[tuple[str, str, str, str]],
) -> tuple[int, int, int, int]:
    widths = [len(header) for header in TABLE_HEADERS]
    for row in rows:
        for index, cell in enumerate(row):
            widths[index] = max(widths[index], len(cell))
    return widths[0], widths[1], widths[2], widths[3]


def _format_table_line(
    cells: tuple[str, ...], widths: tuple[int, int, int, int]
) -> str:
    padded = tuple(cell.ljust(widths[index]) for index, cell in enumerate(cells))
    return COLUMN_SEPARATOR.join(padded)
