import hashlib
import os
import subprocess
import sys
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import FrozenInstanceError, replace
from datetime import date, timedelta
from pathlib import Path

import pytest

from timeline_fingerprint_script import (
    FINGERPRINT_DATE,
    FINGERPRINT_POOL,
    build_fingerprint_timeline,
    fingerprint_text,
)
from tv90.adapters.fake_duration import FakeDurationIndex
from tv90.config import (
    HOLIDAY_CHANNEL_NUMBER,
    LITTLE_BEAR_CHANNEL_NUMBER,
    LITTLE_BEAR_SHOW_STEM,
    OSWALD_CHANNEL_NUMBER,
    OSWALD_SHOW_STEM,
    Settings,
    load_settings,
)
from tv90.domain.duration import DurationUnknownError
from tv90.domain.episode import Daypart, Episode
from tv90.domain.filename import parse_filename
from tv90.domain.holiday_calendar import HolidayCalendar
from tv90.domain.timeline import (
    SECONDS_PER_HOUR,
    SLOT_START_HOUR_DECIMAL_PLACES,
    DailyTimelineBuilder,
    Slot,
    Timeline,
    UnfillableTimelineSlotError,
    slot_seed_payload,
    slot_selection_seed,
)

JULY_FIFTEENTH = date(1994, 7, 15)
HALF_HOUR_SECONDS = 1800.0
FOUR_HOUR_SECONDS = 4 * SECONDS_PER_HOUR
GENERAL_DAYPART_EPISODE_COUNT = 10
MORNING_DAYPART_EPISODE_COUNT = 5
NIGHT_DAYPART_EPISODE_COUNT = 5
MORNING_DAYPART_FIRST_EPISODE = 11
NIGHT_DAYPART_FIRST_EPISODE = 21
TINY_POOL = (
    parse_filename("LittleBear_S01E01.mp4"),
    parse_filename("LittleBear_S01E02.mp4"),
)
LONG_MOVIE_POOL = (
    parse_filename("Holiday_Rudolph_CHRISTMAS.mp4"),
    parse_filename("Holiday_Frosty_CHRISTMAS.mp4"),
)
OSWALD_POOL = (
    parse_filename("Oswald_S01E01.mp4"),
    parse_filename("Oswald_S01E02.mp4"),
    parse_filename("Oswald_S01E03.mp4"),
    parse_filename("Oswald_S01E04.mp4"),
    parse_filename("Oswald_S01E05.mp4"),
)
LARGE_POOL_EPISODE_COUNT = 20
SIMULATION_START_DATE = date(1994, 6, 15)
SIMULATION_DAY_COUNT = 80
MORNING_SHARE_FLOOR = 0.40
EVENING_NIGHT_SHARE_FLOOR = 0.35
MIDDAY_GENERAL_SHARE_FLOOR = 0.55
MIDDAY_MORNING_SHARE_CEILING = 0.20
MIDDAY_GENERAL_MAX_MIN_RATIO = 2.5
PROJECT_ROOT = Path(__file__).resolve().parents[1]
FINGERPRINT_SCRIPT = Path(__file__).resolve().parent / "timeline_fingerprint_script.py"
SRC_PATH = PROJECT_ROOT / "src"


def _large_pool() -> tuple[Episode, ...]:
    return tuple(
        parse_filename(f"LittleBear_S01E{episode_number:02d}.mp4")
        for episode_number in range(1, LARGE_POOL_EPISODE_COUNT + 1)
    )


def _daypart_pool() -> tuple[Episode, ...]:
    generals = tuple(
        parse_filename(f"LittleBear_S01E{episode_number:02d}.mp4")
        for episode_number in range(1, GENERAL_DAYPART_EPISODE_COUNT + 1)
    )
    mornings = tuple(
        parse_filename(f"LittleBear_S01E{episode_number:02d}_MORNING.mp4")
        for episode_number in range(
            MORNING_DAYPART_FIRST_EPISODE,
            MORNING_DAYPART_FIRST_EPISODE + MORNING_DAYPART_EPISODE_COUNT,
        )
    )
    nights = tuple(
        parse_filename(f"LittleBear_S01E{episode_number:02d}_NIGHT.mp4")
        for episode_number in range(
            NIGHT_DAYPART_FIRST_EPISODE,
            NIGHT_DAYPART_FIRST_EPISODE + NIGHT_DAYPART_EPISODE_COUNT,
        )
    )
    # Generals first so always-picking the first file fails the morning skew.
    return generals + mornings + nights


