# Decisions

Already-made choices. Do not reopen them without a new requirement.

- **Web framework: Flask.** The remote is a small LAN page; Flask matches that scope and is the agreed framework (not FastAPI).
- **Timezone: local time from a configurable zone, default America/Vancouver.** The box is meant for a Canadian household; env can override the zone without a code edit.
- **Seeding: hashlib of date, channel, and slot start time.** Python's `hash()` is not stable across processes, so a reboot would retune the day's airings.
- **Timeline purity: a day's timeline is a pure function of date, channel, library contents, and configuration.** Recency is computed from the timeline being built, never from persisted play history, so a pulled plug cannot change what airs.
- **Empty weights: relax the recency block first, then the penalty.** A slot is never left empty while the show has any playable file.
- **Season weight: named per-file multipliers (in-season highest, season-evergreen lower, wrong-season small but non-zero).** Tuned so in-season episodes take roughly 80% of airings when the library has a balanced mix; verify later with a simulation test.
- **Holiday windows: CH 04 opens HOLIDAY_LEAD_DAYS (default 3) before the first event day and closes at the end of the last event day.** Christmas event days are Dec 24 and 25.
- **Layer A multiplier: ramps linearly from 1.25 at 14 days out to 1.50 on event days.** Outside the lead-up, holiday-tagged cartoon episodes are down-weighted like wrong-season episodes.
- **CH 04: same timeline builder with its pool limited to the active holiday's movies.** Time weight is fixed at 1 unless a movie carries a daypart tag.
- **Night lock: an episode may start before 21:00 and be cut off.** At 21:00 the TV goes to standby and input is ignored until sign-on. Outside the broadcast day the player holds the slate.
- **Channel down wraps in the mirror order of channel up.** Surfing either direction visits the same lineup.
- **Volume resets to a configured default on every start.** Nothing is saved, so a power cycle must not remember the last level.
- **setup.sh installs ffmpeg and cec-utils in addition to packages the README lists.** It enables network time sync and does not configure an outbound firewall.
- **Runtime writes: none while the TV service runs.** Power-cut safety requires a read-only card; logs go to a volatile journal.
- **Metadata source for the tagger: deferred to T14.** T14 must confirm coverage of Little Bear, Oswald, and Harry and His Bucket Full of Dinosaurs before building on a source.

## Toolchain (T0)

- **Build backend: hatchling.** Src-layout discovery is first-class and we have no setup.py.
- **Python 3.11 via `.python-version` and a uv-managed `.venv`.** The project targets 3.11; this machine's Homebrew interpreter is newer, so uv provisions CPython 3.11.15 locally.
- **Coverage: `--cov=tv90.domain --cov=tv90.application --cov-branch --cov-fail-under=90`.** Domain and application are empty at T0 (0 statements); coverage.py reports that as 100%, so the threshold stays at 90 without omitting packages.
- **Makefile `check` invokes tools from `.venv/bin`.** `make check` does not depend on an already-activated shell.
- **Ruff selects E, F, I, UP.** A small baseline until later tasks need more rules.
- **Flask is pinned `>=3.0,<4` and is the only runtime dependency.** Unused libraries stay out of the runtime extra.

## T1

- **Sign-on and night lock are overridable** via `TV90_SIGN_ON` and `TV90_NIGHT_LOCK` as decimal hours (6.5 = 6:30 AM). The README's broadcast day is an example; a household may shift bedtime without a code edit.
- **Episode join fade: 1.5 seconds.** Midpoint of the README's ~1–2 s range so joins feel like staying with the same friend, not a YouTube cut.
- **Volume default on start: 40%.** Below the 65% ceiling. Nothing is saved across a pulled plug, so 40% is audible without blasting a toddler after a power cycle.
- **Season multipliers: in-season 1.0, evergreen 0.20, wrong-season 0.05.** On a 1:1:1 mix of in-season, evergreen, and wrong-season files this is exactly 80% in-season (1 / 1.25). T4 maps months and verifies with a simulation.
- **Meteorological month ranges are named constants** (Spring Mar–May, Summer Jun–Aug, Autumn Sep–Nov, Winter Dec–Feb). T4 owns the mapping function.
- **Invalid environment values raise `InvalidSettingsError`.** A missing key keeps the default. Empty, non-numeric, negative lead days, or night lock at or before sign-on never fall back silently and never return None.
- **`load_settings` takes an injected mapping.** It does not read `os.environ` at import time, so tests stay pure. T15 passes the real environment at the composition root.
- **Coverage includes `tv90.config`.** Settings live outside domain/application; the 90% threshold is unchanged.
- **Clock is a `Protocol`, not an ABC.** Adapters match structurally. Domain and application depend on the port; they never import adapters.
- **Trust detection:** prefer `/run/systemd/timesync/synchronized` (file present ⇒ synced). If that path is missing or unreadable, run `timedatectl show --property=NTPSynchronized --value` and treat `yes` / `true` / `1` as trusted. If both are unavailable (macOS laptop, no systemd), the clock is untrusted. Unknown never raises and never writes to disk.
- **FakeClock lives in `adapters/fake_clock.py`.** T12 tests import the same fake. Construct with `FakeClock.trusted(time)` or `FakeClock.untrusted(time)` — not a boolean flag. Time advances in memory; it never sleeps on the OS.

