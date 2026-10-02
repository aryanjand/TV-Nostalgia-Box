from dataclasses import FrozenInstanceError

import pytest

from tv90.config import (
    HARRY_SHOW_STEM,
    HOLIDAY_SHOW_STEM,
    KIPPER_SHOW_STEM,
    OSWALD_SHOW_STEM,
)
from tv90.domain.episode import (
    DAYPART_TAG_DAY,
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
    InvalidEpisodeError,
    SeasonTag,
)
from tv90.domain.filename import MalformedFilenameError, format_filename, parse_filename

DAYPART_CASES = [
    pytest.param((), Daypart.GENERAL, id="daypart-omit"),
    pytest.param((DAYPART_TAG_DAY,), Daypart.GENERAL, id="daypart-DAY"),
    pytest.param((DAYPART_TAG_MORNING,), Daypart.MORNING, id="daypart-MORNING"),
    pytest.param((DAYPART_TAG_NIGHT,), Daypart.NIGHT, id="daypart-NIGHT"),
]
SEASON_CASES = [
    pytest.param((), SeasonTag.EVERGREEN, id="season-omit"),
    pytest.param((SEASON_TAG_SPRING,), SeasonTag.SPRING, id="season-SPRING"),
    pytest.param((SEASON_TAG_SUMMER,), SeasonTag.SUMMER, id="season-SUMMER"),
    pytest.param((SEASON_TAG_AUTUMN,), SeasonTag.AUTUMN, id="season-AUTUMN"),
    pytest.param((SEASON_TAG_WINTER,), SeasonTag.WINTER, id="season-WINTER"),
]
HOLIDAY_CASES = [
    pytest.param((), None, id="holiday-omit"),
    pytest.param(
        (HOLIDAY_TAG_HALLOWEEN,), HolidayTag.HALLOWEEN, id="holiday-HALLOWEEN"
    ),
    pytest.param(
        (HOLIDAY_TAG_THANKSGIVING,),
        HolidayTag.THANKSGIVING,
        id="holiday-THANKSGIVING",
    ),
    pytest.param(
        (HOLIDAY_TAG_CHRISTMAS,), HolidayTag.CHRISTMAS, id="holiday-CHRISTMAS"
    ),
    pytest.param((HOLIDAY_TAG_EASTER,), HolidayTag.EASTER, id="holiday-EASTER"),
]


def _join_filename(identity: str, tags: tuple[str, ...]) -> str:
    if not tags:
        return f"{identity}.mp4"
    return f"{identity}_{'_'.join(tags)}.mp4"


@pytest.mark.parametrize("daypart_tokens, expected_daypart", DAYPART_CASES)
@pytest.mark.parametrize("season_tokens, expected_season", SEASON_CASES)
@pytest.mark.parametrize("holiday_tokens, expected_holiday", HOLIDAY_CASES)
def test_parse_cartoon_tag_cartesian_product(
    daypart_tokens: tuple[str, ...],
    expected_daypart: Daypart,
    season_tokens: tuple[str, ...],
    expected_season: SeasonTag,
    holiday_tokens: tuple[str, ...],
    expected_holiday: HolidayTag | None,
) -> None:
    tags = daypart_tokens + season_tokens + holiday_tokens
    name = _join_filename("Kipper_S01E01", tags)

    episode = parse_filename(name)

    assert episode.filename == name
    assert episode.show_stem == KIPPER_SHOW_STEM
    assert episode.season_number == 1
    assert episode.episode_number == 1
    assert episode.title_slug is None
    assert episode.daypart is expected_daypart
    assert episode.season_tag is expected_season
    assert episode.holiday_tag is expected_holiday
    assert episode.file_extension == "mp4"
    if daypart_tokens != (DAYPART_TAG_DAY,):
        assert parse_filename(format_filename(episode)) == episode


