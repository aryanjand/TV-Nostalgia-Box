from pathlib import Path

import pytest

from tv90.domain.episode import Daypart, HolidayTag, SeasonTag
from tv90.domain.filename import parse_filename
from tv90.domain.keyword_tags import (
    InvalidKeywordRulesError,
    KeywordMatch,
    KeywordTagRule,
    match_keywords,
    parse_keyword_rules,
    propose_tagged_episode,
)

RULES_PATH = (
    Path(__file__).resolve().parents[1] / "src" / "tv90" / "data" / "keyword_rules.toml"
)
STARTING_RULES = (
    KeywordTagRule(tag="WINTER", keywords=("snow", "sled", "ice")),
    KeywordTagRule(tag="NIGHT", keywords=("moon", "bedtime", "sleep", "stars")),
    KeywordTagRule(tag="MORNING", keywords=("breakfast", "wake", "sunrise")),
    KeywordTagRule(tag="HALLOWEEN", keywords=("pumpkin", "costume")),
)


def test_snow_matches_winter() -> None:
    matches = match_keywords("Snow Day", "", STARTING_RULES)

    assert [(match.tag, match.keywords) for match in matches] == [("WINTER", ("snow",))]


def test_moon_matches_night() -> None:
    matches = match_keywords("The Moon", "stars at bedtime", STARTING_RULES)

    assert matches[0].tag == "NIGHT"
    assert "moon" in matches[0].keywords
    assert "stars" in matches[0].keywords
    assert "bedtime" in matches[0].keywords


def test_breakfast_matches_morning() -> None:
    matches = match_keywords("Breakfast with Kipper", "", STARTING_RULES)

    assert [(match.tag, match.keywords) for match in matches] == [
        ("MORNING", ("breakfast",))
    ]


def test_pumpkin_matches_halloween() -> None:
    matches = match_keywords("Pumpkin Party", "a costume", STARTING_RULES)

    assert matches[0].tag == "HALLOWEEN"
    assert matches[0].keywords == ("pumpkin", "costume")


def test_packaged_rules_do_not_treat_costume_party_as_halloween() -> None:
    rules = parse_keyword_rules(RULES_PATH.read_text(encoding="utf-8"))
    matches = match_keywords("The Costume Party", "", rules)

    assert all(match.tag != "HALLOWEEN" for match in matches)


def test_wake_in_its_wake_is_not_morning() -> None:
    rules = parse_keyword_rules(RULES_PATH.read_text(encoding="utf-8"))
    matches = match_keywords(
        "The Nanosaurus",
        "follow the trail of wreckage left in its wake",
        rules,
    )

    assert all(match.tag != "MORNING" for match in matches)


def test_title_night_beats_description_breakfast() -> None:
    rules = parse_keyword_rules(RULES_PATH.read_text(encoding="utf-8"))
    matches = match_keywords(
        "Can I Sleep in My Tent?",
        "Nana makes breakfast for Harry.",
        rules,
    )
    proposal = propose_tagged_episode(parse_filename("Harry_S01E25.mp4"), matches)

    assert proposal.episode.daypart is Daypart.NIGHT
    assert all(match.tag != "MORNING" for match in proposal.applied_matches)


def test_ice_does_not_match_inside_nice() -> None:
    matches = match_keywords("A Nice Day", "", STARTING_RULES)

    assert matches == ()


def test_unmatched_text_returns_no_tags() -> None:
    matches = match_keywords("Friends play a game", "in the house", STARTING_RULES)

    assert matches == ()


def test_packaged_rules_cover_starting_examples_and_extra_seasons() -> None:
    rules = parse_keyword_rules(RULES_PATH.read_text(encoding="utf-8"))
    tags_by_keyword_sample = {
        match_keywords("snow", "", rules)[0].tag,
        match_keywords("night", "", rules)[0].tag,
        match_keywords("breakfast", "", rules)[0].tag,
        match_keywords("pumpkin", "", rules)[0].tag,
        match_keywords("spring bloom", "", rules)[0].tag,
        match_keywords("summer picnic", "", rules)[0].tag,
        match_keywords("autumn harvest", "", rules)[0].tag,
        match_keywords("thanksgiving turkey", "", rules)[0].tag,
        match_keywords("christmas santa", "", rules)[0].tag,
        match_keywords("easter bunny", "", rules)[0].tag,
    }
    ice_cream = propose_tagged_episode(
        parse_filename("Oswald_S01E01.mp4"),
        match_keywords("ICE-Cream", "", rules),
    )

    assert tags_by_keyword_sample == {
        "WINTER",
        "NIGHT",
        "MORNING",
        "HALLOWEEN",
        "SPRING",
        "SUMMER",
        "AUTUMN",
        "THANKSGIVING",
        "CHRISTMAS",
        "EASTER",
    }
    assert ice_cream.episode.season_tag is SeasonTag.SUMMER