## T2

- **Episode is one frozen dataclass** with optional cartoon numbers and an optional holiday title slug. Cartoon stems (`LittleBear`, `Oswald`, `Harry`) require `SxxExx` and forbid a title slug. `Holiday` requires a title slug and forbids `SxxExx`. Mixing those identity shapes raises `InvalidEpisodeError` so a holiday movie cannot look like a cartoon episode.
- **`SxxExx` on a Holiday file is malformed.** Holiday movies are titles (`Holiday_Rudolph_CHRISTMAS.mp4`), not season/episode numbers. `Holiday_S01E01_CHRISTMAS.mp4` is rejected.
- **`filename` is the original basename** given to `parse_filename` (the library path name). The formatter always emits canonical tag order and never emits `_DAY`. `parse(format(e)) == e` when that basename is already canonical (no `_DAY`, tags in daypart then season then holiday order).
- **Daypart, season, and holiday are enums** (`Daypart`, `SeasonTag`, `HolidayTag`). `_DAY` parses to `Daypart.GENERAL` and is dropped on format so it cannot survive as a scheduler daypart. Omitted daypart is general; omitted season is evergreen; omitted holiday is `None`.
- **Tag tokens after the identity may appear in any order.** Duplicate tags of the same kind (two dayparts, two seasons, two holidays, two `SxxExx`) are malformed. Unknown stems, unknown tokens on a cartoon file, empty names, empty tokens, and missing extensions are malformed. Parser raises `MalformedFilenameError` and never returns None.
- **Holiday title slug** is the leftover non-tag tokens joined with `_` in original order. That is how `Holiday_CHRISTMAS_Rudolph.mp4` and `Holiday_Rudolph_CHRISTMAS.mp4` share identity. A slug token must not be a known tag (those are consumed as tags).
- **Canonical format order after identity:** daypart (omit general / never `_DAY`), season (omit evergreen), holiday (omit none). `SxxExx` uses two digits (`S01E04`). Season and episode numbers are 0–99.
- **Media extensions for the library:** `mp4`, `mkv`, `avi`, matched case-insensitively. Parser accepts any non-empty extension; the library ignores non-media files entirely (they are not “unrecognized”). Unrecognized names are media files whose names fail `parse_filename`. Hidden files (basename starts with `.`) are skipped. The folder is flat: no recursion.
- **LibrarySource** exposes `episodes()` and `unrecognized_filenames()` as separate queries (no boolean flag). `FakeLibrarySource` takes injected tuples and never touches disk. `FilesystemLibrarySource` is given a directory path, never writes, fail-softs malformed media into unrecognized so one bad file cannot blank the TV, and returns episodes sorted by filename. A missing or non-directory path raises `LibraryDirectoryError`.
- **Duration miss vs corrupt vs probe failure are distinct exceptions**, never `float | None`. `DurationUnknownError` means the index has no entry. `CorruptDurationError` means a duration was present but not a positive finite number (zero, negative, NaN, inf). `ProbeFailedError` means ffprobe/the runner could not produce a duration (missing file, bad JSON, missing `format.duration`).
- **Duration index file format:** UTF-8 JSON object mapping filename string → seconds (number). `FileDurationIndex` is read-only. `write_duration_index` exists for T14 maintenance and is a separate function, not a method on the index; runtime lookup must not call it.
- **`DurationLookup` (application)** asks the index first; on `DurationUnknownError` it probes in memory and returns that duration. It never writes the index. Corrupt index values propagate and do not fall through to the prober.
- **ffprobe invocation:** `ffprobe -v quiet -print_format json -show_format -- <filename>`. Duration is `format.duration` (string or number). The command runner is injected so tests never call real ffprobe. `--` keeps a leading-dash filename from being parsed as an option. The production runner times out after 30 seconds so a stuck probe cannot freeze kiosk start.

