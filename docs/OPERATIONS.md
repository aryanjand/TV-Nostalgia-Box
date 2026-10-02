# 90s Cable TV Nostalgia Box — parent operations

This is the household guide. You do not need to read the code.

## What this box is

This is a small television, not YouTube.

Plug it in and the box sits on a calm slate. The parent turns the TV on themselves. There is no menu, no search, no “Up Next,” and no list of episodes to pick. A parent phone on the home Wi-Fi can change channel and volume. That is all.

Three friends live on three channels: Little Bear on CH 01, Oswald on CH 02, Harry and His Bucket Full of Dinosaurs on CH 03. A fourth channel appears only around a holiday, with a small set of holiday movies. Shows never come from the internet. If the Wi-Fi is down, the picture still plays from the files on the box.

Mornings tend to be morning-tagged episodes, evenings night-tagged, midday ordinary ones. After 9:00 PM the box goes off-air (calm slate) until morning sign-on (6:30 AM unless you change it). The TV itself is not put on standby; you turn the set on and off. Pulling the power plug is how you turn the box off. That is on purpose.

## First install on the Pi

You need a Raspberry Pi 4, a microSD card, an HDMI cable to the TV, and the official USB-C power supply.

1. Install Raspberry Pi OS Bookworm on the card and boot the Pi once so it can finish first-run setup.
2. Copy this project onto the Pi.
3. On the Pi, open a terminal in the project folder and run `setup.sh` as root (`sudo ./setup.sh`). Wait until it prints that setup is complete. The hostname becomes `90stv`. Folders, the TV service, and the maintenance command are installed for you.
4. Enter maintenance with `sudo tv90-maintenance on` (next section). The words **maintenance mode** print *before* any reboot. After the Pi comes back it will not reprint the mode. Run `sudo tv90-maintenance status` and confirm it says `maintenance mode`.
5. Copy your episode files into `/srv/90stv/library` with `sudo` (or as the `tv90` user). Keep them in that one folder (no subfolders). Cartoon names look like `LittleBear_S01E04.mp4`. Holiday movies look like `Holiday_Rudolph_CHRISTMAS.mp4`.
6. Tag, then index (see “Adding episodes” below). Those commands also need `sudo` (or the `tv90` user).
7. Leave maintenance with `sudo tv90-maintenance off`. **tv mode** prints before any reboot; after the Pi comes back it will not reprint the mode. The television should be on: no desktop, the stream on the set. Confirm with `sudo tv90-maintenance status` if you want the printed words.

If the library is still empty, the child should see a calm colored slate, never a desktop or an error dump.

## How to enter and leave maintenance

On the Pi these need administrator rights. `setup.sh` installs the command at `/usr/local/bin/tv90-maintenance`. Put `sudo` in front (or run them as the `tv90` service user). Without that, the household will see permission errors.

- `sudo tv90-maintenance on` — stop the TV, make the library writable, and take the box out of the write-protected TV overlay so you can add files, tag, index, or change settings.
- `sudo tv90-maintenance off` — put the library back to read-only, turn the write-protected overlay back on, and start the TV again.
- `sudo tv90-maintenance status` — print the current mode and nothing else.

Both `on` and `off` are safe to run twice. If you are already in that mode, nothing harmful happens.

**What the printed words mean**

The last line is the mode:

- `maintenance mode` — you may copy files, tag, index, and edit settings. The TV service is not showing live cable.
- `tv mode` — the box is a television again. Do not add files or edit settings here; those writes would not last.

Lines above the last line are extra notes. Examples:

- `skip overlay: not a Raspberry Pi` — you ran this on a laptop; that is fine.
- `skip remount: library is not a mount point` — episodes live in the ordinary folder; there is no separate disk yet.
- `skip overlay: raspi-config is unavailable` — this image cannot flip the write-protect layer; the mode line still tells you where you landed.

If a reboot is required, the Pi prints the mode **first**, then reboots. It does not print the mode again after it comes back. Wait for the reboot to finish, then run `sudo tv90-maintenance status`.