def _durations(pool: Sequence[Episode], duration_seconds: float) -> dict[str, float]:
    return {episode.filename: duration_seconds for episode in pool}


def _builder(
    pool: Sequence[Episode],
    durations: Mapping[str, float] | None = None,
    settings: Settings | None = None,
) -> DailyTimelineBuilder:
    resolved_settings = load_settings({}) if settings is None else settings
    duration_map = (
        dict(durations)
        if durations is not None
        else _durations(pool, HALF_HOUR_SECONDS)
    )
    return DailyTimelineBuilder(
        resolved_settings,
        HolidayCalendar.from_defaults(resolved_settings),
        FakeDurationIndex(duration_map),
    )


def _build(
    pool: Sequence[Episode],
    on_date: date = JULY_FIFTEENTH,
    channel_number: int = LITTLE_BEAR_CHANNEL_NUMBER,
    durations: Mapping[str, float] | None = None,
    settings: Settings | None = None,
) -> Timeline:
    return _builder(pool, durations, settings).build(on_date, channel_number, pool)


def test_slot_and_timeline_are_frozen() -> None:
    episode = TINY_POOL[0]
    slot = Slot.starting_at(episode, 6.5, HALF_HOUR_SECONDS)
    timeline = Timeline(JULY_FIFTEENTH, LITTLE_BEAR_CHANNEL_NUMBER, (slot,))

    with pytest.raises(FrozenInstanceError):
        setattr(slot, "start_hour", 7.0)
    with pytest.raises(FrozenInstanceError):
        setattr(timeline, "slots", ())


def test_slot_end_hour_is_start_plus_duration_in_hours() -> None:
    slot = Slot.starting_at(TINY_POOL[0], 6.5, HALF_HOUR_SECONDS)

    assert SECONDS_PER_HOUR == 3600
    assert slot.end_hour == 6.5 + HALF_HOUR_SECONDS / SECONDS_PER_HOUR
    assert slot.end_hour == 7.0


def test_seed_payload_canonicalizes_trailing_zeros() -> None:
    expected = "1994-07-15|1|6.500000"

    assert slot_seed_payload(JULY_FIFTEENTH, 1, 6.5) == expected
    assert slot_seed_payload(JULY_FIFTEENTH, 1, 6.50) == expected
    assert SLOT_START_HOUR_DECIMAL_PLACES == 6


def test_seed_is_sha256_of_payload_as_big_endian_int() -> None:
    payload = slot_seed_payload(JULY_FIFTEENTH, 1, 6.5)
    digest = hashlib.sha256(payload.encode("utf-8")).digest()

    assert slot_selection_seed(JULY_FIFTEENTH, 1, 6.5) == int.from_bytes(digest, "big")
    assert slot_selection_seed(JULY_FIFTEENTH, 1, 6.5) == slot_selection_seed(
        JULY_FIFTEENTH, 1, 6.50
    )
    assert slot_selection_seed(JULY_FIFTEENTH, 1, 6.5) != slot_selection_seed(
        JULY_FIFTEENTH, 2, 6.5
    )


def test_empty_pool_returns_an_empty_timeline() -> None:
    timeline = _build(())

    assert timeline.slots == ()
    assert timeline.date == JULY_FIFTEENTH
    assert timeline.channel_number == LITTLE_BEAR_CHANNEL_NUMBER


def test_first_slot_starts_at_sign_on_and_none_start_at_or_after_night_lock() -> None:
    settings = load_settings({})
    timeline = _build(_large_pool(), settings=settings)

    assert timeline.slots[0].start_hour == settings.sign_on_hour
    for slot in timeline.slots:
        assert slot.start_hour < settings.night_lock_hour
    assert timeline.slots[-1].end_hour >= settings.night_lock_hour