@pytest.mark.parametrize(
    ("title", "description", "season_tag", "daypart", "holiday_tag"),
    [
        (
            "The Visitor",
            "Kipper is disturbed by a visitor in the night.",
            None,
            Daypart.NIGHT,
            None,
        ),
        ("The Seaside", "", SeasonTag.SUMMER, Daypart.GENERAL, None),
        ("Snowy Day", "", SeasonTag.WINTER, Daypart.GENERAL, None),
        ("The Paddling Pool", "", SeasonTag.SUMMER, Daypart.GENERAL, None),
        ("The Conker Tree", "", SeasonTag.AUTUMN, Daypart.GENERAL, None),
        ("Sleepless Night", "", None, Daypart.NIGHT, None),
        ("The Igloo", "", SeasonTag.WINTER, Daypart.GENERAL, None),
        ("The Nest", "", SeasonTag.SPRING, Daypart.GENERAL, None),
        ("The Picnic", "", SeasonTag.SUMMER, Daypart.GENERAL, None),
        ("Tiger's Sled", "", SeasonTag.WINTER, Daypart.GENERAL, None),
        ("The Swimming Pool", "", SeasonTag.SUMMER, Daypart.GENERAL, None),
        ("Christmas Eve", "", None, Daypart.GENERAL, HolidayTag.CHRISTMAS),
        ("The Big Freeze", "", SeasonTag.WINTER, Daypart.GENERAL, None),
        ("The Costume Party", "", None, Daypart.GENERAL, None),
        ("The Umbrella", "", None, Daypart.GENERAL, None),
        ("Nothing Ever Happens", "", None, Daypart.GENERAL, None),
        ("Tiger's Cold", "", None, Daypart.GENERAL, None),
        ("The Little Ghost", "", None, Daypart.GENERAL, None),
        ("The Holiday", "", None, Daypart.GENERAL, None),
        ("Skates", "", None, Daypart.GENERAL, None),
        ("Chasing the Ice-Cream Truck", "", SeasonTag.SUMMER, Daypart.GENERAL, None),
        ("Autumn Leaves", "", SeasonTag.AUTUMN, Daypart.GENERAL, None),
        ("A Day at the Beach", "", SeasonTag.SUMMER, Daypart.GENERAL, None),
        ("What's for Breakfast?", "", None, Daypart.MORNING, None),
        ("I See a Seashell!", "", SeasonTag.SUMMER, Daypart.GENERAL, None),
        (
            "I Don't Wanna Go to Bed",
            "",
            None,
            Daypart.NIGHT,
            None,
        ),
        (
            "Aaagh!",
            "Harry has a nightmare about a monster.",
            None,
            Daypart.NIGHT,
            None,
        ),
        (
            "Can I Sleep in My Tent?",
            "They follow the wreckage left in its wake after breakfast.",
            None,
            Daypart.NIGHT,
            None,
        ),
        ("Sleepover", "the next morning a banana grows", None, Daypart.NIGHT, None),
        (
            "I'm Really Hot!",
            "they marvel at the lovely winter weather and a snowstorm",
            SeasonTag.SUMMER,
            Daypart.GENERAL,
            None,
        ),
        (
            "Abracadabra!",
            "Harry receives a box of magic tricks for Christmas.",
            None,
            Daypart.GENERAL,
            None,
        ),
        (
            "The Postman's Here!",
            "A letter addressed to a Mr. Snow is delivered to Harry.",
            None,
            Daypart.GENERAL,
            None,
        ),
        (
            "Somebody's Moving",
            "It is snowing. They help Mr. Snow move to a new igloo.",
            SeasonTag.WINTER,
            Daypart.GENERAL,
            None,
        ),
        (
            "It's Made of Cheese!",
            "They take a rocket to the moon to see if it is cheese.",
            None,
            Daypart.GENERAL,
            None,
        ),
        (
            "Blast Off / Space Captain Harry",
            "Groups of stars make pictures called constellations.",
            None,
            Daypart.GENERAL,
            None,
        ),
        (
            "The Bleepers",
            "Kipper helps the Bleepers return home to the moon.",
            None,
            Daypart.GENERAL,
            None,
        ),
        (
            "Odd One Out / Goodbye Best Friend",
            "Henry decides to move back to the Frozen North.",
            None,
            Daypart.GENERAL,
            None,
        ),
        (
            "Weenie Needs a Bath / Hide and Seek",
            "Weenie hitches a ride in Johnny's ice cream truck.",
            None,
            Daypart.GENERAL,
            None,
        ),
        (
            "The Tomato Garden / Bird Watching",
            "Oswald eats his last tomato for breakfast.",
            None,
            Daypart.GENERAL,
            None,
        ),
        (
            "Can I Keep It? / I Don't Wanna Go to Bed",
            "Harry finds a nest with an egg in it.",
            SeasonTag.SPRING,
            Daypart.NIGHT,
            None,
        ),
        (
            "Job for a Day",
            "Oswald and Weenie make a special ice cream delivery.",
            SeasonTag.SUMMER,
            Daypart.GENERAL,
            None,
        ),
    ],
)
def test_packaged_rules_tag_library_titles_accurately(
    title: str,
    description: str,
    season_tag: SeasonTag | None,
    daypart: Daypart,
    holiday_tag: HolidayTag | None,
) -> None:
    rules = parse_keyword_rules(RULES_PATH.read_text(encoding="utf-8"))
    proposal = propose_tagged_episode(
        parse_filename("Kipper_S01E01.mp4"),
        match_keywords(title, description, rules),
    )

    assert proposal.episode.season_tag is (
        season_tag if season_tag is not None else SeasonTag.EVERGREEN
    )
    assert proposal.episode.daypart is daypart
    assert proposal.episode.holiday_tag is holiday_tag


