from dataclasses import replace

from tv90.config import Settings, load_settings
from tv90.domain.filename import parse_filename
from tv90.domain.recency_weight import RECENCY_CLEAR_WEIGHT, RecencyWeight

# Chronological timeline (oldest first). The scheduler appends each airing, so
# the last three items are the recency block and the last ten are the penalty
# window. Slot 01 is the 11th-most-recent file and sits outside both windows.
SLOT_01_OLDEST = parse_filename("LittleBear_S01E01.mp4")
SLOT_02 = parse_filename("LittleBear_S01E02.mp4")
SLOT_03 = parse_filename("LittleBear_S01E03.mp4")
SLOT_04 = parse_filename("LittleBear_S01E04.mp4")
SLOT_05 = parse_filename("LittleBear_S01E05.mp4")
SLOT_06 = parse_filename("LittleBear_S01E06.mp4")
SLOT_07 = parse_filename("LittleBear_S01E07.mp4")
SLOT_08 = parse_filename("LittleBear_S01E08.mp4")
SLOT_09 = parse_filename("LittleBear_S01E09.mp4")
SLOT_10 = parse_filename("LittleBear_S01E10.mp4")
SLOT_11_NEWEST = parse_filename("LittleBear_S01E11.mp4")
UNSEEN_SAME_SHOW = parse_filename("LittleBear_S01E99.mp4")
UNSEEN_OTHER_SHOW = parse_filename("Oswald_S01E01.mp4")

ELEVEN_SLOT_TIMELINE = (
    SLOT_01_OLDEST,
    SLOT_02,
    SLOT_03,
    SLOT_04,
    SLOT_05,
    SLOT_06,
    SLOT_07,
    SLOT_08,
    SLOT_09,
    SLOT_10,
    SLOT_11_NEWEST,
)
CHRONOLOGICAL_FILENAMES = tuple(episode.filename for episode in ELEVEN_SLOT_TIMELINE)
LAST_THREE_BLOCKED = (SLOT_09, SLOT_10, SLOT_11_NEWEST)
LAST_TEN_PENALIZED_ONLY = (
    SLOT_02,
    SLOT_03,
    SLOT_04,
    SLOT_05,
    SLOT_06,
    SLOT_07,
    SLOT_08,
)


def _strategy(settings: Settings | None = None) -> RecencyWeight:
    return RecencyWeight(load_settings({}) if settings is None else settings)


def test_empty_history_is_clear() -> None:
    settings = load_settings({})
    weight = _strategy(settings).weight(SLOT_01_OLDEST, ())

    assert weight == RECENCY_CLEAR_WEIGHT
    assert weight == 1.0


def test_filename_not_in_history_is_clear() -> None:
    strategy = _strategy()

    assert (
        strategy.weight(UNSEEN_SAME_SHOW, CHRONOLOGICAL_FILENAMES)
        == RECENCY_CLEAR_WEIGHT
    )
    assert (
        strategy.weight(UNSEEN_OTHER_SHOW, CHRONOLOGICAL_FILENAMES)
        == RECENCY_CLEAR_WEIGHT
    )


def test_last_three_filenames_are_blocked() -> None:
    settings = load_settings({})
    strategy = RecencyWeight(settings)

    for episode in LAST_THREE_BLOCKED:
        assert strategy.weight(episode, CHRONOLOGICAL_FILENAMES) == (
            settings.recency_block_weight
        )
        assert strategy.weight(episode, CHRONOLOGICAL_FILENAMES) == 0.0


def test_positions_four_through_ten_are_penalized() -> None:
    settings = load_settings({})
    strategy = RecencyWeight(settings)

    for episode in LAST_TEN_PENALIZED_ONLY:
        assert strategy.weight(episode, CHRONOLOGICAL_FILENAMES) == (
            settings.recency_penalty_weight
        )
        assert strategy.weight(episode, CHRONOLOGICAL_FILENAMES) == 0.15


