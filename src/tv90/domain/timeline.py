"""Seeded daily timeline from sign-on until night lock. No I/O."""

from __future__ import annotations

import hashlib
import random
from collections.abc import Sequence
from dataclasses import dataclass, replace
from datetime import date
from typing import Literal

from tv90.config import Settings
from tv90.domain.combined_weight import CombinedWeight
from tv90.domain.episode import Episode
from tv90.domain.holiday_calendar import HolidayCalendar
from tv90.ports.duration import DurationIndex

SECONDS_PER_HOUR = 3600
SEED_FIELD_SEPARATOR = "|"
SLOT_START_HOUR_DECIMAL_PLACES = 6
SEED_TEXT_ENCODING = "utf-8"
SEED_BYTE_ORDER: Literal["big"] = "big"
EQUAL_CANDIDATE_WEIGHT = 1.0


class UnfillableTimelineSlotError(Exception):
    """The pool is empty, so a slot cannot be filled."""

    def __init__(
        self, on_date: date, channel_number: int, slot_start_hour: float
    ) -> None:
        self.on_date = on_date
        self.channel_number = channel_number
        self.slot_start_hour = slot_start_hour
        super().__init__(
            f"no playable file for channel {channel_number} on {on_date.isoformat()} "
            f"at {slot_start_hour}"
        )


def slot_seed_payload(
    on_date: date, channel_number: int, slot_start_hour: float
) -> str:
    # Fixed decimal places so 6.5 and 6.50 are the same hashlib input.
    canonical_hour = format(slot_start_hour, f".{SLOT_START_HOUR_DECIMAL_PLACES}f")
    return (
        f"{on_date.isoformat()}{SEED_FIELD_SEPARATOR}{channel_number}"
        f"{SEED_FIELD_SEPARATOR}{canonical_hour}"
    )


def slot_selection_seed(
    on_date: date, channel_number: int, slot_start_hour: float
) -> int:
    # SHA-256 of the payload, then big-endian int. Python hash() is per-process.
    payload = slot_seed_payload(on_date, channel_number, slot_start_hour)
    digest = hashlib.sha256(payload.encode(SEED_TEXT_ENCODING)).digest()
    return int.from_bytes(digest, SEED_BYTE_ORDER)


@dataclass(frozen=True)
class Slot:
    episode: Episode
    start_hour: float
    duration_seconds: float
    end_hour: float

    @classmethod
    def starting_at(
        cls,
        episode: Episode,
        start_hour: float,
        duration_seconds: float,
    ) -> Slot:
        return cls(
            episode=episode,
            start_hour=start_hour,
            duration_seconds=duration_seconds,
            end_hour=start_hour + duration_seconds / SECONDS_PER_HOUR,
        )


@dataclass(frozen=True)
class Timeline:
    date: date
    channel_number: int
    slots: tuple[Slot, ...]


