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