def test_file_only_in_position_eleven_is_clear() -> None:
    settings = load_settings({})
    weight = RecencyWeight(settings).weight(SLOT_01_OLDEST, CHRONOLOGICAL_FILENAMES)

    assert weight == RECENCY_CLEAR_WEIGHT
    assert weight != settings.recency_penalty_weight
    assert weight != settings.recency_block_weight


def test_file_in_last_three_is_blocked_not_merely_penalized() -> None:
    settings = load_settings({})
    strategy = RecencyWeight(settings)

    for episode in LAST_THREE_BLOCKED:
        weight = strategy.weight(episode, CHRONOLOGICAL_FILENAMES)
        assert weight == settings.recency_block_weight
        assert weight != settings.recency_penalty_weight


def test_duplicate_filename_in_last_three_is_blocked() -> None:
    settings = load_settings({})
    history_with_repeat = CHRONOLOGICAL_FILENAMES[:-1] + (SLOT_01_OLDEST.filename,)
    weight = RecencyWeight(settings).weight(SLOT_01_OLDEST, history_with_repeat)

    assert SLOT_01_OLDEST.filename == history_with_repeat[0]
    assert SLOT_01_OLDEST.filename == history_with_repeat[-1]
    assert weight == settings.recency_block_weight


def test_identity_is_filename_not_show() -> None:
    settings = load_settings({})
    strategy = RecencyWeight(settings)
    blocked = strategy.weight(SLOT_11_NEWEST, CHRONOLOGICAL_FILENAMES)
    same_show_unseen = strategy.weight(UNSEEN_SAME_SHOW, CHRONOLOGICAL_FILENAMES)

    assert SLOT_11_NEWEST.show_stem == UNSEEN_SAME_SHOW.show_stem
    assert SLOT_11_NEWEST.filename != UNSEEN_SAME_SHOW.filename
    assert blocked == settings.recency_block_weight
    assert same_show_unseen == RECENCY_CLEAR_WEIGHT


def test_weights_follow_settings_multipliers() -> None:
    settings = replace(
        load_settings({}),
        recency_block_weight=0.01,
        recency_penalty_weight=0.4,
    )
    strategy = RecencyWeight(settings)

    assert (
        strategy.weight(SLOT_11_NEWEST, CHRONOLOGICAL_FILENAMES)
        == settings.recency_block_weight
    )
    assert (
        strategy.weight(SLOT_02, CHRONOLOGICAL_FILENAMES)
        == settings.recency_penalty_weight
    )
    assert (
        strategy.weight(SLOT_01_OLDEST, CHRONOLOGICAL_FILENAMES) == RECENCY_CLEAR_WEIGHT
    )


def test_windows_follow_settings_counts() -> None:
    settings = replace(
        load_settings({}),
        recency_block_count=1,
        recency_penalty_count=2,
    )
    strategy = RecencyWeight(settings)
    short_history = (
        SLOT_01_OLDEST.filename,
        SLOT_02.filename,
        SLOT_03.filename,
    )

    assert strategy.weight(SLOT_03, short_history) == settings.recency_block_weight
    assert strategy.weight(SLOT_02, short_history) == settings.recency_penalty_weight
    assert strategy.weight(SLOT_01_OLDEST, short_history) == RECENCY_CLEAR_WEIGHT


def test_short_history_blocks_every_aired_filename() -> None:
    settings = load_settings({})
    two_slot_history = (SLOT_01_OLDEST.filename, SLOT_02.filename)
    strategy = RecencyWeight(settings)

    assert strategy.weight(SLOT_01_OLDEST, two_slot_history) == (
        settings.recency_block_weight
    )
    assert strategy.weight(SLOT_02, two_slot_history) == settings.recency_block_weight
    assert strategy.weight(UNSEEN_OTHER_SHOW, two_slot_history) == RECENCY_CLEAR_WEIGHT