def test_slots_are_contiguous() -> None:
    timeline = _build(TINY_POOL)

    for previous, current in zip(timeline.slots, timeline.slots[1:], strict=False):
        assert current.start_hour == previous.end_hour


def test_a_slot_may_start_before_night_lock_and_extend_past_it() -> None:
    settings = load_settings({})
    timeline = _build(
        LONG_MOVIE_POOL,
        channel_number=HOLIDAY_CHANNEL_NUMBER,
        durations=_durations(LONG_MOVIE_POOL, FOUR_HOUR_SECONDS),
        settings=settings,
    )
    last_slot = timeline.slots[-1]

    assert last_slot.start_hour < settings.night_lock_hour
    assert last_slot.end_hour > settings.night_lock_hour
    assert last_slot.duration_seconds == FOUR_HOUR_SECONDS


def test_nothing_airs_before_sign_on() -> None:
    settings = replace(load_settings({}), sign_on_hour=7.0, night_lock_hour=21.0)
    timeline = _build(TINY_POOL, settings=settings)

    assert timeline.slots[0].start_hour == 7.0
    assert all(slot.start_hour >= settings.sign_on_hour for slot in timeline.slots)


def test_same_date_and_channel_twice_yields_the_identical_timeline() -> None:
    pool = _large_pool()
    first = _build(pool)
    second = _build(pool)

    assert first == second
    assert tuple(slot.episode.filename for slot in first.slots) == tuple(
        slot.episode.filename for slot in second.slots
    )


def test_hashlib_seed_is_stable_across_processes() -> None:
    in_process = fingerprint_text(build_fingerprint_timeline())
    fingerprints = [
        _fingerprint_in_subprocess(hash_seed) for hash_seed in ("0", "1", "random")
    ]

    assert in_process == fingerprints[0]
    assert fingerprints[0] == fingerprints[1] == fingerprints[2]
    assert in_process != ""
    assert FINGERPRINT_DATE == date(1994, 7, 15)
    assert len(FINGERPRINT_POOL) == 5


def test_missing_duration_is_not_swallowed() -> None:
    pool = (parse_filename("LittleBear_S01E01.mp4"),)
    builder = DailyTimelineBuilder(
        load_settings({}),
        HolidayCalendar.from_defaults(load_settings({})),
        FakeDurationIndex({}),
    )

    with pytest.raises(DurationUnknownError) as caught:
        builder.build(JULY_FIFTEENTH, LITTLE_BEAR_CHANNEL_NUMBER, pool)

    assert caught.value.filename == pool[0].filename


def test_large_pool_does_not_repeat_the_recency_block() -> None:
    settings = load_settings({})
    timeline = _build(_large_pool(), settings=settings)
    block_count = settings.recency_block_count

    assert len(_large_pool()) > block_count
    for position in range(block_count, len(timeline.slots)):
        blocked = {
            timeline.slots[position - offset].episode.filename
            for offset in range(1, block_count + 1)
        }
        assert timeline.slots[position].episode.filename not in blocked


def test_tiny_library_fills_until_lock_and_may_repeat_after_relaxation() -> None:
    settings = load_settings({})
    timeline = _build(TINY_POOL, settings=settings)
    filenames = [slot.episode.filename for slot in timeline.slots]

    assert len(timeline.slots) > len(TINY_POOL)
    assert timeline.slots[-1].end_hour >= settings.night_lock_hour
    assert set(filenames) == {episode.filename for episode in TINY_POOL}
    assert max(filenames.count(episode.filename) for episode in TINY_POOL) > 1


def test_zero_recency_weights_still_fill_the_broadcast_day() -> None:
    settings = replace(
        load_settings({}),
        recency_block_weight=0.0,
        recency_penalty_weight=0.0,
    )
    timeline = _build(TINY_POOL, settings=settings)

    assert timeline.slots
    assert timeline.slots[0].start_hour == settings.sign_on_hour
    assert timeline.slots[-1].end_hour >= settings.night_lock_hour