def test_existing_morning_is_kept_when_night_keywords_match() -> None:
    episode = parse_filename("Kipper_S01E01_MORNING.mp4")
    matches = match_keywords("Moon", "bedtime sleep stars", STARTING_RULES)

    proposal = propose_tagged_episode(episode, matches)

    assert proposal.episode.daypart is Daypart.MORNING
    assert proposal.episode.season_tag is SeasonTag.EVERGREEN
    assert all(match.tag != "NIGHT" for match in proposal.applied_matches)
    assert proposal.episode.filename == "Kipper_S01E01_MORNING.mp4"


def test_new_tags_are_added_when_absent() -> None:
    episode = parse_filename("Kipper_S01E01.mp4")
    matches = match_keywords("Snow", "ice on the sled", STARTING_RULES)

    proposal = propose_tagged_episode(episode, matches)

    assert proposal.episode.season_tag is SeasonTag.WINTER
    assert proposal.episode.filename == "Kipper_S01E01_WINTER.mp4"
    assert proposal.applied_matches[0].tag == "WINTER"


def test_first_same_kind_rule_wins_when_both_dayparts_match() -> None:
    rules = (
        KeywordTagRule(tag="MORNING", keywords=("breakfast",)),
        KeywordTagRule(tag="NIGHT", keywords=("moon",)),
    )
    episode = parse_filename("Oswald_S01E01.mp4")
    matches = match_keywords("breakfast moon", "", rules)

    proposal = propose_tagged_episode(episode, matches)

    assert proposal.episode.daypart is Daypart.MORNING
    assert [match.tag for match in proposal.applied_matches] == ["MORNING"]


def test_holiday_tag_is_added_from_keywords() -> None:
    episode = parse_filename("Kipper_S01E04.mp4")
    matches = match_keywords("Pumpkin", "", STARTING_RULES)

    proposal = propose_tagged_episode(episode, matches)

    assert proposal.episode.holiday_tag is HolidayTag.HALLOWEEN
    assert proposal.episode.filename == "Kipper_S01E04_HALLOWEEN.mp4"


def test_parse_keyword_rules_rejects_unknown_tag() -> None:
    with pytest.raises(InvalidKeywordRulesError):
        parse_keyword_rules('[[rule]]\ntag = "SPICY"\nkeywords = ["hot"]\n')


def test_parse_keyword_rules_rejects_empty_keywords() -> None:
    with pytest.raises(InvalidKeywordRulesError):
        parse_keyword_rules('[[rule]]\ntag = "WINTER"\nkeywords = []\n')


def test_parse_keyword_rules_rejects_invalid_toml() -> None:
    with pytest.raises(InvalidKeywordRulesError, match="not valid TOML"):
        parse_keyword_rules("[[rule]\n")


def test_parse_keyword_rules_rejects_missing_rule_table() -> None:
    with pytest.raises(InvalidKeywordRulesError, match="\\[\\[rule\\]\\]"):
        parse_keyword_rules('tag = "WINTER"\n')


def test_parse_keyword_rules_rejects_duplicate_tag() -> None:
    text = (
        '[[rule]]\ntag = "WINTER"\nkeywords = ["snow"]\n'
        '[[rule]]\ntag = "WINTER"\nkeywords = ["ice"]\n'
    )
    with pytest.raises(InvalidKeywordRulesError, match="duplicate"):
        parse_keyword_rules(text)


def test_parse_keyword_rules_rejects_non_table_rule() -> None:
    with pytest.raises(InvalidKeywordRulesError, match="must be a table"):
        parse_keyword_rules('rule = ["snow"]\n')


def test_parse_keyword_rules_rejects_empty_tag() -> None:
    with pytest.raises(InvalidKeywordRulesError, match="non-empty string"):
        parse_keyword_rules('[[rule]]\ntag = ""\nkeywords = ["snow"]\n')