## T3

- **Public API:** `TimeOfDayWeight(settings).weight(episode, clock_hour) -> float`. No shared `WeightFactor` protocol; T7 will multiply independent parts.
- **clock_hour range matches Settings:** `[MINIMUM_CLOCK_HOUR, MAXIMUM_CLOCK_HOUR]` i.e. 0.0 through 24.0 inclusive. 24.0 is midnight as hour 24, not wrapped to 0.0 — the Gaussian is not circular. Non-finite values and hours outside that range raise `InvalidClockHourError`.
- **CH 04 is not special-cased.** W_time is only `Daypart` and `clock_hour`. A holiday movie with general daypart uses the same piecewise function as an untagged cartoon. T8 owns forcing time weight 1 when a movie has no daypart tag.

## T4

- **Public API:** `month_to_season(month: int) -> SeasonTag` is a plain function (never `EVERGREEN`). `SeasonWeight(settings).weight(episode, month: int) -> float` is the strategy. Month is a calendar-month integer, not a `date` — the scheduler already has the local month, and this factor must not read the clock. No shared `WeightFactor` protocol; T7 will multiply independent parts.
- **Invalid months raise `InvalidMonthError`.** 0, 13, negatives, and any value outside the four meteorological month tuples. Never None. An evergreen file still validates the month: a bad month is always an error, even though the weight would ignore the calendar season.
- **Mapping uses the named month tuples** (`SPRING_MONTHS`, `SUMMER_MONTHS`, `AUTUMN_MONTHS`, `WINTER_MONTHS`). Domain code has no 1–12 literals. Weights come from Settings (`in_season_weight`, `evergreen_season_weight`, `wrong_season_weight`), not new magic numbers.
- **Holiday tags are ignored.** W_season compares `season_tag` to the calendar month only. `M_holiday` is T5. A Christmas-tagged winter cartoon in July is still wrong-season, not boosted.
- **Simulation:** tests inject `random.Random(1990)` (never the global RNG, never the clock) and draw 20_000 times from a 1:1:1 July pool. Algebraic in-season share from Settings is 0.8; simulated share must land in 0.76–0.84; wrong-season draws must be greater than zero so a zero wrong-season weight cannot hide inside the band.

## T5

