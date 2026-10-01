"""Parse and format README §4 library filenames. No I/O."""

from __future__ import annotations

import re
from dataclasses import dataclass

from tv90.config import HOLIDAY_SHOW_STEM
from tv90.domain.episode import (
    CARTOON_SHOW_STEMS,
    DAYPART_TAG_DAY,
    DAYPART_TAG_MORNING,
    DAYPART_TAG_NIGHT,
    HOLIDAY_TAG_CHRISTMAS,
    HOLIDAY_TAG_EASTER,
    HOLIDAY_TAG_HALLOWEEN,
    HOLIDAY_TAG_THANKSGIVING,
    KNOWN_SHOW_STEMS,
    SEASON_TAG_AUTUMN,
    SEASON_TAG_SPRING,
    SEASON_TAG_SUMMER,
    SEASON_TAG_WINTER,
    Daypart,
    Episode,
    HolidayTag,
    SeasonTag,
)

FILENAME_TOKEN_SEPARATOR = "_"
EXTENSION_SEPARATOR = "."
SEASON_EPISODE_PATTERN = re.compile(r"^S(\d{2})E(\d{2})$")

DAYPART_BY_TOKEN = {
    DAYPART_TAG_MORNING: Daypart.MORNING,
    DAYPART_TAG_NIGHT: Daypart.NIGHT,
    DAYPART_TAG_DAY: Daypart.GENERAL,
}
SEASON_BY_TOKEN = {
    SEASON_TAG_SPRING: SeasonTag.SPRING,
    SEASON_TAG_SUMMER: SeasonTag.SUMMER,
    SEASON_TAG_AUTUMN: SeasonTag.AUTUMN,
    SEASON_TAG_WINTER: SeasonTag.WINTER,
}
HOLIDAY_BY_TOKEN = {
    HOLIDAY_TAG_HALLOWEEN: HolidayTag.HALLOWEEN,
    HOLIDAY_TAG_THANKSGIVING: HolidayTag.THANKSGIVING,
    HOLIDAY_TAG_CHRISTMAS: HolidayTag.CHRISTMAS,
    HOLIDAY_TAG_EASTER: HolidayTag.EASTER,
}
DAYPART_EMIT_TOKEN = {
    Daypart.MORNING: DAYPART_TAG_MORNING,
    Daypart.NIGHT: DAYPART_TAG_NIGHT,
}
SEASON_EMIT_TOKEN = {
    SeasonTag.SPRING: SEASON_TAG_SPRING,
    SeasonTag.SUMMER: SEASON_TAG_SUMMER,
    SeasonTag.AUTUMN: SEASON_TAG_AUTUMN,
    SeasonTag.WINTER: SEASON_TAG_WINTER,
}
HOLIDAY_EMIT_TOKEN = {
    HolidayTag.HALLOWEEN: HOLIDAY_TAG_HALLOWEEN,
    HolidayTag.THANKSGIVING: HOLIDAY_TAG_THANKSGIVING,
    HolidayTag.CHRISTMAS: HOLIDAY_TAG_CHRISTMAS,
    HolidayTag.EASTER: HOLIDAY_TAG_EASTER,
}


class MalformedFilenameError(Exception):
    """A library filename does not match the README §4 tag scheme."""

    def __init__(self, filename: str, reason: str) -> None:
        self.filename = filename
        self.reason = reason
        super().__init__(f"{filename}: {reason}")


@dataclass(frozen=True)
class _FilenameParts:
    season_episode_numbers: tuple[tuple[int, int], ...]
    daypart_tokens: tuple[str, ...]
    season_tokens: tuple[str, ...]
    holiday_tokens: tuple[str, ...]
    leftover_tokens: tuple[str, ...]


def parse_filename(name: str) -> Episode:
    show_stem, parts, file_extension = _split_filename(name)
    daypart = _daypart_from_tokens(name, parts.daypart_tokens)
    season_tag = _season_from_tokens(name, parts.season_tokens)
    holiday_tag = _holiday_from_tokens(name, parts.holiday_tokens)
    if show_stem in CARTOON_SHOW_STEMS:
        season_number, episode_number = _cartoon_season_episode(name, parts)
        return Episode(
            filename=name,
            show_stem=show_stem,
            season_number=season_number,
            episode_number=episode_number,
            title_slug=None,
            daypart=daypart,
            season_tag=season_tag,
            holiday_tag=holiday_tag,
            file_extension=file_extension,
        )
    title_slug = _holiday_slug(name, parts)
    return Episode(
        filename=name,
        show_stem=show_stem,
        season_number=None,
        episode_number=None,
        title_slug=title_slug,
        daypart=daypart,
        season_tag=season_tag,
        holiday_tag=holiday_tag,
        file_extension=file_extension,
    )


def format_filename(episode: Episode) -> str:
    identity = _format_identity(episode)
    suffix_tokens = _canonical_tag_tokens(episode)
    if suffix_tokens:
        stem = FILENAME_TOKEN_SEPARATOR.join((identity, *suffix_tokens))
    else:
        stem = identity
    return f"{stem}{EXTENSION_SEPARATOR}{episode.file_extension}"


