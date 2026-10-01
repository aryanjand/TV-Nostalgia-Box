# 90s Cable TV Nostalgia Box: Final Project Requirements Document

### Design North Star

Unlike YouTube or Netflix, this box is not engineered for watch time, click-through, or a dopamine loop. It is a **safe, passive routine** for a 2-year-old: cognitive calm, developmental consistency, and stress-free entertainment. Script and library architecture must prioritize the following over engagement metrics.

1. **Minimal cognitive stimulation (slow pacing).** Fast-cut, high-energy feeds (Cocomelon-style flashes, unboxings) hyper-focus attention and leave kids irritable. The library is *Little Bear*, *Oswald*, and *Harry and His Bucket Full of Dinosaurs* — slow camera, visual stillness, quiet music. Do not add high-stimulation titles to “fill the card.”
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
* **Physical Controller:** 2.4GHz USB Wireless Remote / Air Mouse with a dedicated USB receiver dongle.

---

### 2. System Architecture & Provisioning

* **Automated Provisioning Script:** A single Bash setup script (`setup.sh`) automates system updates, installs dependencies (`mpv`, `flask`, `avahi-daemon`), assigns the hostname (`90stv`), configures local mDNS discovery, and sets up project folders.
* **Systemd Daemon Service:** The application runs as a background service (`90stv.service`) with `Restart=always` to guarantee immediate startup on power-up and automatic recovery if a process exits unexpectedly.
* **Headless Kiosk Boot:** The device boots directly into the live television video stream upon receiving power—bypassing user logins, desktop environments, and command-line text to mimic an arcade machine or classic TV set.
* **Air-Gapped Operation:** The system operates 100% offline from local SD card storage without external internet dependencies.

---

### 3. Video Playback & Display Interface

* **Rendering Backend:** MPV controlled via Python.
* **Wall-Clock Live TV Sync:** Each channel airs a **daypart-aware daily timeline** (see §4). Switching channels jumps to the file + timestamp that station is broadcasting *right now* — including morning vs night weighting — not a fresh random draw.
* **Retro On-Screen Display (OSD):** Styled with a neon-green (`#00FF00`) blocky monospace CRT font displaying channel banners (e.g., `CH 03`) for 3 seconds upon channel changes, alongside horizontal segmented volume bars during audio adjustments.
* **Channel Tuning Effect:** A brief 150ms static/noise burst or black frame plays during channel changes to simulate analog tuner signal acquisition.

---

### 4. Content Scheduling & Time-Aware Engine

The scheduler is how the north star becomes code: **which episode of the current friend** is on, given clock, season, and holiday — never which new video to chase. CH 01–03 stay one show each. Time-of-day Gaussians bias *morning-tagged episodes to the morning* and *night-tagged episodes to the evening* inside that show. They do not mix Little Bear against Oswald (that would be a feed).

* **Closed 3-Show Library (~140 episodes):** Three dedicated cartoon channels, one show each, on the 32GB card. No search, no related videos, no growing catalog.

  | Channel | Show | Role on the box |
  | --- | --- | --- |
  | **CH 01** | *Little Bear* | Slow pans, quiet woods, low sensory load |
  | **CH 02** | *Oswald* | Gentle city strolls, classical-leaning music |
  | **CH 03** | *Harry and His Bucket Full of Dinosaurs* | Familiar friend + simple pretend-play loop |
  | **CH 04** | Holiday movies | **Ghost channel** — not in the lineup except during a holiday window |

* **Zero Decision Fatigue:** No episode menus, thumbnails, or "Up Next." Default experience is **power on → already playing.** The physical/web remote only changes **channel** and **volume** (adult override, not a library). Channel-up wraps `01 → 02 → 03 → (04 if live) → 01`. The toddler-facing rule remains: TV is on (gentle surprise) or off.