- **Public API:** `load_holiday_calendar(environ, settings) -> HolidayCalendar` follows `load_settings`: injected mapping, no `os.environ`, no clock. `HolidayCalendar.from_defaults(settings)` is the same table with every holiday enabled and no date-rule overrides. Queries: `channel_four_open(on_date)`, `active_holiday(on_date) -> HolidayTag | None`, `layer_a_multiplier(episode, on_date)`, `channel_four_window(holiday, year) -> tuple[date, date] | None`. `None` from `active_holiday` / a disabled `channel_four_window` is “CH 04 is dark,” not a parse failure.
- **Table, not scattered dates.** `DEFAULT_HOLIDAY_DEFINITIONS` is a frozen tuple of `HolidayDefinition` (tag, event-day callable, enabled). Oct 31, Dec 24–25, second-Monday Thanksgiving, and Western Easter live only inside `holiday_dates.py` functions the table points at. The calendar never hardcodes those month-days.
- **CH 04 lead days come from `Settings.holiday_lead_days`.** `TV90_HOLIDAY_LEAD_DAYS` is already parsed by `load_settings`. The calendar does not parse that variable again. Window is first event day minus lead days through last event day inclusive; the day after the last event is closed.
- **Enable/disable env (missing → enabled).** Names: `TV90_HOLIDAY_HALLOWEEN`, `TV90_HOLIDAY_THANKSGIVING`, `TV90_HOLIDAY_CHRISTMAS`, `TV90_HOLIDAY_EASTER`. Values: `1` / `0` / `ON` / `OFF`, case-insensitive after strip. Anything else, including empty, raises `InvalidHolidayOverrideError` (variable name + reason). Never silent fallback. Disabled: `channel_four_window` is `None`; Layer A treats tagged files as outside (wrong-season weight).
- **Date-rule overrides.** Names: `TV90_HOLIDAY_<TAG>_EVENT` (e.g. `TV90_HOLIDAY_HALLOWEEN_EVENT`). Tokens are `MM-DD` or `YYYY-MM-DD`, comma-separated for multiple event days (Christmas). ISO year is used only to validate the date; the month-day applies every year so a test can pin Easter without forking the computus. Event days are sorted by month-day. Duplicates, empty tokens, and impossible month-days raise `InvalidHolidayOverrideError`. Feb 29 is accepted as a rule (validated against leap year 2000) and raises `InvalidHolidayDateError` when that year has no Feb 29.
- **Western Easter** is Anonymous Gregorian / Meeus–Jones–Butcher, stdlib only. Pinned: 2023-04-09, 2024-03-31, 2025-04-20, 2026-04-05. **Canadian Thanksgiving** is the second Monday of October: 2023-10-09, 2024-10-14, 2025-10-13.
- **Layer A ramp** uses `Settings.layer_a_lead_days` (14), `layer_a_lead_multiplier` (1.25), `layer_a_event_multiplier` (1.50), `wrong_season_weight`. “14 days out” is 14 days before the **first** event day, not before the CH 04 window. On the first event day through the last event day (inclusive, including any gap in an override list) the multiplier is the event value. Between those endpoints it interpolates linearly. Day after last event, and more than lead-days before first event: tagged files get `wrong_season_weight`. Untagged files are always `UNTAGGED_LAYER_A_MULTIPLIER` (1.0). A tag for a *different* holiday uses that tag’s own curve — it is not boosted by the active CH 04 holiday; if that tag is outside its own lead-up it is wrong-season-like. Disabled holidays are outside. `layer_a_lead_days == 0` boosts event days only (the ramp interval collapses to the event span).
- **Overlap.** Filename parser already forbids two holiday tags on one file. Layer A is per tag, so Thanksgiving and Halloween files in October follow independent curves. CH 04 is open if **either** window contains the date. `active_holiday` picks the open holiday whose **first event day is sooner**; equal first-event days break ties by `HolidayTag.name` (alphabetical), not table order. README table order is Halloween, Thanksgiving, Christmas, Easter; that is documentation order only. 2024 at default lead 3 does not overlap (Thanksgiving Oct 11–14, Halloween Oct 28–31); tests use a constructed two-row table.
- **Adjacent years.** Open-window and Layer A queries also consider year±1 so a lead that crosses 1 January still matches. `channel_four_window(holiday, year)` stays a single-year query.
- **Layer A is tag + date, not show stem.** A `Holiday_` movie with `_CHRISTMAS` gets the same multiplier as a cartoon with that tag. T8 owns the CH 04 pool and whether that multiplier is applied on the ghost channel.
- **No I/O.** Dates are injected. Environ is injected. Invalid years that cannot form a `date` raise `InvalidHolidayDateError`. A tag missing from a custom table raises `UnknownHolidayError`.

## T6

- **Public API:** `RecencyWeight(settings).weight(episode, recently_aired_filenames: Sequence[str]) -> float`. Identity is `episode.filename` (the file), not the show stem. No shared `WeightFactor` protocol; T7 will multiply independent parts.
- **History order is chronological (oldest first).** The timeline being built appends each airing, so the last `recency_block_count` items are the newest. Tests construct tuples oldest-to-newest so `history[-3:]` is the block window. Most-recent-first was the alternative; chronological matches how the builder walks the day.
- **`RECENCY_CLEAR_WEIGHT = 1.0` lives in `recency_weight.py`, not Settings.** Files outside the last `recency_penalty_count` airings, and empty history, return this identity. Block and penalty magnitudes stay on Settings (`recency_block_weight`, `recency_penalty_weight`). Same pattern as T5’s `UNTAGGED_LAYER_A_MULTIPLIER`.
- **Strict R only.** A filename in the last 3 still returns `recency_block_weight` (0). T6 does not add `weight(..., relax_block=True)` or a second method. T7 relaxes empty-weight slots by passing a truncated history (omit the block window, then the penalty window) or a second class.
- **No I/O, no clock, no random.** History is injected from the timeline being built. Only the last `recency_penalty_count` filenames matter for the penalty; last `recency_block_count` still block. A duplicate filename is blocked if any occurrence is in the last 3.

## T7

