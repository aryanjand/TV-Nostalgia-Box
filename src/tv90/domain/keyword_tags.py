"""Keyword-to-tag matching and merge with existing filename tags. No I/O."""

from __future__ import annotations

import re
import tomllib
from collections.abc import Mapping, Sequence
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

# Whole-word tokens so "ice" cannot match "nice". Phrase keywords match
# consecutive tokens. Extra spellings live in the rules file.
WORD_PATTERN = re.compile(r"[a-z0-9]+")
KEYWORD_PHRASE_PATTERN = re.compile(r"^[a-z0-9]+(?: [a-z0-9]+)*$")
REPEATED_SPACES_PATTERN = re.compile(r" +")
KEYWORD_WORD_SEPARATOR = " "
RULES_TABLE_KEY = "rule"
RULE_TAG_KEY = "tag"
RULE_KEYWORDS_KEY = "keywords"
RULE_TITLE_KEYWORDS_KEY = "title_keywords"
RULE_PLOT_KEYWORDS_KEY = "plot_keywords"
RULE_EXCLUDE_PHRASES_KEY = "exclude_phrases"

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
    title_keywords: tuple[str, ...] = ()
    plot_keywords: tuple[str, ...] = ()
    exclude_phrases: tuple[str, ...] = ()

    def terms_for_title(self) -> tuple[str, ...]:
        if self.title_keywords:
            return self.title_keywords
        return self.keywords

    def terms_for_plot(self) -> tuple[str, ...]:
        if self.title_keywords or self.plot_keywords:
            return self.plot_keywords
        return self.keywords


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
    combined_tokens = WORD_PATTERN.findall(f"{title} {description}".lower())
    title_matches = _matches_in_text(title, rules, for_title=True)
    plot_matches = _matches_in_text(
        description,
        rules,
        for_title=False,
        suppressed=_suppressed_plot_keywords(rules, combined_tokens),
    )
    return _prefer_title_kind_matches(title_matches, plot_matches)


def _matches_in_text(
    text: str,
    rules: Sequence[KeywordTagRule],
    *,
    for_title: bool,
    suppressed: Mapping[str, frozenset[str]] | None = None,
) -> tuple[KeywordMatch, ...]:
    tokens = WORD_PATTERN.findall(text.lower())
    token_set = frozenset(tokens)
    blocked_by_tag = suppressed or {}
    matches: list[KeywordMatch] = []
    for rule in rules:
        blocked = blocked_by_tag.get(rule.tag, frozenset())
        terms = rule.terms_for_title() if for_title else rule.terms_for_plot()
        triggered = tuple(
            keyword
            for keyword in terms
            if keyword not in blocked
            and _keyword_is_triggered(keyword, tokens, token_set)
        )
        if triggered:
            matches.append(KeywordMatch(tag=rule.tag, keywords=triggered))
    return tuple(matches)


def _suppressed_plot_keywords(
    rules: Sequence[KeywordTagRule], tokens: Sequence[str]
) -> dict[str, frozenset[str]]:
    suppressed: dict[str, frozenset[str]] = {}
    for rule in rules:
        blocked: set[str] = set()
        for phrase in rule.exclude_phrases:
            phrase_tokens = _keyword_tokens(phrase)
            if not _consecutive_tokens_match(phrase_tokens, tokens):
                continue
            for keyword in rule.terms_for_plot():
                if _consecutive_tokens_match(_keyword_tokens(keyword), phrase_tokens):
                    blocked.add(keyword)
        if blocked:
            suppressed[rule.tag] = frozenset(blocked)
    return suppressed


def _match_kind(tag: str) -> str:
    if tag in DAYPART_FROM_RULE_TAG:
        return "daypart"
    if tag in SEASON_FROM_RULE_TAG:
        return "season"
    if tag in HOLIDAY_FROM_RULE_TAG:
        return "holiday"
    return tag


def _prefer_title_kind_matches(
    title_matches: Sequence[KeywordMatch],
    description_matches: Sequence[KeywordMatch],
) -> tuple[KeywordMatch, ...]:
    title_kinds = {_match_kind(match.tag) for match in title_matches}
    description_by_tag = {match.tag: match for match in description_matches}
    merged: list[KeywordMatch] = []
    for match in title_matches:
        extra = description_by_tag.get(match.tag)
        if extra is None:
            merged.append(match)
            continue
        keywords = tuple(dict.fromkeys((*match.keywords, *extra.keywords)))
        merged.append(KeywordMatch(tag=match.tag, keywords=keywords))
    for match in description_matches:
        if _match_kind(match.tag) in title_kinds:
            continue
        merged.append(match)
    return tuple(merged)


