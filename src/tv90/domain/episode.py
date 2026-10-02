"""Frozen episode identity and scheduler tags. No I/O."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from tv90.config import (
    HARRY_SHOW_STEM,
    HOLIDAY_SHOW_STEM,
    KIPPER_SHOW_STEM,
    OSWALD_SHOW_STEM,
)

MINIMUM_SEASON_EPISODE_NUMBER = 0
MAXIMUM_SEASON_EPISODE_NUMBER = 99

DAYPART_TAG_MORNING = "MORNING"
DAYPART_TAG_NIGHT = "NIGHT"
DAYPART_TAG_DAY = "DAY"
SEASON_TAG_SPRING = "SPRING"
SEASON_TAG_SUMMER = "SUMMER"
SEASON_TAG_AUTUMN = "AUTUMN"
SEASON_TAG_WINTER = "WINTER"
HOLIDAY_TAG_HALLOWEEN = "HALLOWEEN"
HOLIDAY_TAG_THANKSGIVING = "THANKSGIVING"
HOLIDAY_TAG_CHRISTMAS = "CHRISTMAS"
HOLIDAY_TAG_EASTER = "EASTER"

CARTOON_SHOW_STEMS = frozenset({KIPPER_SHOW_STEM, OSWALD_SHOW_STEM, HARRY_SHOW_STEM})
KNOWN_SHOW_STEMS = CARTOON_SHOW_STEMS | {HOLIDAY_SHOW_STEM}


class Daypart(Enum):
    MORNING = "morning"
    NIGHT = "night"
    GENERAL = "general"


class SeasonTag(Enum):
    SPRING = "spring"
    SUMMER = "summer"
    AUTUMN = "autumn"
    WINTER = "winter"
    EVERGREEN = "evergreen"


class HolidayTag(Enum):
    HALLOWEEN = "halloween"
    THANKSGIVING = "thanksgiving"
    CHRISTMAS = "christmas"
    EASTER = "easter"


class InvalidEpisodeError(Exception):
    """An Episode value cannot be constructed or formatted."""

    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(reason)


@dataclass(frozen=True)
class Episode:
    filename: str
    show_stem: str
    season_number: int | None
    episode_number: int | None
    title_slug: str | None
    daypart: Daypart
    season_tag: SeasonTag
    holiday_tag: HolidayTag | None
    file_extension: str

    def __post_init__(self) -> None:
        _validate_episode(self)

    def cartoon_season_and_episode(self) -> tuple[int, int]:
        if self.season_number is None or self.episode_number is None:
            raise InvalidEpisodeError(
                "cartoon episode requires season and episode numbers"
            )
        return self.season_number, self.episode_number

    def holiday_title_slug(self) -> str:
        if self.title_slug is None:
            raise InvalidEpisodeError("holiday movie requires a title slug")
        return self.title_slug


def _validate_episode(episode: Episode) -> None:
    if episode.filename == "":
        raise InvalidEpisodeError("filename must not be empty")
    if episode.file_extension == "" or "." in episode.file_extension:
        raise InvalidEpisodeError(
            "file extension must be a non-empty suffix without a dot"
        )
    if episode.show_stem not in KNOWN_SHOW_STEMS:
        raise InvalidEpisodeError(f"unknown show stem: {episode.show_stem}")
    if episode.show_stem == HOLIDAY_SHOW_STEM:
        _validate_holiday_identity(episode)
        return
    _validate_cartoon_identity(episode)


def _validate_holiday_identity(episode: Episode) -> None:
    title_slug = episode.holiday_title_slug()
    if episode.season_number is not None or episode.episode_number is not None:
        raise InvalidEpisodeError(
            "holiday movie must not have season or episode numbers"
        )
    if title_slug == "":
        raise InvalidEpisodeError("holiday movie requires a title slug")
    for token in title_slug.split("_"):
        if token == "":
            raise InvalidEpisodeError("title slug must not contain empty tokens")


def _validate_cartoon_identity(episode: Episode) -> None:
    if episode.title_slug is not None:
        raise InvalidEpisodeError("cartoon episode must not have a title slug")
    season_number, episode_number = episode.cartoon_season_and_episode()
    _require_season_episode_number(season_number, "season number")
    _require_season_episode_number(episode_number, "episode number")


def _require_season_episode_number(value: int, field_name: str) -> None:
    if value < MINIMUM_SEASON_EPISODE_NUMBER or value > MAXIMUM_SEASON_EPISODE_NUMBER:
        raise InvalidEpisodeError(
            f"{field_name} must be between "
            f"{MINIMUM_SEASON_EPISODE_NUMBER} and {MAXIMUM_SEASON_EPISODE_NUMBER}"
        )