- **Public API:** `CombinedWeight(settings, holiday_calendar, channel_number).weight(episode, clock_hour, on_date, recently_aired_filenames) -> float` multiplies the four existing strategies. `DailyTimelineBuilder(settings, holiday_calendar, duration_index).build(on_date, channel_number, episode_pool) -> Timeline`. Frozen `Slot` (`episode`, `start_hour`, `duration_seconds`, `end_hour`) and `Timeline` (`date`, `channel_number`, `slots`). `Slot.starting_at` derives `end_hour`. Domain depends on `tv90.ports.duration.DurationIndex`, never adapters.
- **CH 04 time override lives on CombinedWeight, not TimeOfDayWeight.** T3 kept W_time channel-agnostic. When `channel_number` is `HOLIDAY_CHANNEL_NUMBER` (4) and `daypart` is `GENERAL` (omitted or `_DAY`), time factor is `HOLIDAY_CHANNEL_GENERAL_TIME_WEIGHT` (1.0) even at 8:00. `MORNING` / `NIGHT` still call `TimeOfDayWeight`. T8 still owns the CH 04 movie pool.
- **Seed payload:** `"{isoformat}|{channel_number}|{slot_start_hour:.6f}"` with `SEED_FIELD_SEPARATOR = "|"`. Example: `1994-07-15|1|6.500000`. Six decimal places so 6.5 and 6.50 hash the same, and a 1-second duration (`1/3600` h) still changes the next slot’s string. UTF-8 encode, `hashlib.sha256`, `int.from_bytes(digest, "big")`, then `random.Random(seed).choices(...)`. Never `hash()`.
- **Empty-weight steps (named, no flags):** `pick_with_recency` (full R) → `pick_without_block` (`RecencyWeight` on a Settings copy with `recency_block_weight` set to `recency_penalty_weight`, so last-3 get the penalty not zero) → `pick_without_recency` (empty history, R=1). If time/season/holiday are also all zero, `pick_without_recency` falls back to equal weight 1.0 among the pool. Empty pool → empty `Timeline` (T12 holds the slate); `pick_without_recency` on an empty pool raises `UnfillableTimelineSlotError`.
- **`SECONDS_PER_HOUR = 3600`.** Missing duration propagates from the injected index. Weighted choice preserves injected pool order. Recency history is filenames already on this timeline, chronological oldest-first.

## T8

- **Unknown channel raises `UnknownChannelError`.** Channels outside 01–04 (0, 5, 99) are programming errors, not a silent coerce to CH 01. Leftover CH 04 after the window closes is the one required remap: coerce, channel-up, and channel-down all land on CH 01. They do **not** treat leftover 4 as already-on-1 and then wrap (that would surf to 02 or 03).
- **Wrap is modular index on `channels_on`.** Live lineup is always `(1, 2, 3)` or `(1, 2, 3, 4)`. Channel-up is `index + 1`; channel-down is `index - 1`. That down step is the mirror of up: with CH 04 live, 01 down goes to 04; without it, 01 down goes to 03.
- **`episodes_for_channel` preserves injected order.** Cartoon pools are show-stem equality (`LITTLE_BEAR_SHOW_STEM` on CH 01, and so on). CH 04 is `HOLIDAY_SHOW_STEM` **and** `holiday_tag == active_holiday(date)`. Closed window or no active holiday → empty tuple, not an error. Holiday-tagged cartoons stay on 01–03; they never enter the movie pool. Layer A stays on CombinedWeight (T7); T8 only filters which files CH 04 may air.
- **`ChannelLineup(settings, holiday_calendar)`** takes Settings for composition-root symmetry. Wrap and pools read `HolidayCalendar` plus the config channel numbers and show stems; they do not invent a second holiday table.
- **`resolve_airing` returns `Airing | OutsideBroadcastDay`.** `OutsideBroadcastDay` is the documented “nothing on” result (player holds slate): clock before sign-on, at or after night lock, an empty timeline, or a gap with no covering slot. It is not a parse failure. `None` is never returned. Overlapping or inverted slots raise `CorruptTimelineError` instead of inventing an airing.
- **Night lock wins over a slot that runs past 21:00.** An episode may start before lock; `clock_hour >= night_lock_hour` is still outside even if that slot’s `end_hour` is later. Inside the day, the covering slot is `start_hour <= clock_hour < end_hour`. Offset is `(clock_hour - start_hour) * SECONDS_PER_HOUR` from `timeline`. Clock hour range matches T3 (`InvalidClockHourError`).
- **`Station` caches `(date, channel) → Timeline` in a dict on the instance.** No disk. One library snapshot per `Station`; a new instance if the library changes. Stale CH 04 is coerced to CH 01 before build/cache. `timelines_on` builds every live channel from `channels_on`.