@pytest.mark.parametrize("daypart_tokens, expected_daypart", DAYPART_CASES)
@pytest.mark.parametrize("season_tokens, expected_season", SEASON_CASES)
@pytest.mark.parametrize("holiday_tokens, expected_holiday", HOLIDAY_CASES)
def test_parse_holiday_tag_cartesian_product(
    daypart_tokens: tuple[str, ...],
    expected_daypart: Daypart,
    season_tokens: tuple[str, ...],
    expected_season: SeasonTag,
    holiday_tokens: tuple[str, ...],
    expected_holiday: HolidayTag | None,
) -> None:
    tags = daypart_tokens + season_tokens + holiday_tokens
    name = _join_filename("Holiday_Rudolph", tags)

    episode = parse_filename(name)

    assert episode.filename == name
    assert episode.show_stem == HOLIDAY_SHOW_STEM
    assert episode.season_number is None
    assert episode.episode_number is None
    assert episode.title_slug == "Rudolph"
    assert episode.daypart is expected_daypart
    assert episode.season_tag is expected_season
    assert episode.holiday_tag is expected_holiday
    assert episode.file_extension == "mp4"
    if daypart_tokens != (DAYPART_TAG_DAY,):
        assert parse_filename(format_filename(episode)) == episode


def test_parse_oswald_night_example() -> None:
    episode = parse_filename("Oswald_S01E09_NIGHT.mp4")

    assert episode.show_stem == OSWALD_SHOW_STEM
    assert episode.season_number == 1
    assert episode.episode_number == 9
    assert episode.daypart is Daypart.NIGHT
    assert episode.season_tag is SeasonTag.EVERGREEN
    assert episode.holiday_tag is None


def test_parse_harry_identity() -> None:
    episode = parse_filename("Harry_S02E03.mkv")

    assert episode.show_stem == HARRY_SHOW_STEM
    assert episode.season_number == 2
    assert episode.episode_number == 3
    assert episode.file_extension == "mkv"


def test_parse_readme_kipper_morning_winter() -> None:
    episode = parse_filename("Kipper_S01E04_MORNING_WINTER.mp4")

    assert episode.season_number == 1
    assert episode.episode_number == 4
    assert episode.daypart is Daypart.MORNING
    assert episode.season_tag is SeasonTag.WINTER


def test_day_normalizes_to_general_and_does_not_survive_format() -> None:
    episode = parse_filename("Kipper_S01E01_DAY.mp4")

    assert episode.daypart is Daypart.GENERAL
    formatted = format_filename(episode)
    assert "_DAY" not in formatted
    assert formatted == "Kipper_S01E01.mp4"
    assert parse_filename(formatted).daypart is Daypart.GENERAL


def test_parse_accepts_tags_in_any_order() -> None:
    morning_first = parse_filename("Kipper_S01E04_MORNING_WINTER.mp4")
    winter_first = parse_filename("Kipper_S01E04_WINTER_MORNING.mp4")

    assert morning_first.daypart is winter_first.daypart is Daypart.MORNING
    assert morning_first.season_tag is winter_first.season_tag is SeasonTag.WINTER
    assert format_filename(morning_first) == "Kipper_S01E04_MORNING_WINTER.mp4"
    assert format_filename(winter_first) == "Kipper_S01E04_MORNING_WINTER.mp4"


def test_parse_holiday_joins_multi_token_title_slug() -> None:
    episode = parse_filename("Holiday_The_Grinch_CHRISTMAS.mp4")

    assert episode.title_slug == "The_Grinch"
    assert episode.holiday_tag is HolidayTag.CHRISTMAS
    assert format_filename(episode) == "Holiday_The_Grinch_CHRISTMAS.mp4"


def test_parse_holiday_accepts_tag_before_title_slug() -> None:
    episode = parse_filename("Holiday_CHRISTMAS_Rudolph.mp4")

    assert episode.title_slug == "Rudolph"
    assert episode.holiday_tag is HolidayTag.CHRISTMAS
    assert format_filename(episode) == "Holiday_Rudolph_CHRISTMAS.mp4"


def test_format_omits_general_evergreen_and_missing_holiday() -> None:
    episode = parse_filename("Oswald_S01E09.avi")

    assert format_filename(episode) == "Oswald_S01E09.avi"