class DailyTimelineBuilder:
    def __init__(
        self,
        settings: Settings,
        holiday_calendar: HolidayCalendar,
        duration_index: DurationIndex,
    ) -> None:
        self._settings = settings
        self._holiday_calendar = holiday_calendar
        self._duration_index = duration_index

    def build(
        self,
        on_date: date,
        channel_number: int,
        episode_pool: Sequence[Episode],
    ) -> Timeline:
        if not episode_pool:
            # T12 holds the slate when a channel has nothing to air.
            return Timeline(date=on_date, channel_number=channel_number, slots=())

        slots: list[Slot] = []
        slot_start_hour = self._settings.sign_on_hour
        while slot_start_hour < self._settings.night_lock_hour:
            recently_aired = tuple(slot.episode.filename for slot in slots)
            episode = self._pick_episode(
                episode_pool,
                on_date,
                channel_number,
                slot_start_hour,
                recently_aired,
            )
            duration_seconds = self._duration_index.duration_seconds(episode.filename)
            slot = Slot.starting_at(episode, slot_start_hour, duration_seconds)
            slots.append(slot)
            # A slot may start before lock and run past it; playback cuts it off.
            slot_start_hour = slot.end_hour
        return Timeline(date=on_date, channel_number=channel_number, slots=tuple(slots))

    def pick_with_recency(
        self,
        episode_pool: Sequence[Episode],
        on_date: date,
        channel_number: int,
        slot_start_hour: float,
        recently_aired_filenames: Sequence[str],
    ) -> Episode | None:
        return self._pick_positive_weight(
            CombinedWeight(self._settings, self._holiday_calendar, channel_number),
            episode_pool,
            on_date,
            channel_number,
            slot_start_hour,
            recently_aired_filenames,
        )

    def pick_without_block(
        self,
        episode_pool: Sequence[Episode],
        on_date: date,
        channel_number: int,
        slot_start_hour: float,
        recently_aired_filenames: Sequence[str],
    ) -> Episode | None:
        # Last-3 files keep the penalty magnitude instead of a hard zero.
        relaxed_settings = replace(
            self._settings,
            recency_block_weight=self._settings.recency_penalty_weight,
        )
        return self._pick_positive_weight(
            CombinedWeight(relaxed_settings, self._holiday_calendar, channel_number),
            episode_pool,
            on_date,
            channel_number,
            slot_start_hour,
            recently_aired_filenames,
        )

    def pick_without_recency(
        self,
        episode_pool: Sequence[Episode],
        on_date: date,
        channel_number: int,
        slot_start_hour: float,
    ) -> Episode:
        chosen = self._pick_positive_weight(
            CombinedWeight(self._settings, self._holiday_calendar, channel_number),
            episode_pool,
            on_date,
            channel_number,
            slot_start_hour,
            (),
        )
        if chosen is not None:
            return chosen
        seed = slot_selection_seed(on_date, channel_number, slot_start_hour)
        equal_weights = tuple(
            (episode, EQUAL_CANDIDATE_WEIGHT) for episode in episode_pool
        )
        equal_choice = _choose_weighted_episode(equal_weights, seed)
        if equal_choice is None:
            raise UnfillableTimelineSlotError(on_date, channel_number, slot_start_hour)
        return equal_choice

    def _pick_episode(
        self,
        episode_pool: Sequence[Episode],
        on_date: date,
        channel_number: int,
        slot_start_hour: float,
        recently_aired_filenames: Sequence[str],
    ) -> Episode:
        chosen = self.pick_with_recency(
            episode_pool,
            on_date,
            channel_number,
            slot_start_hour,
            recently_aired_filenames,
        )
        if chosen is not None:
            return chosen
        chosen = self.pick_without_block(
            episode_pool,
            on_date,
            channel_number,
            slot_start_hour,
            recently_aired_filenames,
        )
        if chosen is not None:
            return chosen
        return self.pick_without_recency(
            episode_pool, on_date, channel_number, slot_start_hour
        )

    def _pick_positive_weight(
        self,
        combined_weight: CombinedWeight,
        episode_pool: Sequence[Episode],
        on_date: date,
        channel_number: int,
        slot_start_hour: float,
        recently_aired_filenames: Sequence[str],
    ) -> Episode | None:
        episode_weights = tuple(
            (
                episode,
                combined_weight.weight(
                    episode, slot_start_hour, on_date, recently_aired_filenames
                ),
            )
            for episode in episode_pool
        )
        seed = slot_selection_seed(on_date, channel_number, slot_start_hour)
        return _choose_weighted_episode(episode_weights, seed)


def _choose_weighted_episode(
    episode_weights: Sequence[tuple[Episode, float]], seed: int
) -> Episode | None:
    positive = tuple(
        (episode, weight) for episode, weight in episode_weights if weight > 0
    )
    if not positive:
        return None
    seeded_random = random.Random(seed)
    population = [episode for episode, _weight in positive]
    weights = [weight for _episode, weight in positive]
    chosen = seeded_random.choices(population, weights=weights, k=1)
    return chosen[0]
