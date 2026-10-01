import random
from dataclasses import replace

import pytest

from tv90.config import load_settings
from tv90.domain.episode import SeasonTag
from tv90.domain.filename import parse_filename
from tv90.domain.season_weight import (
    InvalidMonthError,
    SeasonWeight,
    month_to_season,
)

SPRING_EPISODE = parse_filename("LittleBear_S01E01_SPRING.mp4")
SUMMER_EPISODE = parse_filename("LittleBear_S01E02_SUMMER.mp4")
AUTUMN_EPISODE = parse_filename("LittleBear_S01E03_AUTUMN.mp4")
WINTER_EPISODE = parse_filename("LittleBear_S01E04_WINTER.mp4")
EVERGREEN_EPISODE = parse_filename("Oswald_S01E09.mp4")
HOLIDAY_EVERGREEN_EPISODE = parse_filename("Holiday_Rudolph_CHRISTMAS.mp4")
CHRISTMAS_WINTER_CARTOON = parse_filename("Harry_S01E01_WINTER_CHRISTMAS.mp4")

JANUARY = 1
APRIL = 4
JULY = 7
OCTOBER = 10
DECEMBER = 12

# Band around the 80% in-season share on a 1:1:1 mix. Tight enough that equal
# weights (~33%) fail, wide enough that a seeded 20_000-draw binomial at p=0.8
# stays inside.
IN_SEASON_SHARE_FLOOR = 0.76
IN_SEASON_SHARE_CEILING = 0.84
BALANCED_MIX_IN_SEASON_SHARE = 0.8
SIMULATION_DRAW_COUNT = 20_000
SIMULATION_SEED = 1990


def _strategy() -> SeasonWeight:
    return SeasonWeight(load_settings({}))


@pytest.mark.parametrize(
    ("month", "expected_season"),
    [
        (1, SeasonTag.WINTER),
        (2, SeasonTag.WINTER),
        (3, SeasonTag.SPRING),
        (4, SeasonTag.SPRING),
        (5, SeasonTag.SPRING),
        (6, SeasonTag.SUMMER),
        (7, SeasonTag.SUMMER),
        (8, SeasonTag.SUMMER),
        (9, SeasonTag.AUTUMN),
        (10, SeasonTag.AUTUMN),
        (11, SeasonTag.AUTUMN),
        (12, SeasonTag.WINTER),
    ],
)
def test_month_to_season_maps_every_calendar_month(
    month: int, expected_season: SeasonTag
) -> None:
    assert month_to_season(month) is expected_season
    assert month_to_season(month) is not SeasonTag.EVERGREEN


def test_spring_file_in_april_is_in_season() -> None:
    settings = load_settings({})

    assert SeasonWeight(settings).weight(SPRING_EPISODE, APRIL) == (
        settings.in_season_weight
    )


def test_summer_file_in_july_is_in_season() -> None:
    settings = load_settings({})

    assert (
        SeasonWeight(settings).weight(SUMMER_EPISODE, JULY) == settings.in_season_weight
    )


def test_autumn_file_in_october_is_in_season() -> None:
    settings = load_settings({})

    assert (
        SeasonWeight(settings).weight(AUTUMN_EPISODE, OCTOBER)
        == settings.in_season_weight
    )


def test_winter_file_in_january_is_in_season() -> None:
    settings = load_settings({})

    assert (
        SeasonWeight(settings).weight(WINTER_EPISODE, JANUARY)
        == settings.in_season_weight
    )


def test_winter_file_in_july_is_wrong_season_not_zero() -> None:
    settings = load_settings({})
    weight = SeasonWeight(settings).weight(WINTER_EPISODE, JULY)

    assert weight == settings.wrong_season_weight
    assert weight > 0
    assert weight < settings.in_season_weight
    assert weight < settings.evergreen_season_weight


def test_spring_file_in_july_is_wrong_season() -> None:
    settings = load_settings({})

    assert (
        SeasonWeight(settings).weight(SPRING_EPISODE, JULY)
        == settings.wrong_season_weight
    )


