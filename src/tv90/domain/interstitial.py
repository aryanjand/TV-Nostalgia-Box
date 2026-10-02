"""Seeded bumper pick. No I/O."""

from __future__ import annotations

import hashlib
import random
from collections.abc import Sequence
from datetime import date
from typing import Literal

SEED_FIELD_SEPARATOR = "|"
CLOCK_HOUR_DECIMAL_PLACES = 6
SEED_TEXT_ENCODING = "utf-8"
SEED_BYTE_ORDER: Literal["big"] = "big"


def interstitial_pick_seed(
    on_date: date, channel_number: int, clock_hour: float
) -> int:
    canonical_hour = format(clock_hour, f".{CLOCK_HOUR_DECIMAL_PLACES}f")
    payload = (
        f"{on_date.isoformat()}{SEED_FIELD_SEPARATOR}{channel_number}"
        f"{SEED_FIELD_SEPARATOR}{canonical_hour}"
    )
    digest = hashlib.sha256(payload.encode(SEED_TEXT_ENCODING)).digest()
    return int.from_bytes(digest, SEED_BYTE_ORDER)


def pick_interstitial(
    candidates: Sequence[str],
    *,
    seed: int,
    recently_played: Sequence[str],
) -> str | None:
    if not candidates:
        return None
    pool = _pool_skipping_last_if_possible(candidates, recently_played)
    return random.Random(seed).choice(pool)


def _pool_skipping_last_if_possible(
    candidates: Sequence[str], recently_played: Sequence[str]
) -> list[str]:
    if not recently_played:
        return list(candidates)
    last_played = recently_played[-1]
    without_last = [name for name in candidates if name != last_played]
    if without_last:
        return without_last
    return list(candidates)