Wrong usage prints: `usage: tv90-maintenance on|off|status`

## Adding episodes

Always in maintenance mode. The library folder is owned by the `tv90` user. Copy, tag, and index with `sudo` (or as `tv90`) so you do not get permission errors.

1. Copy the new video files into `/srv/90stv/library` (`sudo cp … /srv/90stv/library/`). One flat folder. Use the show names the box already knows: `LittleBear_`, `Oswald_`, `Harry_`, or `Holiday_`. Cartoons need a season and episode number (`S01E04`). Holiday movies need a title and a holiday word (`_HALLOWEEN`, `_THANKSGIVING`, `_CHRISTMAS`, or `_EASTER`).
2. Dry-run tags (changes nothing). On the Pi:

   `sudo /opt/90stv/venv/bin/python3 -m tv90 tag --library /srv/90stv/library`

   You should see a table: file, title, proposed tags, and which words triggered them. Files the catalog does not know are listed at the end. Tags already in a filename are left alone.
3. If the table looks right, apply:

   `sudo /opt/90stv/venv/bin/python3 -m tv90 tag --library /srv/90stv/library --apply`

4. Index durations (so the day’s schedule knows how long each file is):

   `sudo /opt/90stv/venv/bin/python3 -m tv90 index --library /srv/90stv/library`

5. `sudo tv90-maintenance off`. After reboot, the new episode can air when the scheduler picks it. There is no “play this file now” button. Confirm the mode with `sudo tv90-maintenance status` if you want the printed words.

Tagging uses the internet once to fetch titles and descriptions, then remembers them next to the library so a second run does not fetch again. Playback never uses that network.

## Editing keyword rules

Tags come from a word list, not from rewriting the program.

On the Pi the file is (use `sudo` to edit; ordinary accounts cannot write it):

`/opt/90stv/venv/lib/python3.11/site-packages/tv90/data/keyword_rules.toml`

If you still have the project folder, the same file is `src/tv90/data/keyword_rules.toml`. Edit one copy. If you edit the project copy, run `sudo ./setup.sh` again so the Pi’s installed copy matches.

Each block is a tag and the words that mean that tag (snow → winter, bedtime → night, pumpkin → Halloween, and so on). Words are matched whole, ignoring capitals: `ice` will not tag a title that only contains `nice`.

After you save, enter maintenance if you are not already in it (`sudo tv90-maintenance on`), dry-run tag with `sudo` as above, then `--apply` if the table is right. Existing filename tags are never overwritten.

## Changing settings

These names are the household knobs. Put them on the TV service only while you are in **maintenance mode** (so the change is on the real card, not the throw-away overlay). The file is `/etc/systemd/system/90stv.service` (needs `sudo` to edit). Add or change an `Environment=` line, then `sudo tv90-maintenance off` so TV mode starts with the new values.

| What you want | Name | Example | Default |
| --- | --- | --- | --- |
| Clock and holiday dates follow your civil time | `TV90_TIMEZONE` | `America/Vancouver` | `America/Vancouver` |
| Morning sign-on | `TV90_SIGN_ON` | `6.5` is 6:30 AM; `7` is 7:00 AM | `6.5` |
| Night lock (box off-air) | `TV90_NIGHT_LOCK` | `21.0` is 9:00 PM; `20.5` is 8:30 PM | `21.0` |
| How many days before a holiday CH 04 appears | `TV90_HOLIDAY_LEAD_DAYS` | `3` | `3` |
| Turn a holiday on or off | `TV90_HOLIDAY_HALLOWEEN`, `TV90_HOLIDAY_THANKSGIVING`, `TV90_HOLIDAY_CHRISTMAS`, `TV90_HOLIDAY_EASTER` | `1` / `ON` enable; `0` / `OFF` disable | enabled if you omit the line |

Night lock must be later than sign-on. Empty or nonsense values are not silently ignored; the TV will refuse to start until the line is a real number or zone name.

Do not add new channels, menus, or streaming URLs. This box only plays the local library.

## How to read the simulator on a laptop

The simulator prints a day’s schedule as text. It does not play video and does not need a Pi.