@pytest.mark.parametrize(
    "name",
    [
        pytest.param("", id="empty"),
        pytest.param("   ", id="whitespace"),
        pytest.param("Kipper_S01E01", id="missing-extension"),
        pytest.param("Kipper_S01E01.", id="empty-extension"),
        pytest.param(".mp4", id="missing-stem"),
        pytest.param("Bluey_S01E01.mp4", id="unknown-stem"),
        pytest.param("Kipper_S01E01_FOO.mp4", id="unknown-tag"),
        pytest.param("Kipper_S01E01_MORNING_NIGHT.mp4", id="two-dayparts"),
        pytest.param("Kipper_S01E01_DAY_MORNING.mp4", id="day-and-morning"),
        pytest.param("Kipper_S01E01_SPRING_WINTER.mp4", id="two-seasons"),
        pytest.param("Kipper_S01E01_CHRISTMAS_EASTER.mp4", id="two-holidays"),
        pytest.param("Kipper_MORNING.mp4", id="cartoon-missing-identity"),
        pytest.param("Kipper.mp4", id="cartoon-stem-only"),
        pytest.param("Kipper_S01E01_S02E03.mp4", id="two-identities"),
        pytest.param("Kipper__S01E01.mp4", id="empty-token"),
        pytest.param("Holiday_S01E01_CHRISTMAS.mp4", id="holiday-with-sxxexx"),
        pytest.param("Holiday_CHRISTMAS.mp4", id="holiday-missing-slug"),
        pytest.param("Holiday_.mp4", id="holiday-empty-slug-token"),
    ],
)
def test_parse_filename_rejects_malformed_names(name: str) -> None:
    with pytest.raises(MalformedFilenameError):
        parse_filename(name)


def test_malformed_filename_error_includes_name_and_reason() -> None:
    with pytest.raises(MalformedFilenameError) as caught:
        parse_filename("Bluey_S01E01.mp4")

    assert caught.value.filename == "Bluey_S01E01.mp4"
    assert caught.value.reason == "unknown show stem"


def test_episode_is_frozen() -> None:
    episode = parse_filename("Kipper_S01E01.mp4")

    with pytest.raises(FrozenInstanceError):
        setattr(episode, "filename", "other.mp4")


def test_invalid_episode_rejects_empty_filename() -> None:
    with pytest.raises(InvalidEpisodeError):
        Episode(
            filename="",
            show_stem=KIPPER_SHOW_STEM,
            season_number=1,
            episode_number=1,
            title_slug=None,
            daypart=Daypart.GENERAL,
            season_tag=SeasonTag.EVERGREEN,
            holiday_tag=None,
            file_extension="mp4",
        )


def test_invalid_episode_rejects_dotted_extension() -> None:
    with pytest.raises(InvalidEpisodeError):
        Episode(
            filename="Kipper_S01E01.mp4",
            show_stem=KIPPER_SHOW_STEM,
            season_number=1,
            episode_number=1,
            title_slug=None,
            daypart=Daypart.GENERAL,
            season_tag=SeasonTag.EVERGREEN,
            holiday_tag=None,
            file_extension=".mp4",
        )


def test_invalid_episode_rejects_empty_extension() -> None:
    with pytest.raises(InvalidEpisodeError):
        Episode(
            filename="Kipper_S01E01.mp4",
            show_stem=KIPPER_SHOW_STEM,
            season_number=1,
            episode_number=1,
            title_slug=None,
            daypart=Daypart.GENERAL,
            season_tag=SeasonTag.EVERGREEN,
            holiday_tag=None,
            file_extension="",
        )


def test_invalid_episode_rejects_unknown_show_stem() -> None:
    with pytest.raises(InvalidEpisodeError):
        Episode(
            filename="Bluey_S01E01.mp4",
            show_stem="Bluey",
            season_number=1,
            episode_number=1,
            title_slug=None,
            daypart=Daypart.GENERAL,
            season_tag=SeasonTag.EVERGREEN,
            holiday_tag=None,
            file_extension="mp4",
        )


def test_invalid_episode_rejects_cartoon_title_slug() -> None:
    with pytest.raises(InvalidEpisodeError):
        Episode(
            filename="Kipper_S01E01.mp4",
            show_stem=KIPPER_SHOW_STEM,
            season_number=1,
            episode_number=1,
            title_slug="Picnic",
            daypart=Daypart.GENERAL,
            season_tag=SeasonTag.EVERGREEN,
            holiday_tag=None,
            file_extension="mp4",
        )