def test_zero_time_weights_still_pick_a_playable_file() -> None:
    settings = replace(
        load_settings({}),
        general_midday_weight=0.0,
        general_off_peak_weight=0.0,
        time_weight_floor=0.0,
    )
    timeline = _build(TINY_POOL, settings=settings)

    assert timeline.slots
    assert {slot.episode.filename for slot in timeline.slots} <= {
        episode.filename for episode in TINY_POOL
    }


def test_pick_without_recency_raises_when_the_pool_is_empty() -> None:
    builder = _builder(())

    with pytest.raises(UnfillableTimelineSlotError) as caught:
        builder.pick_without_recency(
            (), JULY_FIFTEENTH, LITTLE_BEAR_CHANNEL_NUMBER, 6.5
        )

    assert caught.value.on_date == JULY_FIFTEENTH
    assert caught.value.channel_number == LITTLE_BEAR_CHANNEL_NUMBER
    assert caught.value.slot_start_hour == 6.5


def test_oswald_pool_never_emits_little_bear() -> None:
    timeline = _build(OSWALD_POOL, channel_number=OSWALD_CHANNEL_NUMBER)

    assert timeline.slots
    for slot in timeline.slots:
        assert slot.episode.show_stem != LITTLE_BEAR_SHOW_STEM
        assert slot.episode.show_stem == OSWALD_SHOW_STEM


def test_mornings_skew_to_morning_files_and_evenings_to_night() -> None:
    pool = _daypart_pool()
    settings = load_settings({})
    builder = _builder(pool, settings=settings)
    morning_slots: list[Slot] = []
    evening_slots: list[Slot] = []
    midday_slots: list[Slot] = []

    for day_offset in range(SIMULATION_DAY_COUNT):
        on_date = SIMULATION_START_DATE + timedelta(days=day_offset)
        timeline = builder.build(on_date, LITTLE_BEAR_CHANNEL_NUMBER, pool)
        for slot in timeline.slots:
            if slot.start_hour < settings.general_midday_start_hour:
                morning_slots.append(slot)
            elif slot.start_hour < settings.general_midday_end_hour:
                midday_slots.append(slot)
            else:
                evening_slots.append(slot)

    morning_morning_share = _daypart_share(morning_slots, Daypart.MORNING)
    evening_night_share = _daypart_share(evening_slots, Daypart.NIGHT)
    midday_general_share = _daypart_share(midday_slots, Daypart.GENERAL)
    midday_morning_share = _daypart_share(midday_slots, Daypart.MORNING)

    assert morning_morning_share >= MORNING_SHARE_FLOOR
    assert evening_night_share >= EVENING_NIGHT_SHARE_FLOOR
    assert midday_general_share >= MIDDAY_GENERAL_SHARE_FLOOR
    assert midday_morning_share <= MIDDAY_MORNING_SHARE_CEILING
    _assert_midday_generals_are_roughly_uniform(midday_slots, pool)


def _daypart_share(slots: Sequence[Slot], daypart: Daypart) -> float:
    return sum(slot.episode.daypart is daypart for slot in slots) / len(slots)


def _assert_midday_generals_are_roughly_uniform(
    midday_slots: Sequence[Slot], pool: Sequence[Episode]
) -> None:
    general_filenames = tuple(
        episode.filename for episode in pool if episode.daypart is Daypart.GENERAL
    )
    midday_general_filenames = [
        slot.episode.filename
        for slot in midday_slots
        if slot.episode.daypart is Daypart.GENERAL
    ]
    counts = Counter(midday_general_filenames)
    counted = [counts[filename] for filename in general_filenames]

    assert min(counted) > 0
    assert max(counted) / min(counted) < MIDDAY_GENERAL_MAX_MIN_RATIO


def _fingerprint_in_subprocess(python_hash_seed: str) -> str:
    environment = dict(os.environ)
    environment["PYTHONHASHSEED"] = python_hash_seed
    environment["PYTHONPATH"] = str(SRC_PATH)
    completed = subprocess.run(
        [sys.executable, str(FINGERPRINT_SCRIPT)],
        check=True,
        capture_output=True,
        text=True,
        env=environment,
        cwd=str(PROJECT_ROOT),
    )
    return completed.stdout