def propose_tagged_episode(
    episode: Episode, matches: Sequence[KeywordMatch]
) -> TagProposal:
    daypart = episode.daypart
    season_tag = episode.season_tag
    holiday_tag = episode.holiday_tag
    applied: list[KeywordMatch] = []
    for match in _prefer_longest_new_matches(matches):
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
    shared = _optional_phrases(raw_rule, RULE_KEYWORDS_KEY, tag)
    title_keywords = _optional_phrases(raw_rule, RULE_TITLE_KEYWORDS_KEY, tag)
    plot_keywords = _optional_phrases(raw_rule, RULE_PLOT_KEYWORDS_KEY, tag)
    exclude_phrases = _optional_phrases(raw_rule, RULE_EXCLUDE_PHRASES_KEY, tag) or ()
    if title_keywords is None and plot_keywords is None:
        if not shared:
            raise InvalidKeywordRulesError(f"{tag} must list at least one keyword")
        return KeywordTagRule(tag=tag, keywords=shared, exclude_phrases=exclude_phrases)
    resolved_title = title_keywords if title_keywords is not None else shared or ()
    resolved_plot = plot_keywords if plot_keywords is not None else shared or ()
    if not resolved_title and not resolved_plot:
        raise InvalidKeywordRulesError(f"{tag} must list at least one keyword")
    return KeywordTagRule(
        tag=tag,
        keywords=tuple(dict.fromkeys((*resolved_title, *resolved_plot))),
        title_keywords=resolved_title,
        plot_keywords=resolved_plot,
        exclude_phrases=exclude_phrases,
    )


def _require_tag(value: object, seen_tags: set[str]) -> str:
    if not isinstance(value, str) or value == "":
        raise InvalidKeywordRulesError("rule tag must be a non-empty string")
    if value not in KNOWN_RULE_TAGS:
        raise InvalidKeywordRulesError(f"unknown keyword tag {value!r}")
    if value in seen_tags:
        raise InvalidKeywordRulesError(f"duplicate keyword tag {value!r}")
    return value


def _optional_phrases(
    raw_rule: Mapping[str, object], key: str, tag: str
) -> tuple[str, ...] | None:
    if key not in raw_rule:
        return None
    return _require_phrases(raw_rule[key], tag, allow_empty=True)


def _require_keywords(value: object, tag: str) -> tuple[str, ...]:
    return _require_phrases(value, tag, allow_empty=False)


def _require_phrases(value: object, tag: str, *, allow_empty: bool) -> tuple[str, ...]:
    if not isinstance(value, list):
        raise InvalidKeywordRulesError(f"{tag} keywords must be a list of strings")
    if not value:
        if allow_empty:
            return ()
        raise InvalidKeywordRulesError(f"{tag} must list at least one keyword")
    keywords: list[str] = []
    seen: set[str] = set()
    for item in value:
        if not isinstance(item, str) or item.strip() == "":
            raise InvalidKeywordRulesError(f"{tag} keywords must be non-empty strings")
        phrase = _normalize_keyword(item)
        if KEYWORD_PHRASE_PATTERN.fullmatch(phrase) is None:
            raise InvalidKeywordRulesError(
                f"{tag} keyword {item!r} must be alphanumeric words "
                "separated by single spaces"
            )
        if phrase in seen:
            continue
        seen.add(phrase)
        keywords.append(phrase)
    return tuple(keywords)


def _normalize_keyword(item: str) -> str:
    return REPEATED_SPACES_PATTERN.sub(KEYWORD_WORD_SEPARATOR, item.strip().lower())


def _keyword_tokens(keyword: str) -> tuple[str, ...]:
    return tuple(keyword.split(KEYWORD_WORD_SEPARATOR))


def _keyword_is_triggered(
    keyword: str, tokens: Sequence[str], token_set: frozenset[str]
) -> bool:
    phrase = _keyword_tokens(keyword)
    if len(phrase) == 1:
        return phrase[0] in token_set
    return _consecutive_tokens_match(phrase, tokens)


def _consecutive_tokens_match(phrase: Sequence[str], tokens: Sequence[str]) -> bool:
    width = len(phrase)
    phrase_tokens = tuple(phrase)
    return any(
        tuple(tokens[start : start + width]) == phrase_tokens
        for start in range(len(tokens) - width + 1)
    )


def _prefer_longest_new_matches(
    matches: Sequence[KeywordMatch],
) -> tuple[KeywordMatch, ...]:
    ranked = sorted(enumerate(matches), key=_new_match_rank)
    return tuple(match for _, match in ranked)


def _new_match_rank(indexed: tuple[int, KeywordMatch]) -> tuple[int, int]:
    index, match = indexed
    return (-_longest_triggered_token_count(match), index)


def _longest_triggered_token_count(match: KeywordMatch) -> int:
    return max(len(_keyword_tokens(keyword)) for keyword in match.keywords)