def test_invalid_episode_rejects_cartoon_without_numbers() -> None:
    with pytest.raises(InvalidEpisodeError):
        Episode(
            filename="Kipper_S01E01.mp4",
            show_stem=KIPPER_SHOW_STEM,
            season_number=None,
            episode_number=None,
            title_slug=None,
            daypart=Daypart.GENERAL,
            season_tag=SeasonTag.EVERGREEN,
            holiday_tag=None,
            file_extension="mp4",
        )


def test_invalid_episode_rejects_cartoon_missing_episode_number() -> None:
    with pytest.raises(InvalidEpisodeError):
        Episode(
            filename="Kipper_S01E01.mp4",
            show_stem=KIPPER_SHOW_STEM,
            season_number=1,
            episode_number=None,
            title_slug=None,
            daypart=Daypart.GENERAL,
            season_tag=SeasonTag.EVERGREEN,
            holiday_tag=None,
            file_extension="mp4",
        )


def test_invalid_episode_rejects_season_number_out_of_range() -> None:
    with pytest.raises(InvalidEpisodeError):
        Episode(
            filename="Kipper_S100E01.mp4",
            show_stem=KIPPER_SHOW_STEM,
            season_number=100,
            episode_number=1,
            title_slug=None,
            daypart=Daypart.GENERAL,
            season_tag=SeasonTag.EVERGREEN,
            holiday_tag=None,
            file_extension="mp4",
        )


def test_invalid_episode_rejects_negative_episode_number() -> None:
    with pytest.raises(InvalidEpisodeError):
        Episode(
            filename="Kipper_S01E00.mp4",
            show_stem=KIPPER_SHOW_STEM,
            season_number=1,
            episode_number=-1,
            title_slug=None,
            daypart=Daypart.GENERAL,
            season_tag=SeasonTag.EVERGREEN,
            holiday_tag=None,
            file_extension="mp4",
        )


def test_invalid_episode_rejects_holiday_without_slug() -> None:
    with pytest.raises(InvalidEpisodeError):
        Episode(
            filename="Holiday_Rudolph.mp4",
            show_stem=HOLIDAY_SHOW_STEM,
            season_number=None,
            episode_number=None,
            title_slug=None,
            daypart=Daypart.GENERAL,
            season_tag=SeasonTag.EVERGREEN,
            holiday_tag=HolidayTag.CHRISTMAS,
            file_extension="mp4",
        )


def test_invalid_episode_rejects_holiday_with_season_numbers() -> None:
    with pytest.raises(InvalidEpisodeError):
        Episode(
            filename="Holiday_Rudolph.mp4",
            show_stem=HOLIDAY_SHOW_STEM,
            season_number=1,
            episode_number=1,
            title_slug="Rudolph",
            daypart=Daypart.GENERAL,
            season_tag=SeasonTag.EVERGREEN,
            holiday_tag=HolidayTag.CHRISTMAS,
            file_extension="mp4",
        )


def test_invalid_episode_rejects_holiday_with_only_episode_number() -> None:
    with pytest.raises(InvalidEpisodeError):
        Episode(
            filename="Holiday_Rudolph.mp4",
            show_stem=HOLIDAY_SHOW_STEM,
            season_number=None,
            episode_number=1,
            title_slug="Rudolph",
            daypart=Daypart.GENERAL,
            season_tag=SeasonTag.EVERGREEN,
            holiday_tag=HolidayTag.CHRISTMAS,
            file_extension="mp4",
        )


def test_invalid_episode_rejects_empty_holiday_slug() -> None:
    with pytest.raises(InvalidEpisodeError):
        Episode(
            filename="Holiday_.mp4",
            show_stem=HOLIDAY_SHOW_STEM,
            season_number=None,
            episode_number=None,
            title_slug="",
            daypart=Daypart.GENERAL,
            season_tag=SeasonTag.EVERGREEN,
            holiday_tag=None,
            file_extension="mp4",
        )


def test_invalid_episode_rejects_holiday_slug_empty_token() -> None:
    with pytest.raises(InvalidEpisodeError):
        Episode(
            filename="Holiday_Rudolph_.mp4",
            show_stem=HOLIDAY_SHOW_STEM,
            season_number=None,
            episode_number=None,
            title_slug="Rudolph_",
            daypart=Daypart.GENERAL,
            season_tag=SeasonTag.EVERGREEN,
            holiday_tag=None,
            file_extension="mp4",
        )
