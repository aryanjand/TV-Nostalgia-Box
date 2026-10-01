"""Keyword-to-tag matching and merge with existing filename tags. No I/O."""

from __future__ import annotations

import re
import tomllib
from collections.abc import Sequence
from dataclasses import dataclass, replace

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
from tv90.domain.filename import format_filename

# Whole-word tokens so "ice" cannot match "nice". Extra spellings live in the
# rules file.
WORD_PATTERN = re.compile(r"[a-z0-9]+")
KEYWORD_TOKEN_PATTERN = re.compile(r"^[a-z0-9]+$")
RULES_TABLE_KEY = "rule"
RULE_TAG_KEY = "tag"
RULE_KEYWORDS_KEY = "keywords"

DAYPART_FROM_RULE_TAG = {
    DAYPART_TAG_MORNING: Daypart.MORNING,
    DAYPART_TAG_NIGHT: Daypart.NIGHT,
}
SEASON_FROM_RULE_TAG = {
    SEASON_TAG_SPRING: SeasonTag.SPRING,
    SEASON_TAG_SUMMER: SeasonTag.SUMMER,
    SEASON_TAG_AUTUMN: SeasonTag.AUTUMN,
    SEASON_TAG_WINTER: SeasonTag.WINTER,
}
HOLIDAY_FROM_RULE_TAG = {
    HOLIDAY_TAG_HALLOWEEN: HolidayTag.HALLOWEEN,
    HOLIDAY_TAG_THANKSGIVING: HolidayTag.THANKSGIVING,
    HOLIDAY_TAG_CHRISTMAS: HolidayTag.CHRISTMAS,
    HOLIDAY_TAG_EASTER: HolidayTag.EASTER,
}
KNOWN_RULE_TAGS = (
    frozenset(DAYPART_FROM_RULE_TAG)
    | frozenset(SEASON_FROM_RULE_TAG)
    | frozenset(HOLIDAY_FROM_RULE_TAG)
)


class InvalidKeywordRulesError(Exception):
    """The keyword rules document is not a usable tag table."""

    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(reason)


@dataclass(frozen=True)
class KeywordTagRule:
    tag: str
    keywords: tuple[str, ...]


@dataclass(frozen=True)
class KeywordMatch:
    tag: str
    keywords: tuple[str, ...]


@dataclass(frozen=True)
class TagProposal:
    episode: Episode
    applied_matches: tuple[KeywordMatch, ...]


def parse_keyword_rules(toml_text: str) -> tuple[KeywordTagRule, ...]:
    try:
        loaded: object = tomllib.loads(toml_text)
    except tomllib.TOMLDecodeError as error:
        raise InvalidKeywordRulesError("keyword rules are not valid TOML") from error
    if not isinstance(loaded, dict):
        raise InvalidKeywordRulesError("keyword rules must be a TOML table")
    raw_rules: object = loaded.get(RULES_TABLE_KEY)
    if not isinstance(raw_rules, list) or not raw_rules:
        raise InvalidKeywordRulesError("keyword rules must list [[rule]] entries")
    parsed: list[KeywordTagRule] = []
    seen_tags: set[str] = set()
    for raw_rule in raw_rules:
        rule = _parse_one_rule(raw_rule, seen_tags)
        seen_tags.add(rule.tag)
        parsed.append(rule)
    return tuple(parsed)


def match_keywords(
    title: str, description: str, rules: Sequence[KeywordTagRule]
) -> tuple[KeywordMatch, ...]:
    words = frozenset(WORD_PATTERN.findall(f"{title} {description}".lower()))
    matches: list[KeywordMatch] = []
    for rule in rules:
        triggered = tuple(keyword for keyword in rule.keywords if keyword in words)
        if triggered:
            matches.append(KeywordMatch(tag=rule.tag, keywords=triggered))
    return tuple(matches)


def propose_tagged_episode(
    episode: Episode, matches: Sequence[KeywordMatch]
) -> TagProposal:
    daypart = episode.daypart
    season_tag = episode.season_tag
    holiday_tag = episode.holiday_tag
    applied: list[KeywordMatch] = []
    for match in matches:
        if match.tag in DAYPART_FROM_RULE_TAG:
            if daypart is not Daypart.GENERAL:
                continue
            daypart = DAYPART_FROM_RULE_TAG[match.tag]
            applied.append(match)
        elif match.tag in SEASON_FROM_RULE_TAG:
            if season_tag is not SeasonTag.EVERGREEN:
                continue
            season_tag = SEASON_FROM_RULE_TAG[match.tag]
            applied.append(match)
        elif match.tag in HOLIDAY_FROM_RULE_TAG:
            if holiday_tag is not None:
                continue
            holiday_tag = HOLIDAY_FROM_RULE_TAG[match.tag]
            applied.append(match)
        else:
            raise InvalidKeywordRulesError(f"unknown keyword tag {match.tag!r}")
    updated = replace(
        episode,
        daypart=daypart,
        season_tag=season_tag,
        holiday_tag=holiday_tag,
    )
    return TagProposal(
        episode=replace(updated, filename=format_filename(updated)),
        applied_matches=tuple(applied),
    )


def _parse_one_rule(raw_rule: object, seen_tags: set[str]) -> KeywordTagRule:
    if not isinstance(raw_rule, dict):
        raise InvalidKeywordRulesError("each [[rule]] must be a table")
    tag = _require_tag(raw_rule.get(RULE_TAG_KEY), seen_tags)
    keywords = _require_keywords(raw_rule.get(RULE_KEYWORDS_KEY), tag)
    return KeywordTagRule(tag=tag, keywords=keywords)


def _require_tag(value: object, seen_tags: set[str]) -> str:
    if not isinstance(value, str) or value == "":
        raise InvalidKeywordRulesError("rule tag must be a non-empty string")
    if value not in KNOWN_RULE_TAGS:
        raise InvalidKeywordRulesError(f"unknown keyword tag {value!r}")
    if value in seen_tags:
        raise InvalidKeywordRulesError(f"duplicate keyword tag {value!r}")
    return value


def _require_keywords(value: object, tag: str) -> tuple[str, ...]:
    if not isinstance(value, list) or not value:
        raise InvalidKeywordRulesError(f"{tag} must list at least one keyword")
    keywords: list[str] = []
    seen: set[str] = set()
    for item in value:
        if not isinstance(item, str) or item.strip() == "":
            raise InvalidKeywordRulesError(f"{tag} keywords must be non-empty strings")
        token = item.strip().lower()
        if KEYWORD_TOKEN_PATTERN.fullmatch(token) is None:
            raise InvalidKeywordRulesError(
                f"{tag} keyword {item!r} must be a single alphanumeric word"
            )
        if token in seen:
            continue
        seen.add(token)
        keywords.append(token)
    return tuple(keywords)
