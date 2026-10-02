"""Emit one day's airing fingerprint for a cross-process determinism check."""

from datetime import date

from tv90.adapters.fake_duration import FakeDurationIndex
from tv90.config import KIPPER_CHANNEL_NUMBER, load_settings
from tv90.domain.filename import parse_filename
from tv90.domain.holiday_calendar import HolidayCalendar
from tv90.domain.timeline import DailyTimelineBuilder, Timeline

FINGERPRINT_DATE = date(1994, 7, 15)
FINGERPRINT_DURATION_SECONDS = 1800.0
FINGERPRINT_POOL = (
    parse_filename("Kipper_S01E01.mp4"),
    parse_filename("Kipper_S01E02_MORNING.mp4"),
    parse_filename("Kipper_S01E03_NIGHT.mp4"),
    parse_filename("Kipper_S01E04.mp4"),
    parse_filename("Kipper_S01E05.mp4"),
)


def fingerprint_text(timeline: Timeline) -> str:
    return ",".join(
        f"{slot.start_hour:.6f}:{slot.episode.filename}" for slot in timeline.slots
    )


def build_fingerprint_timeline() -> Timeline:
    settings = load_settings({})
    durations = {
        episode.filename: FINGERPRINT_DURATION_SECONDS for episode in FINGERPRINT_POOL
    }
    builder = DailyTimelineBuilder(
        settings,
        HolidayCalendar.from_defaults(settings),
        FakeDurationIndex(durations),
    )
    return builder.build(FINGERPRINT_DATE, KIPPER_CHANNEL_NUMBER, FINGERPRINT_POOL)


if __name__ == "__main__":
    print(fingerprint_text(build_fingerprint_timeline()), end="")
