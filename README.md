# 90s Cable TV Nostalgia Box: Final Project Requirements Document

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
* **Wall-Clock Live TV Sync:** Channels operate on continuous loop schedules calculated from Unix Epoch time. Switching channels immediately jumps to the exact calculated timestamp where the target show is currently "airing live" in the background.
* **Retro On-Screen Display (OSD):** Styled with a neon-green (`#00FF00`) blocky monospace CRT font displaying channel banners (e.g., `CH 03`) for 3 seconds upon channel changes, alongside horizontal segmented volume bars during audio adjustments.
* **Channel Tuning Effect:** A brief 150ms static/noise burst or black frame plays during channel changes to simulate analog tuner signal acquisition.

---

### 4. Content Scheduling & Time-Aware Engine

* **Curated 32GB Cartoon Library:** Optimized for gentle, calm, low-sensory 90s/2000s shows for ages 2 (*🐻 Little Bear*, *🐙 Oswald the Octopus*, *🦕 Harry and His Bucket Full of Dinosaurs*). Files utilize suffix tags (e.g., `_WINTER.mp4`) for automated metadata parsing without requiring complex folder structures.
* **Statistical Time-of-Day Distribution:** Uses Gaussian probability curves anchored to the system clock to prioritize content dynamically—peaking morning wake-up shows at 8:00 AM ($\mu = 8.0$), bedtime wind-down episodes at 8:00 PM ($\mu = 20.0$), and spreading general daytime shows across the afternoon.
* **4-Season Ambient Synchronization:** Maps the current calendar month to meteorological seasons (Spring: Mar–May, Summer: Jun–Aug, Autumn: Sep–Nov, Winter: Dec–Feb). Episodes matching the active season's file tag receive an 80% selection probability, ensuring on-screen weather and themes naturally reflect the real world outside.
* **Seasonal Holiday Engine (Lead-Up vs. Event Day):** Overrides the ambient season engine for specific dates. Applies a progressive multiplier ($25\%\text{--}50\%$) during the two-week lead-up to build anticipation, then switches to a **strict 100% holiday override** on the exact holiday date (e.g., Oct 31, Dec 24–25) to replicate authentic, all-day 90s broadcast marathons.
* **Anti-Repeat Cooldown & Weight Selection:** Multiplies time, season, and holiday scores by a recency factor ($R$) that blocks the last 3 played episodes ($R = 0$) and penalizes the last 10 ($R = 0.15$). The final formula ($\text{Weight} = W_{\text{time}} \times W_{\text{season}} \times M_{\text{holiday}} \times R$) drives selection, while an **HDMI-CEC sleep timer** automatically powers off the display after a set block for a seamless transition to family time.

---

### 5. Remote Control, Web UI & Safety Controls

* **Smartphone / Tablet Web Remote:** An embedded lightweight Flask/FastAPI web server accessible over home Wi-Fi at `[http://90stv.local:5000](http://90stv.local:5000)` (or local IP). The interface features large touch buttons for `CHANNEL UP`, `CHANNEL DOWN`, `VOLUME UP`, `VOLUME DOWN`, and a "Now Playing" display.
* **Physical USB Remote Integration:** USB remote inputs map directly to MPV player controls without needing a desktop manager.
* **Input Debouncing:** Enforces a 500ms command cooldown to ignore rapid toddler button mashing.
* **Hardware Audio Ceiling:** Hard-codes a maximum audio output limit (e.g., 65% ALSA volume) to protect hardware and child hearing.
* **HDMI-CEC Sleep Scheduling:** Sends HDMI-CEC commands to turn off/standby the television display at a set bedtime (e.g., 7:30 PM) and ignores inputs until a set morning wake time (e.g., 6:30 AM).

---