* **Filename Tags, Flat Library:** Single folder. The scheduler parses suffixes:

  * Show stem: `LittleBear_…`, `Oswald_…`, `Harry_…`, `Holiday_…`.
  * Daypart: `_MORNING`, `_NIGHT` (omit = **general** — equal chance at midday). Optional `_DAY` is treated the same as untagged.
  * Season: `_SPRING`, `_SUMMER`, `_AUTUMN`, `_WINTER` (omit = season-evergreen).
  * Holiday: `_HALLOWEEN`, `_THANKSGIVING`, `_CHRISTMAS`, `_EASTER`.
  * Example: `LittleBear_S01E04_MORNING_WINTER.mp4`, `Oswald_S01E09_NIGHT.mp4`, `Holiday_Rudolph_CHRISTMAS.mp4`.

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

* **Night lock — 9:00 PM:** Hard stop at **21:00 local**. The engine will not start a new episode at or after 9:00 PM. HDMI-CEC standby (§5) matches this lock. This is the only hard time gate; morning/night Gaussians stay probabilistic.

* **4-Season Ambient Sync (within each show):** Month → meteorological season (Spring Mar–May, Summer Jun–Aug, Autumn Sep–Nov, Winter Dec–Feb). Current-season tags get ~80% of seasonal weight; season-evergreen fills the rest; wrong-season is down-weighted (snowy Little Bear is rare in July), not deleted. Screen weather should mostly match the trees outside.

* **Holiday Engine — two layers:**

  * **Layer A — regular channels (lead-up):** Two weeks before a mapped holiday, holiday-tagged *episodes of that show* get a progressive multiplier (~1.25 → 1.50). The three friends stay on CH 01–03; they start “noticing” the holiday.
  * **Layer B — CH 04 ghost channel:** Exists only inside the window. Closed, familiar movie set for that occasion (repeat the same few titles). Movies stay on CH 04; cartoons stay on 01–03. CH 04 **ignores $W_{\text{time}}$** unless a movie is explicitly daypart-tagged (most are not). **Event days** (Oct 31, Thanksgiving, Dec 24–25, Easter Sunday) max Layer A on CH 01–03 and leave CH 04 as the movie marathon. When the window ends, CH 04 drops out of the wrap; a leftover CH 04 press lands on CH 01.

  | Holiday | Window (CH 04 visible) | Event-day marathon |
  | --- | --- | --- |
  | Halloween | Oct 18–31 | Oct 31 |
  | Thanksgiving (US) | Mon of that week → Thursday | Thanksgiving Day |
  | Christmas | Dec 11 – Dec 26 | Dec 24–25 |
  | Easter | 14 days before → Easter Sunday | Easter Sunday |

* **Anti-Repeat & Final Weight (per channel):** Same *show* on purpose; not the same *file* twice in an hour. Recency $R$ is per channel: last 3 blocked ($R = 0$), last 10 penalized ($R = 0.15$). For each slot at time $t$:

  $$\text{Weight} = W_{\text{time}}(t) \times W_{\text{season}} \times M_{\text{holiday}} \times R$$

* **Station sign-on / sign-off:** Broadcast day e.g. 6:30 AM – **9:00 PM** (night lock). Outside that window the engine does not start another episode; HDMI-CEC standby (§5) owns bedtime. On or off — never an infinite next-up queue.

---

### 5. Remote Control, Web UI & Safety Controls

* **Smartphone / Tablet Web Remote:** An embedded lightweight Flask/FastAPI web server accessible over home Wi-Fi at `[http://90stv.local:5000](http://90stv.local:5000)` (or local IP). The interface features large touch buttons for `CHANNEL UP`, `CHANNEL DOWN`, `VOLUME UP`, `VOLUME DOWN`, and a "Now Playing" display.
* **Physical USB Remote Integration:** USB remote inputs map directly to MPV player controls without needing a desktop manager.
* **Input Debouncing:** Enforces a 500ms command cooldown to ignore rapid toddler button mashing.
* **Hardware Audio Ceiling:** Hard-codes a maximum audio output limit (e.g., 65% ALSA volume) to protect hardware and child hearing.
* **HDMI-CEC Sleep Scheduling:** Sends HDMI-CEC commands to turn off/standby the television at the **9:00 PM night lock** and ignores inputs until morning sign-on (e.g., 6:30 AM).

---