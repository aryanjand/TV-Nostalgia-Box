# 90s Cable TV Nostalgia Box: Final Project Requirements Document

## First-time setup (Raspberry Pi)

Do this from a laptop on the same Wi-Fi. You only type on the TV if SSH will not connect.

**What you need**

* Raspberry Pi 4, 32GB+ microSD card, HDMI cable to the TV, official USB-C power supply
* Home Wi-Fi
* Raspberry Pi Imager on your computer ([raspberrypi.com/software](https://www.raspberrypi.com/software/))

**1. Flash the card**

1. Open Raspberry Pi Imager.
2. Choose your Pi, then **Raspberry Pi OS Lite (64-bit)**. The desktop is not needed.
3. Open settings (the gear) and set:
   * a username and password (remember them — this is how you log in)
   * **Enable SSH**
   * your Wi-Fi name and password
4. Write the image. Put the card in the Pi.

**2. First boot**

1. Plug HDMI into the TV, then plug in power.
2. Wait 2–3 minutes. A login prompt on the TV is **normal this one time**.
3. Do not log in on the TV. Use your laptop for the next steps.

**3. Log in from your laptop**

```bash
ssh YOURUSERNAME@raspberrypi.local
```

Use the username you set in Imager. If that hostname does not work, look up the Pi’s IP in your router and run `ssh YOURUSERNAME@192.168.x.x`.

**4. Install the box**

```bash
sudo apt-get update
sudo apt-get install -y git
git clone https://github.com/aryanjand/TV-Nostalgia-Box.git
cd TV-Nostalgia-Box
sudo ./setup.sh
```

You **must** use `sudo`. Without it, shows may download but the TV will not start and the screen stays on a login. Downloads need the internet and can take a long time. Leave the command running until it finishes.

**5. Reboot**

If the script says a reboot is needed, run:

```bash
sudo reboot
```

If it does not say that, reboot once anyway so the TV takes the screen:

```bash
sudo reboot
```

**6. After the reboot (final check)**

1. The TV shows a **calm muted green screen**. That is the idle slate. It is working.
2. You should **not** see a desktop, a mouse cursor, or `90stv login:`.
3. On your phone (same Wi-Fi) open [http://90stv.local:5000](http://90stv.local:5000).
4. Tap **CHANNEL UP**. A show should start.
5. Sound comes from the TV speakers. Turn the TV volume up. The box sends audio over HDMI, not the headphone jack.

`tv90` is the service account. It cannot log in. Always use the username you set in Imager.

**If the TV still shows a login after setup**

From your laptop:

```bash
ssh YOURUSERNAME@90stv.local
cd TV-Nostalgia-Box
sudo ./setup.sh --skip-media
sudo reboot
```

Then check the TV again. Optional: `sudo tv90-maintenance status` should print `tv mode`.

Household day-to-day steps (maintenance, adding episodes, settings) are in `docs/OPERATIONS.md`.

---

### Design North Star

Unlike YouTube or Netflix, this box is not engineered for watch time, click-through, or a dopamine loop. It is a **safe, passive routine** for a 2-year-old: cognitive calm, developmental consistency, and stress-free entertainment. Script and library architecture must prioritize the following over engagement metrics.

1. **Minimal cognitive stimulation (slow pacing).** Fast-cut, high-energy feeds (Cocomelon-style flashes, unboxings) hyper-focus attention and leave kids irritable. The library is *Kipper*, *Oswald*, and *Harry and His Bucket Full of Dinosaurs* — slow camera, visual stillness, quiet music. Do not add high-stimulation titles to “fill the card.”
2. **Predictability and routine over novelty.** A changing feed keeps kids searching. A **closed ~140-episode library** of the same three friends, looping familiar simple tasks, is how toddlers learn language and structure. Comfort, not “what’s new.”
3. **Gentle environmental connection.** Algorithms detach kids from the room and the season. Filename tags (`_WINTER`, `_SUMMER`, `_MORNING`, `_NIGHT`, holiday suffixes) plus the Python scheduler keep the screen an extension of the real day: weather, trees, morning vs bedtime, holidays outside the window.
4. **Zero decision fatigue (no menus).** Scrolling pickers create fights. There is no episode list, no search, no Up Next. Power on plays a gentle surprise; power off is the only “choice.” Channel buttons (if used) only switch which of the three friends is on — never which file.

---

### 1. Hardware & Storage Specifications

* **Core Compute:** Raspberry Pi 4 (2GB RAM).
* **Storage:** 32GB MicroSD Card (curated media storage for high-quality, slow-paced 90s/2000s toddler cartoons without bloated folder requirements).
* **Cooling:** Passive aluminum heatsink enclosure (e.g., Flirc case) for silent, fan-free operation.
* **Power Supply:** Official 15W (5.1V / 3.0A) USB-C power supply to prevent undervoltage issues during continuous playback.
* **Display Output:** Micro-HDMI to Standard HDMI cable connected to a modern television.
* **Controller:** None in the toddler's hands. The only remote is a parent **Wi-Fi web remote** on a phone/tablet already on the home LAN (see §5). No USB air mouse, no extra buttons on the TV stand.

---

### 2. System Architecture & Provisioning

* **Automated Provisioning Script:** A single Bash setup script (`setup.sh`) automates system updates, installs dependencies (`mpv`, `flask`, `avahi-daemon`), assigns the hostname (`90stv`), configures local mDNS discovery, and sets up project folders. First run (`./setup.sh`, or `sudo ./setup.sh` on the Pi) also fetches the local episode library and channel bumpers; playback itself never uses the network.
* **Systemd Daemon Service:** The application runs as a background service (`90stv.service`) with `Restart=always` to guarantee immediate startup on power-up and automatic recovery if a process exits unexpectedly.
* **Headless Kiosk Boot:** The device boots directly into the live television video stream upon receiving power—bypassing user logins, desktop environments, and command-line text to mimic an arcade machine or classic TV set.
* **Internet for operations, never for content:** Shows never come from the internet. The library is 100% local. Playback never fetches, streams, or depends on anything online. If the internet is down, the TV works exactly the same. The Pi may use the internet for time sync (NTP), for system updates during maintenance, and for fetching episode titles and descriptions during maintenance. Avahi/mDNS stays on the LAN (`90stv.local`). Do not configure an outbound firewall.
* **Fail-soft, never a computer:** If a file is missing/corrupt, HDMI drops, or the SD library is empty, the child must still see a **calm slate** (soft color field or a still of the current friend) — never a desktop, cursor, login, terminal, or stack trace. Skip a bad file and continue the timeline; if nothing can play, hold the slate until the library is fixed. HDMI flap: wait and resume, do not exit kiosk.

#### Power-cut safety

The box is switched off like a TV: the plug is pulled, with no shutdown sequence.

* **Read-only runtime:** Overlay filesystem, write-protected boot partition. Runtime writes go to memory and disappear at power-off.
* **Library partition:** Episodes live on their own partition, mounted read-only during normal use.
* **No disk writes while the TV service runs:** The application writes nothing to disk — no play history, no caches, no state files, no log files. Logs go to the journal, memory-only (`Storage=volatile`). mpv must not write watch-later or cache files.
* **Maintenance mode** via `tv90-maintenance on|off`:
  * `on` stops the TV service, disables the overlay, remounts the library writable, and reboots if required.
  * `off` reverses it.
  * Both directions are idempotent and print plainly which mode the box is in.
  * Adding episodes, tagging, indexing durations, and system updates happen in maintenance mode.
* **Trusted clock before tuning in:** The Pi has no battery clock. On start, hold the calm slate until the clock is trusted (network time synchronised). If still untrusted after a configurable timeout (default 3 minutes), begin playback using the system's best-known time so the child is not left with a blank slate, show "clock not synced" on the web remote's now-playing line, and re-tune to the correct airing as soon as sync arrives.

---

### 3. Video Playback & Display Interface

* **Rendering Backend:** MPV controlled via Python.
* **Wall-Clock Live TV Sync:** Each channel airs a **daypart-aware daily timeline** (see §4). Power-on, reboot, and channel-surf all jump to the file + timestamp that station is broadcasting *right now* — including morning vs night weighting — not a fresh random draw, and **not** from the start of the episode. If the theme already aired, they missed it; that is intentional (real cable).
* **Retro On-Screen Display (OSD):** Styled with a neon-green (`#00FF00`) blocky monospace CRT font displaying channel banners (e.g., `CH 03`) for 3 seconds upon channel changes, alongside horizontal segmented volume bars during audio adjustments.
* **Channel Tuning Effect:** A brief 150ms static/noise burst or black frame plays during channel changes to simulate analog tuner signal acquisition.
* **Gentle episode joins (no YouTube cut):** When one file ends and the next on the same channel begins, do **not** hard-cut. Fade audio/video ~1–2 s, or play a short still bumper of the **same friend** (Oswald into Oswald). The message is “we’re still with this friend,” not autoplay-next. Channel changes may still use the short tuner effect above.

---

### 4. Content Scheduling & Time-Aware Engine

The scheduler is how the north star becomes code: **which episode of the current friend** is on, given clock, season, and holiday — never which new video to chase. CH 01–03 stay one show each. Time-of-day Gaussians bias *morning-tagged episodes to the morning* and *night-tagged episodes to the evening* inside that show. They do not mix Kipper against Oswald (that would be a feed).

* **Closed 3-Show Library (~140 episodes):** Three dedicated cartoon channels, one show each, on the 32GB card. No search, no related videos, no growing catalog.

  | Channel | Show | Role on the box |
  | --- | --- | --- |
  | **CH 01** | *Kipper* | Gentle walks, quiet friends, low sensory load |
  | **CH 02** | *Oswald* | Gentle city strolls, classical-leaning music |
  | **CH 03** | *Harry and His Bucket Full of Dinosaurs* | Familiar friend + simple pretend-play loop |
  | **CH 04** | Holiday movies | **Ghost channel** — not in the lineup except during a holiday window |

* **Zero Decision Fatigue:** No episode menus, thumbnails, or "Up Next." Default experience is **power on → already playing.** The parent Wi-Fi remote only changes **channel** and **volume** (adult override, not a library). Channel-up wraps `01 → 02 → 03 → (04 if live) → 01`. The toddler-facing rule remains: TV is on (gentle surprise) or off.

* **Filename Tags, Flat Library:** Single folder. The scheduler parses suffixes:

  * Show stem: `Kipper_…`, `Oswald_…`, `Harry_…`, `Holiday_…`.
  * Daypart: `_MORNING`, `_NIGHT` (omit = **general** — equal chance at midday). Optional `_DAY` is treated the same as untagged.
  * Season: `_SPRING`, `_SUMMER`, `_AUTUMN`, `_WINTER` (omit = season-evergreen).
  * Holiday: `_HALLOWEEN`, `_THANKSGIVING`, `_CHRISTMAS`, `_EASTER`.
  * Example: `Kipper_S01E04_MORNING_WINTER.mp4`, `Oswald_S01E09_NIGHT.mp4`, `Holiday_Rudolph_CHRISTMAS.mp4`.
  * Tags are assigned by `python -m tv90 tag` (see §6), not by hand.

* **Per-Channel Daily Timeline (live TV, time-varying weights):** Because each cartoon channel **is** one show, the engine never picks a series. At local midnight (or first boot), it **walks the broadcast day in order** and fills slots so 8:00 AM draws morning-biased, midday is a **fair lottery among general episodes**, and evening draws night-biased until the 9:00 PM lock:

  1. Pool = all files for that show (CH 04 only if a holiday window is active).
  2. `t = sign_on` (e.g. 6:30). While `t < 21.0` (9:00 PM lock): compute `Weight(file, t)` below, pick with a **seeded RNG** (`date + channel + t`) so a reboot lands on the same airing, append the file, `t += duration`.
  3. Playback seeks to the slot covering `now` (file + offset). Channel-surf uses that same timeline — not a new roll.

* **Time-of-Day ($W_{\text{time}}$):** Morning and night use Gaussians. **Midday does not** — it is a flat, equal-chance draw among general episodes. Hour $t$ is decimal local time (8.5 = 8:30 AM). Morning/night PDFs scale to peak $1.0$, then floor at $\varepsilon \approx 0.05$ (statistical, not a hard ban, except the 9:00 PM lock).

  | Tag | Meaning | $W_{\text{time}}$ rule |
  | --- | --- | --- |
  | `_MORNING` | Wake-up, breakfast, getting-dressed (still slow-paced) | Gaussian $\mu = 8.0$ (8:00 AM), $\sigma = 2.0$ |
  | *(none)* or `_DAY` | **General** — ordinary episodes | **Equal chance at midday** (~10:00 AM–5:00 PM): every general file gets $W_{\text{time}} = 1$ (no ranking among them). Outside midday, $W_{\text{time}} = 0.35$ so they can fill gaps without tying morning/night at their peaks |
  | `_NIGHT` | Moon, pajamas, quiet wind-down | Gaussian $\mu = 20.0$ (8:00 PM), $\sigma = 1.5$ — peaks in the hour before the 9:00 PM lock |

  $$W_{\text{time}}(\text{morning or night}, t) = \max\left(\varepsilon,\; \exp\!\left(-\frac{(t-\mu)^2}{2\sigma^2}\right)\right)$$

  $$W_{\text{time}}(\text{general}, t) = \begin{cases} 1 & 10 \le t < 17 \\ 0.35 & \text{otherwise} \end{cases}$$

  Example: 8:00 AM favors `_MORNING`. 1:00 PM is a **fair lottery** across general episodes (recency $R$ still applies; season/holiday still apply). 8:00 PM favors `_NIGHT`. **Episode dayparting, not show mixing** — Oswald at night is still Oswald.

* **Night lock — 9:00 PM:** Hard stop at **21:00 local**. The engine will not start a new episode at or after 9:00 PM. The box holds an off-air slate; it does not send HDMI-CEC standby. This is the only hard time gate; morning/night Gaussians stay probabilistic.

* **4-Season Ambient Sync (within each show):** Month → meteorological season (Spring Mar–May, Summer Jun–Aug, Autumn Sep–Nov, Winter Dec–Feb). Current-season tags get ~80% of seasonal weight; season-evergreen fills the rest; wrong-season is down-weighted (snowy Kipper is rare in July), not deleted. Screen weather should mostly match the trees outside.

* **Holiday Engine — two layers:**

  * **Config: constants, overridable by env.** Holiday names, file tags, event-date rules, CH 04 lead-in days, and Layer A cartoon lead-up live in a **constants** table (e.g. `holidays.py` / a `HOLIDAYS` dict). The scheduler only reads that table — it does not hardcode “Oct 31”. **Env vars override constants** without a code edit (enable/disable a holiday, change lead-in, swap a date rule). Missing env → use the constant. Defaults below are the Canadian set.

  * **Layer A — regular channels (lead-up):** Two weeks before a mapped holiday (constant, env-overridable), holiday-tagged *episodes of that show* get a progressive multiplier (~1.25 → 1.50). The three friends stay on CH 01–03; they start “noticing” the holiday.
  * **Layer B — CH 04 ghost channel:** Exists only inside an **inclusive date range**, not a single night. Closed, familiar movie set for that occasion (repeat the same few titles). Movies stay on CH 04; cartoons stay on 01–03. CH 04 **ignores $W_{\text{time}}$** unless a movie is explicitly daypart-tagged (most are not). The range **opens 2–3 days before** the first event day (constant `HOLIDAY_LEAD_DAYS`, default 3, env override) and **closes at the end of the last event day** — no hangover after. **Event days** max Layer A on CH 01–03 and leave CH 04 as the movie marathon. After the range ends, CH 04 drops from the wrap; a leftover CH 04 press lands on CH 01.

  Default holiday table (constants; env may add, remove, or retune):

  | Holiday | Window (CH 04 visible) | Event-day marathon |
  | --- | --- | --- |
  | Halloween | Oct 28–29 → Oct 31 (Oct 31 − 2–3 days) | Oct 31 |
  | Thanksgiving (Canada) | Fri–Sat → second Monday of October (Monday − 2–3 days) | Thanksgiving Monday |
  | Christmas | Dec 21–22 → Dec 25 (Dec 24 − 2–3 days) | Dec 24–25 |
  | Easter | Easter − 2–3 days → Easter Sunday | Easter Sunday |

* **Anti-Repeat & Final Weight (per channel):** Same *show* on purpose; not the same *file* twice in an hour. Recency $R$ is per channel: last 3 blocked ($R = 0$), last 10 penalized ($R = 0.15$). For each slot at time $t$:

  $$\text{Weight} = W_{\text{time}}(t) \times W_{\text{season}} \times M_{\text{holiday}} \times R$$

* **Station sign-on / sign-off:** Broadcast day e.g. 6:30 AM – **9:00 PM** (night lock). Outside that window the engine does not start another episode; the box holds an off-air slate. Parents turn the TV on themselves. On or off — never an infinite next-up queue.

---

### 5. Remote Control, Web UI & Safety Controls

* **LAN-only Flask remote (parent device):** The **only** controller is the embedded Flask page on the home LAN at `http://90stv.local:5000` (or local IP). Large buttons: `CHANNEL UP`, `CHANNEL DOWN`, `VOLUME UP`, `VOLUME DOWN`, and a "Now Playing" line. No episode grid, no search, no thumbnails. Bind to LAN; do not expose the remote to the internet. Network access on the Pi also supports NTP and maintenance (see §2); it is never used to fetch or stream shows.
* **No physical toddler remote:** No USB air mouse / extra IR clicker on the table. The parent turns the TV on; the phone remote starts the current channel from idle.
* **Input Debouncing:** Enforces a 500ms command cooldown on the web remote so repeated taps do not race the player.
* **Hardware Audio Ceiling:** Hard-codes a maximum audio output limit (e.g., 65% ALSA volume) to protect hardware and child hearing.
* **Idle until the parent remote:** After the clock is trusted (or the trust timeout), the box stays on a calm slate. CHANNEL UP or CHANNEL DOWN on the phone remote starts the current channel at the wall-clock offset without wrapping. The box does not send HDMI-CEC standby or power-on.

---

### 6. Library Maintenance Tools

These tools run only in maintenance mode (`tv90-maintenance on`), on the Pi or a laptop pointed at a folder of episodes.

* **`python -m tv90 tag`** assigns tags by renaming files to the §4 naming scheme. It identifies each episode from show stem and season/episode number, fetches title and description from a free online episode database, and matches keywords to tags.
  * Dry run is the default: print a plain table of file, title, proposed tags, and keywords that triggered each tag; change nothing.
  * `--apply` performs the renames.
  * Tags already present in a filename are the owner's manual choice and are never removed or changed.
  * No keyword match stays untagged (the scheduler treats the episode as general and season-evergreen).
  * Episodes whose metadata could not be found are listed at the end.
  * Keyword rules live in one editable data file, not in code.
  * Cache fetched metadata next to the library so reruns do not refetch.

  Starting keyword examples (implementation is T14):

  | Keywords | Tag |
  | --- | --- |
  | snow, sled, ice | `_WINTER` |
  | moon, bedtime, sleep, stars | `_NIGHT` |
  | breakfast, wake, sunrise | `_MORNING` |
  | pumpkin, costume | `_HALLOWEEN` |

* **`python -m tv90 index`** probes every file's duration with ffprobe and writes the duration index onto the library partition. At runtime the scheduler reads that index; a file missing from it is probed in memory and never written back.

---