@pytest.mark.parametrize("month", [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12])
def test_evergreen_file_uses_evergreen_weight_in_every_month(month: int) -> None:
    settings = load_settings({})

    assert (
        SeasonWeight(settings).weight(EVERGREEN_EPISODE, month)
        == settings.evergreen_season_weight
    )


def test_holiday_movie_without_season_tag_is_evergreen() -> None:
    settings = load_settings({})
    strategy = SeasonWeight(settings)

    assert strategy.weight(HOLIDAY_EVERGREEN_EPISODE, JULY) == (
        settings.evergreen_season_weight
    )
    assert strategy.weight(HOLIDAY_EVERGREEN_EPISODE, DECEMBER) == (
        settings.evergreen_season_weight
    )


def test_holiday_tag_does_not_change_season_weight() -> None:
    settings = load_settings({})

    assert SeasonWeight(settings).weight(CHRISTMAS_WINTER_CARTOON, JULY) == (
        settings.wrong_season_weight
    )
    assert SeasonWeight(settings).weight(CHRISTMAS_WINTER_CARTOON, JANUARY) == (
        settings.in_season_weight
    )


def test_weights_follow_settings_multipliers() -> None:
    settings = replace(
        load_settings({}),
        in_season_weight=0.9,
        evergreen_season_weight=0.3,
        wrong_season_weight=0.1,
    )
    strategy = SeasonWeight(settings)

    assert strategy.weight(SPRING_EPISODE, APRIL) == settings.in_season_weight
    assert strategy.weight(EVERGREEN_EPISODE, JULY) == settings.evergreen_season_weight
    assert strategy.weight(WINTER_EPISODE, JULY) == settings.wrong_season_weight


@pytest.mark.parametrize("month", [0, 13, -1])
def test_invalid_month_raises(month: int) -> None:
    with pytest.raises(InvalidMonthError) as mapping_error:
        month_to_season(month)
    assert mapping_error.value.month == month

    with pytest.raises(InvalidMonthError) as weight_error:
        _strategy().weight(EVERGREEN_EPISODE, month)
    assert weight_error.value.month == month


def test_balanced_mix_in_season_share_is_algebraically_eighty_percent() -> None:
    settings = load_settings({})
    total_weight = (
        settings.in_season_weight
        + settings.evergreen_season_weight
        + settings.wrong_season_weight
    )

    assert settings.wrong_season_weight > 0
    assert settings.in_season_weight != settings.evergreen_season_weight
    assert settings.in_season_weight / total_weight == pytest.approx(
        BALANCED_MIX_IN_SEASON_SHARE
    )


def test_balanced_mix_simulation_airs_in_season_about_eighty_percent() -> None:
    settings = load_settings({})
    strategy = SeasonWeight(settings)
    pool = (SUMMER_EPISODE, EVERGREEN_EPISODE, WINTER_EPISODE)
    weights = tuple(strategy.weight(episode, JULY) for episode in pool)
    in_season_weight, evergreen_weight, wrong_season_weight = weights

    # Weights must be the named Settings multipliers. Equal weights or a zero
    # wrong-season weight would still let a 0.76–0.84 band pass in some cases.
    assert in_season_weight == settings.in_season_weight
    assert evergreen_weight == settings.evergreen_season_weight
    assert wrong_season_weight == settings.wrong_season_weight
    assert wrong_season_weight > 0
    assert in_season_weight != evergreen_weight

    rng = random.Random(SIMULATION_SEED)
    chosen = rng.choices(pool, weights=weights, k=SIMULATION_DRAW_COUNT)
    in_season_count = sum(episode is SUMMER_EPISODE for episode in chosen)
    wrong_season_count = sum(episode is WINTER_EPISODE for episode in chosen)
    in_season_share = in_season_count / SIMULATION_DRAW_COUNT

    assert IN_SEASON_SHARE_FLOOR <= in_season_share <= IN_SEASON_SHARE_CEILING
    assert wrong_season_count > 0