From the project folder (with the project’s Python environment active):

`python -m tv90 simulate --date YYYY-MM-DD`

Examples: `--date 2024-07-15` is an ordinary summer day (CH 01–03 only). `--date 2024-10-31` is Halloween (CH 04 holiday movies as well).

Optional: `--library /path/to/your/episodes` to use your files instead of the tiny dummy library that ships with the tests.

You should see channel headers and clock times with filenames. You should not see a picker, thumbnails, or “Up Next.” That printout is what that date would air.

## Manual checks that can only be done on the real Pi and TV

Do these after first install, and again after a big library change. A laptop cannot stand in for HDMI, overlay, or a pulled plug.

1. **Power-on kiosk.** Apply power. No desktop, no mouse cursor, no login prompt. After a short wait for the clock, the box holds a calm slate. CHANNEL UP or CHANNEL DOWN on the phone remote starts the current channel.
2. **Web remote.** On a phone on the same Wi-Fi, open `http://90stv.local:5000`. You should see Now Playing and four buttons: channel up, channel down, volume up, volume down. No episode list.
3. **Channel and volume on the real TV.** Use the phone remote. The TV OSD shows `CH 01` (and so on) for a few seconds, and a segmented volume bar when you change volume. Channel-up visits 01 → 02 → 03 → (04 only in a holiday window) → 01.
4. **Night lock.** At 9:00 PM local (or your night lock), the box goes off-air (slate). Buttons do nothing until morning sign-on. The television is not put on standby. At sign-on the box waits on the slate until CHANNEL UP or CHANNEL DOWN.
5. **Pull-the-plug.** While something is playing, yank the USB-C power, wait a few seconds, plug it back in. The box returns to the calm slate until CHANNEL UP or CHANNEL DOWN; then live TV for whatever the wall clock says that channel should be airing (mid-episode is correct; starting the file over is wrong). The card is not corrupted. The TV does not show write errors, a desktop, or a stack trace.
6. **Unplug the network.** Unplug ethernet / turn off Wi-Fi. The TV still plays the local library. The phone remote may disappear until the LAN returns. If the clock was not synced, Now Playing may show `clock not synced`, then retune when time sync comes back.
7. **Overlay / read-only.** In **tv mode**, create a throw-away file on the system disk (not in the library). Reboot. That file should be gone. Library episodes are still there.
8. **Maintenance add-one-file.** `sudo tv90-maintenance on`, copy one new episode into `/srv/90stv/library` with `sudo`, dry-run tag, `--apply`, index (all with `sudo` as above), `sudo tv90-maintenance off`. After reboot the new episode is eligible to air (confirm with the simulator for today, or wait until that channel picks it).

## Requirement → where verified

README sections 2–5 and the three README overrides. “Test” means automated on a laptop. “Manual” means a numbered check above on the Pi and TV.