def test_parse_keyword_rules_rejects_non_string_keyword() -> None:
    with pytest.raises(InvalidKeywordRulesError, match="non-empty strings"):
        parse_keyword_rules('[[rule]]\ntag = "WINTER"\nkeywords = [1]\n')


def test_parse_keyword_rules_allows_phrase_keyword() -> None:
    rules = parse_keyword_rules('[[rule]]\ntag = "SUMMER"\nkeywords = ["ice cream"]\n')

    assert rules == (KeywordTagRule(tag="SUMMER", keywords=("ice cream",)),)


def test_parse_keyword_rules_collapses_repeated_spaces_in_phrase() -> None:
    rules = parse_keyword_rules('[[rule]]\ntag = "SUMMER"\nkeywords = ["ice  cream"]\n')

    assert rules == (KeywordTagRule(tag="SUMMER", keywords=("ice cream",)),)


def test_parse_keyword_rules_rejects_hyphenated_keyword() -> None:
    with pytest.raises(InvalidKeywordRulesError, match="alphanumeric"):
        parse_keyword_rules('[[rule]]\ntag = "SUMMER"\nkeywords = ["ice-cream"]\n')


def test_parse_keyword_rules_rejects_tab_in_keyword() -> None:
    with pytest.raises(InvalidKeywordRulesError, match="alphanumeric"):
        parse_keyword_rules('[[rule]]\ntag = "SUMMER"\nkeywords = ["ice\\tcream"]\n')


def test_title_ice_cream_truck_still_tags_summer() -> None:
    rules = parse_keyword_rules(RULES_PATH.read_text(encoding="utf-8"))
    matches = match_keywords(
        "Chasing the Ice-Cream Truck",
        "Oswald and Weenie chase after Johnny's ice cream truck.",
        rules,
    )
    proposal = propose_tagged_episode(parse_filename("Oswald_S01E01.mp4"), matches)

    assert proposal.episode.season_tag is SeasonTag.SUMMER


@pytest.mark.parametrize("title", ["ICE-Cream", "Ice Cream"])
def test_ice_cream_titles_propose_summer(title: str) -> None:
    rules = parse_keyword_rules(RULES_PATH.read_text(encoding="utf-8"))
    matches = match_keywords(title, "", rules)
    summer = next(match for match in matches if match.tag == "SUMMER")

    assert "ice cream" in summer.keywords

    proposal = propose_tagged_episode(parse_filename("Oswald_S01E01.mp4"), matches)

    assert proposal.episode.season_tag is SeasonTag.SUMMER
    assert proposal.episode.filename == "Oswald_S01E01_SUMMER.mp4"
    assert all(match.tag != "WINTER" for match in proposal.applied_matches)


def test_longer_phrase_beats_earlier_same_kind_rule() -> None:
    rules = (
        KeywordTagRule(tag="WINTER", keywords=("ice",)),
        KeywordTagRule(tag="SUMMER", keywords=("ice cream",)),
    )
    episode = parse_filename("Oswald_S01E01.mp4")
    matches = match_keywords("ICE-Cream", "", rules)

    proposal = propose_tagged_episode(episode, matches)

    assert proposal.episode.season_tag is SeasonTag.SUMMER
    assert [match.tag for match in proposal.applied_matches] == ["SUMMER"]


def test_parse_keyword_rules_deduplicates_keywords() -> None:
    rules = parse_keyword_rules(
        '[[rule]]\ntag = "WINTER"\nkeywords = ["snow", "Snow", "ice"]\n'
    )

    assert rules == (KeywordTagRule(tag="WINTER", keywords=("snow", "ice")),)


def test_existing_season_is_kept_when_other_season_keywords_match() -> None:
    episode = parse_filename("Kipper_S01E01_SUMMER.mp4")
    matches = match_keywords("snow sled ice", "", STARTING_RULES)

    proposal = propose_tagged_episode(episode, matches)

    assert proposal.episode.season_tag is SeasonTag.SUMMER
    assert proposal.applied_matches == ()


def test_existing_holiday_is_kept_when_other_holiday_keywords_match() -> None:
    episode = parse_filename("Kipper_S01E01_EASTER.mp4")
    matches = match_keywords("pumpkin costume", "", STARTING_RULES)

    proposal = propose_tagged_episode(episode, matches)

    assert proposal.episode.holiday_tag is HolidayTag.EASTER
    assert proposal.applied_matches == ()


def test_unknown_match_tag_is_rejected() -> None:
    episode = parse_filename("Kipper_S01E01.mp4")
    matches = (KeywordMatch(tag="SPICY", keywords=("hot",)),)

    with pytest.raises(InvalidKeywordRulesError, match="unknown keyword tag"):
        propose_tagged_episode(episode, matches)