def _split_filename(name: str) -> tuple[str, _FilenameParts, str]:
    if name.strip() == "":
        raise MalformedFilenameError(name, "name must not be empty")
    stem, separator, file_extension = name.rpartition(EXTENSION_SEPARATOR)
    if separator == "" or file_extension == "":
        raise MalformedFilenameError(name, "missing extension")
    if stem == "":
        raise MalformedFilenameError(name, "missing show stem")
    tokens = stem.split(FILENAME_TOKEN_SEPARATOR)
    show_stem = tokens[0]
    if show_stem not in KNOWN_SHOW_STEMS:
        raise MalformedFilenameError(name, "unknown show stem")
    return show_stem, _classify_tokens(name, tuple(tokens[1:])), file_extension


def _classify_tokens(name: str, tokens: tuple[str, ...]) -> _FilenameParts:
    season_episode_numbers: list[tuple[int, int]] = []
    daypart_tokens: list[str] = []
    season_tokens: list[str] = []
    holiday_tokens: list[str] = []
    leftover_tokens: list[str] = []
    for token in tokens:
        if token == "":
            raise MalformedFilenameError(name, "empty filename token")
        season_episode = _season_episode_numbers(token)
        if season_episode is not None:
            season_episode_numbers.append(season_episode)
        elif token in DAYPART_BY_TOKEN:
            daypart_tokens.append(token)
        elif token in SEASON_BY_TOKEN:
            season_tokens.append(token)
        elif token in HOLIDAY_BY_TOKEN:
            holiday_tokens.append(token)
        else:
            leftover_tokens.append(token)
    return _FilenameParts(
        season_episode_numbers=tuple(season_episode_numbers),
        daypart_tokens=tuple(daypart_tokens),
        season_tokens=tuple(season_tokens),
        holiday_tokens=tuple(holiday_tokens),
        leftover_tokens=tuple(leftover_tokens),
    )


def _season_episode_numbers(token: str) -> tuple[int, int] | None:
    match = SEASON_EPISODE_PATTERN.fullmatch(token)
    if match is None:
        return None
    return int(match.group(1)), int(match.group(2))


def _daypart_from_tokens(name: str, tokens: tuple[str, ...]) -> Daypart:
    if len(tokens) > 1:
        raise MalformedFilenameError(name, "duplicate daypart tag")
    if not tokens:
        return Daypart.GENERAL
    return DAYPART_BY_TOKEN[tokens[0]]


def _season_from_tokens(name: str, tokens: tuple[str, ...]) -> SeasonTag:
    if len(tokens) > 1:
        raise MalformedFilenameError(name, "duplicate season tag")
    if not tokens:
        return SeasonTag.EVERGREEN
    return SEASON_BY_TOKEN[tokens[0]]


def _holiday_from_tokens(name: str, tokens: tuple[str, ...]) -> HolidayTag | None:
    if len(tokens) > 1:
        raise MalformedFilenameError(name, "duplicate holiday tag")
    if not tokens:
        return None
    return HOLIDAY_BY_TOKEN[tokens[0]]


def _cartoon_season_episode(name: str, parts: _FilenameParts) -> tuple[int, int]:
    if parts.leftover_tokens:
        raise MalformedFilenameError(name, "unknown tag")
    if len(parts.season_episode_numbers) > 1:
        raise MalformedFilenameError(name, "duplicate season-episode identity")
    if not parts.season_episode_numbers:
        raise MalformedFilenameError(name, "missing season-episode identity")
    return parts.season_episode_numbers[0]


def _holiday_slug(name: str, parts: _FilenameParts) -> str:
    if parts.season_episode_numbers:
        raise MalformedFilenameError(
            name, "holiday movie must not use season-episode identity"
        )
    if not parts.leftover_tokens:
        raise MalformedFilenameError(name, "missing title slug")
    return FILENAME_TOKEN_SEPARATOR.join(parts.leftover_tokens)


def _format_identity(episode: Episode) -> str:
    if episode.show_stem == HOLIDAY_SHOW_STEM:
        return FILENAME_TOKEN_SEPARATOR.join(
            (episode.show_stem, episode.holiday_title_slug())
        )
    season_number, episode_number = episode.cartoon_season_and_episode()
    season_episode_token = f"S{season_number:02d}E{episode_number:02d}"
    return FILENAME_TOKEN_SEPARATOR.join((episode.show_stem, season_episode_token))


def _canonical_tag_tokens(episode: Episode) -> tuple[str, ...]:
    tokens: list[str] = []
    daypart_token = DAYPART_EMIT_TOKEN.get(episode.daypart)
    if daypart_token is not None:
        tokens.append(daypart_token)
    season_token = SEASON_EMIT_TOKEN.get(episode.season_tag)
    if season_token is not None:
        tokens.append(season_token)
    if episode.holiday_tag is not None:
        tokens.append(HOLIDAY_EMIT_TOKEN[episode.holiday_tag])
    return tuple(tokens)