| Requirement | Where verified |
| --- | --- |
| **§2 Automated provisioning script** (`setup.sh`, packages, hostname `90stv`, folders) | `tests/test_setup_script.py` |
| **§2 Systemd daemon** (`90stv.service`, restart on failure) | `tests/test_setup_script.py`, `tests/test_main.py`; Manual 1 |
| **§2 Headless kiosk boot** (no login/desktop/cursor; stream on power) | `setup.sh` (multi-user target, display managers disabled); Manual 1 |
| **§2 Internet for operations, never for content** | `tests/test_television.py` (controller does not import metadata), `tests/test_setup_script.py` (no outbound firewall; NTP enabled); Manual 6 |
| **§2 Fail-soft, never a computer** (missing/corrupt file, empty library, HDMI flap → slate, skip, keep ticking) | `tests/test_television.py`, `tests/test_end_to_end.py` (yank mid-week); Manual 1, 5 |
| **§2 Read-only runtime** (overlay, write-protected boot) | `tests/test_setup_script.py`, `tests/test_maintenance.py`; Manual 7 |
| **§2 Library partition** (episodes on their own mount, read-only in TV mode) | `tests/test_setup_script.py` (fstab stub); Manual 7, 8 |
| **§2 No disk writes while the TV service runs** | `tests/test_end_to_end.py` (read-only library week), `tests/test_television.py`, `tests/test_player.py`; Manual 5, 7 |
| **§2 Maintenance mode** (`tv90-maintenance on` / `off`, idempotent, prints mode) | `tests/test_maintenance.py`; Manual 8 |
| **§2 Trusted clock before tuning in** (slate, timeout, `clock not synced`, retune) | `tests/test_television.py`, `tests/test_end_to_end.py`, `tests/test_clock.py`; Manual 6 |
| **§3 MPV rendering backend** | `tests/test_player.py`, `tests/test_main.py`; Manual 1 |
| **§3 Wall-clock live TV sync** (power-on/reboot/channel-surf land on now, not tape-from-start) | `tests/test_airing.py`, `tests/test_television.py`, `tests/test_end_to_end.py`; Manual 5 |
| **§3 Retro OSD** (neon `CH 0N`, volume bar) | `tests/test_player.py`, `tests/test_television.py`; Manual 3 |
| **§3 Channel tuning effect** | `tests/test_player.py`; Manual 3 |
| **§3 Gentle episode joins** (same-channel fade, not a hard cut) | `tests/test_player.py`, `tests/test_television.py` |
| **§4 Closed 3-show library** (CH 01–03 one show each; CH 04 ghost) | `tests/test_lineup.py`, `tests/test_end_to_end.py` |
| **§4 Zero decision fatigue** (no menus; remote is channel + volume only) | `tests/test_remote.py`, `tests/test_end_to_end.py`; Manual 2 |
| **§4 Filename tags, flat library** | `tests/test_filename.py`, `tests/test_library.py` |
| **§4 Per-channel daily timeline** (seeded, reboot-stable) | `tests/test_timeline.py`, `tests/test_simulate.py`, `tests/test_end_to_end.py` |
| **§4 Time-of-day weights** (morning / general midday / night) | `tests/test_time_weight.py`, `tests/test_end_to_end.py` |
| **§4 Night lock 9:00 PM** | `tests/test_broadcast_day.py`, `tests/test_television.py`, `tests/test_end_to_end.py`; Manual 4 |
| **§4 Four-season ambient sync** | `tests/test_season_weight.py` |
| **§4 Holiday engine** (CH 04 window, Layer A, movies stay on 04) | `tests/test_holiday_calendar.py`, `tests/test_lineup.py`, `tests/test_end_to_end.py` |
| **§4 Anti-repeat recency** | `tests/test_recency_weight.py`, `tests/test_timeline.py` |
| **§4 Station sign-on / sign-off** | `tests/test_broadcast_day.py`, `tests/test_television.py`, `tests/test_end_to_end.py`; Manual 4 |
| **§5 LAN-only Flask remote** (`http://90stv.local:5000`, four buttons, Now Playing) | `tests/test_remote.py`, `tests/test_end_to_end.py`; Manual 2 |
| **§5 No physical toddler remote** | Design + Manual 2 (parent phone only) |
| **§5 Input debouncing (500 ms)** | `tests/test_television.py` |
| **§5 Hardware audio ceiling** | `tests/test_television.py`, `tests/test_config.py`; Manual 3 |
| **§5 HDMI-CEC sleep scheduling** | Not used. Production is `NullTvPower`; night lock is off-air slate. `tests/test_tv_power.py`, `tests/test_television.py`; Manual 4 |
| **Override 1 — Internet allowed, never for content** | `tests/test_setup_script.py` (no outbound firewall; NTP enabled), `tests/test_television.py` (controller does not import metadata); Manual 6 |
| **Override 2 — Survive a pulled plug** | `tests/test_end_to_end.py` (no runtime writes), `tests/test_setup_script.py`, `tests/test_maintenance.py`; Manual 5, 7 |
| **Override 3 — Episode tags generated by a tool** | `tests/test_tagging.py`, `tests/test_keyword_tags.py`, `tests/test_cli.py`; Manual 8 |
