#!/usr/bin/env bash
# Idempotent first-run for the 90s TV box (Pi root or laptop).
# Safe to re-run: skip valid existing files, do not clobber household config.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

PI_LIBRARY_PATH="/srv/90stv/library"
PI_INTERSTITIALS_PATH="/srv/90stv/interstitials"
LAPTOP_LIBRARY_PATH="${SCRIPT_DIR}/downloads/library"
LAPTOP_INTERSTITIALS_PATH="${SCRIPT_DIR}/downloads/interstitials"
INSTALL_ROOT="/opt/90stv"
PI_VENV_DIR="${INSTALL_ROOT}/venv"
LAPTOP_VENV_DIR="${SCRIPT_DIR}/.venv"
TV90_USER="tv90"
HOSTNAME_VALUE="90stv"
FSTAB_MARKER="90stv-library-mount"
UNIT_SOURCE="${SCRIPT_DIR}/packaging/90stv.service"
UNIT_DEST="/etc/systemd/system/90stv.service"
UNIT_DROPIN_DIR="/etc/systemd/system/90stv.service.d"
UNIT_DROPIN_DEST="${UNIT_DROPIN_DIR}/paths.conf"
JOURNALD_SOURCE="${SCRIPT_DIR}/packaging/90stv-volatile.conf"
JOURNALD_DEST="/etc/systemd/journald.conf.d/90stv-volatile.conf"
MAINTENANCE_SOURCE="${SCRIPT_DIR}/scripts/tv90-maintenance"
MAINTENANCE_DEST="/usr/local/bin/tv90-maintenance"
LIBRARY_RW_SOURCE="${SCRIPT_DIR}/scripts/tv90-apply-library-mount"
LIBRARY_RW_DEST="/usr/local/bin/tv90-apply-library-mount"
LIBRARY_RW_UNIT_SOURCE="${SCRIPT_DIR}/packaging/90stv-library-rw.service"
LIBRARY_RW_UNIT_DEST="/etc/systemd/system/90stv-library-rw.service"
KIOSK_TTY_UNIT_SOURCE="${SCRIPT_DIR}/packaging/90stv-kiosk-tty.service"
KIOSK_TTY_UNIT_DEST="/etc/systemd/system/90stv-kiosk-tty.service"
OVERLAYROOT_LOCAL="/etc/overlayroot.local.conf"
# recurse=0 keeps /srv/90stv/library remountable; Bookworm default recurse=1 overlays every mount.
OVERLAYROOT_LINE='overlayroot="tmpfs:recurse=0"'

DOWNLOAD_KIPPER="${SCRIPT_DIR}/scripts/download-kipper.py"
DOWNLOAD_OSWALD="${SCRIPT_DIR}/scripts/download-oswald.py"
DOWNLOAD_HARRY="${SCRIPT_DIR}/scripts/download-harry.py"
DOWNLOAD_HOLIDAY="${SCRIPT_DIR}/scripts/download-holiday.py"
DOWNLOAD_INTERSTITIALS="${SCRIPT_DIR}/scripts/download-interstitials.py"

# Disk space: abort remote episode fetch below this floor; bumpers-only uses the smaller floor.
MIN_FREE_GIB_FULL_LIBRARY=8
MIN_FREE_GIB_BUMPERS_ONLY=1
ARCHIVE_ORG_URL="https://archive.org/"
NETWORK_TIMEOUT_SECONDS=8
MEDIA_STEP_COUNT=5
CHANNEL_FOLDERS=(ch01 ch02 ch03 ch04)
APT_PACKAGES=(
  mpv
  python3
  python3-venv
  python3-pip
  avahi-daemon
  ffmpeg
)

LIBRARY_PATH=""
INTERSTITIALS_PATH=""
VENV_DIR=""
IS_ROOT=0
IS_PI=0
SKIP_MEDIA=0
REPAIR=0
DRY_RUN=0
SKIP_REMOTE_MEDIA=0
OVERLAY_REBOOT_NEEDED=0

log() {
  printf '%s\n' "$*"
}

have_cmd() {
  command -v "$1" >/dev/null 2>&1
}

usage() {
  cat <<'EOF'
Usage: ./setup.sh [--skip-media] [--repair] [--dry-run]

  (default)   Install deps and fetch shows + channel bumpers.
  --skip-media  Provision only (Pi packages/units); skip downloads.
  --repair      Re-fetch missing/corrupt media (interstitials --repair).
  --dry-run     Pass --dry-run through to download scripts.
EOF
}

parse_args() {
  local arg
  for arg in "$@"; do
    case "${arg}" in
      --skip-media) SKIP_MEDIA=1 ;;
      --repair) REPAIR=1 ;;
      --dry-run) DRY_RUN=1 ;;
      -h | --help)
        usage
        exit 0
        ;;
      *)
        log "unknown argument: ${arg}"
        usage
        exit 1
        ;;
    esac
  done
}

is_raspberry_pi() {
  local model="/proc/device-tree/model"
  if [[ -r "${model}" ]] && grep -q "Raspberry Pi" "${model}"; then
    return 0
  fi
  # Bookworm firmware lives here; a lone directory on a laptop must not trip overlay.
  if [[ -r "${model}" && -d /boot/firmware ]] && grep -q "Raspberry Pi" "${model}"; then
    return 0
  fi
  return 1
}

detect_mode() {
  if [[ "$(id -u)" -eq 0 ]]; then
    IS_ROOT=1
  else
    IS_ROOT=0
  fi
  if is_raspberry_pi; then
    IS_PI=1
  else
    IS_PI=0
  fi
}

configure_paths() {
  if [[ "${IS_ROOT}" -eq 1 ]]; then
    LIBRARY_PATH="${PI_LIBRARY_PATH}"
    INTERSTITIALS_PATH="${PI_INTERSTITIALS_PATH}"
    VENV_DIR="${PI_VENV_DIR}"
  else
    LIBRARY_PATH="${LAPTOP_LIBRARY_PATH}"
    INTERSTITIALS_PATH="${LAPTOP_INTERSTITIALS_PATH}"
    VENV_DIR="${LAPTOP_VENV_DIR}"
  fi
}

resolve_python() {
  if [[ -x "${VENV_DIR}/bin/python3" ]]; then
    printf '%s\n' "${VENV_DIR}/bin/python3"
    return 0
  fi
  if have_cmd python3; then
    printf '%s\n' "python3"
    return 0
  fi
  return 1
}

package_is_installed() {
  dpkg -s "$1" >/dev/null 2>&1
}

ensure_packages() {
  if [[ "${IS_ROOT}" -ne 1 ]] || ! have_cmd apt-get; then
    return 0
  fi
  export DEBIAN_FRONTEND=noninteractive
  local pkg
  local missing=()
  for pkg in "${APT_PACKAGES[@]}"; do
    if ! package_is_installed "${pkg}"; then
      missing+=("${pkg}")
    fi
  done
  if ((${#missing[@]} == 0)); then
    log "packages: already installed"
    return 0
  fi
  apt-get update
  apt-get install -y "${missing[@]}"
}

ensure_user() {
  if ! id -u "${TV90_USER}" >/dev/null 2>&1; then
    useradd --system --home /srv/90stv --shell /usr/sbin/nologin "${TV90_USER}"
  fi
  usermod -aG video,audio,render,gpio "${TV90_USER}" 2>/dev/null || true
}

ensure_hostname() {
  if ! have_cmd hostnamectl; then
    log "skip hostname: hostnamectl not found"
    return 0
  fi
  hostnamectl set-hostname "${HOSTNAME_VALUE}"
  if ! grep -qE '[[:space:]]90stv([[:space:]]|$)' /etc/hosts; then
    printf '127.0.1.1 %s\n' "${HOSTNAME_VALUE}" >> /etc/hosts
  fi
}

ensure_avahi() {
  if ! have_cmd systemctl; then
    log "skip avahi: systemctl not found"
    return 0
  fi
  if ! systemctl enable avahi-daemon; then
    log "skip avahi: could not enable avahi-daemon"
    return 0
  fi
  systemctl start avahi-daemon || true
}

ensure_timesyncd() {
  # NTP only; no outbound firewall is configured.
  if have_cmd timedatectl; then
    timedatectl set-ntp true || true
  fi
  if ! have_cmd systemctl; then
    return 0
  fi
  if ! systemctl enable systemd-timesyncd; then
    log "skip timesyncd: could not enable systemd-timesyncd"
    return 0
  fi
  systemctl start systemd-timesyncd || true
}

chown_tv90_if_present() {
  if ! id -u "${TV90_USER}" >/dev/null 2>&1; then
    return 0
  fi
  local path
  for path in "$@"; do
    if [[ -e "${path}" ]]; then
      chown "${TV90_USER}:${TV90_USER}" "${path}"
    fi
  done
}

ensure_channel_folders() {
  local folder
  mkdir -p "${LIBRARY_PATH}" "${INTERSTITIALS_PATH}"
  for folder in "${CHANNEL_FOLDERS[@]}"; do
    mkdir -p "${INTERSTITIALS_PATH}/${folder}"
  done
}

ensure_folders() {
  mkdir -p /srv/90stv "${INSTALL_ROOT}" /etc/systemd/journald.conf.d
  ensure_channel_folders
  chown_tv90_if_present /srv/90stv "${LIBRARY_PATH}" "${INTERSTITIALS_PATH}"
  local folder
  for folder in "${CHANNEL_FOLDERS[@]}"; do
    chown_tv90_if_present "${INTERSTITIALS_PATH}/${folder}"
  done
}

ensure_fstab_library() {
  # Separate partition should be mounted here read-only. Device UUID is household-specific.
  if [[ ! -f /etc/fstab ]] || grep -q "${FSTAB_MARKER}" /etc/fstab; then
    return 0
  fi
  {
    printf '# %s — uncomment and set UUID after partitioning; keep ro at runtime\n' "${FSTAB_MARKER}"
    printf '# UUID=CHANGE-ME  %s  ext4  defaults,ro,noload,nofail  0  2\n' "${LIBRARY_PATH}"
  } >> /etc/fstab
}

ensure_venv() {
  if ! have_cmd python3; then
    log "python3 is required for the venv"
    exit 1
  fi
  if [[ ! -x "${VENV_DIR}/bin/python3" ]]; then
    python3 -m venv "${VENV_DIR}"
    "${VENV_DIR}/bin/pip" install --upgrade pip
  fi
  "${VENV_DIR}/bin/pip" install "${SCRIPT_DIR}"
}

unit_mentions_library_paths() {
  grep -q "TV90_LIBRARY_PATH" "${UNIT_DEST}" \
    && grep -q "TV90_INTERSTITIALS_PATH" "${UNIT_DEST}"
}

ensure_unit_path_dropin() {
  if unit_mentions_library_paths; then
    return 0
  fi
  if [[ -f "${UNIT_DROPIN_DEST}" ]] && grep -q "TV90_LIBRARY_PATH" "${UNIT_DROPIN_DEST}"; then
    return 0
  fi
  mkdir -p "${UNIT_DROPIN_DIR}"
  cat > "${UNIT_DROPIN_DEST}" <<EOF
[Service]
Environment=TV90_LIBRARY_PATH=${PI_LIBRARY_PATH}
Environment=TV90_INTERSTITIALS_PATH=${PI_INTERSTITIALS_PATH}
EOF
  log "installed unit drop-in ${UNIT_DROPIN_DEST}"
}

ensure_unit() {
  if [[ ! -f "${UNIT_DEST}" ]]; then
    install -m 644 "${UNIT_SOURCE}" "${UNIT_DEST}"
  elif cmp -s "${UNIT_SOURCE}" "${UNIT_DEST}"; then
    log "skip unit: already matches packaging"
  else
    log "keeping existing unit ${UNIT_DEST}"
    ensure_unit_path_dropin
  fi
  if have_cmd systemctl; then
    systemctl daemon-reload
    systemctl enable 90stv.service
  fi
}

ensure_journald() {
  install -m 644 "${JOURNALD_SOURCE}" "${JOURNALD_DEST}"
  if have_cmd systemctl; then
    systemctl restart systemd-journald || true
  fi
}

hdmi_alsa_card() {
  local connector card status
  for connector in HDMI-A-1 HDMI-A-2; do
    status="$(cat /sys/class/drm/*-"${connector}"/status 2>/dev/null | head -n 1 || true)"
    if [[ "${status}" == "connected" ]]; then
      if [[ "${connector}" == "HDMI-A-2" ]]; then
        printf '%s\n' "vc4hdmi1"
      else
        printf '%s\n' "vc4hdmi0"
      fi
      return 0
    fi
  done
  printf '%s\n' "vc4hdmi0"
}

ensure_hdmi_audio() {
  # ALSA card 0 is the 3.5mm jack. Video is on HDMI, so default sound must be HDMI.
  local card
  card="$(hdmi_alsa_card)"
  cat > /etc/asound.conf <<EOF
pcm.!default {
  type plug
  slave.pcm "hdmi:CARD=${card},DEV=0"
}
ctl.!default {
  type hw
  card ${card}
}
EOF
  if [[ -d /media/root-ro/etc ]]; then
    if mount -o remount,rw /media/root-ro; then
      install -m 644 /etc/asound.conf /media/root-ro/etc/asound.conf
      mount -o remount,ro /media/root-ro || true
    fi
  fi
  log "audio: ALSA default is HDMI (${card}), not the headphone jack"
}

ensure_kiosk() {
  if [[ "${IS_PI}" -ne 1 ]]; then
    log "skip kiosk: not a Raspberry Pi (systemd + mpv --force-window --fullscreen is the kiosk)"
    return 0
  fi
  if ! have_cmd systemctl; then
    return 0
  fi
  # Headless: no desktop/cursor fallback. mpv fullscreen is the picture.
  ensure_hdmi_audio
  systemctl set-default multi-user.target
  local dm
  for dm in lightdm gdm3 sddm greetd; do
    if systemctl list-unit-files "${dm}.service" >/dev/null 2>&1; then
      systemctl disable "${dm}.service" >/dev/null 2>&1 || true
      systemctl stop "${dm}.service" >/dev/null 2>&1 || true
    fi
  done
  # getty-generator always starts a login on tty1. That TTY hangup makes
  # 90stv.service start and immediately deactivate in a loop. Overlay can
  # discard a persistent /etc mask, so also install a boot oneshot that
  # applies a /run mask before getty starts.
  install -m 644 "${KIOSK_TTY_UNIT_SOURCE}" "${KIOSK_TTY_UNIT_DEST}"
  systemctl daemon-reload
  systemctl enable 90stv-kiosk-tty.service
  systemctl mask getty@tty1.service >/dev/null 2>&1 || true
  systemctl mask autovt@tty1.service >/dev/null 2>&1 || true
  systemctl stop getty@tty1.service >/dev/null 2>&1 || true
  systemctl stop autovt@tty1.service >/dev/null 2>&1 || true
  persist_kiosk_on_real_root
}

persist_kiosk_on_real_root() {
  local dest_dir="/media/root-ro/etc/systemd/system"
  if [[ ! -d "${dest_dir}" ]]; then
    return 0
  fi
  if ! mount -o remount,rw /media/root-ro; then
    log "skip kiosk persist: could not remount /media/root-ro read-write"
    return 0
  fi
  install -m 644 "${KIOSK_TTY_UNIT_SOURCE}" "${dest_dir}/90stv-kiosk-tty.service"
  mkdir -p "${dest_dir}/multi-user.target.wants"
  ln -sfn /etc/systemd/system/90stv-kiosk-tty.service \
    "${dest_dir}/multi-user.target.wants/90stv-kiosk-tty.service"
  ln -sfn /dev/null "${dest_dir}/getty@tty1.service"
  ln -sfn /dev/null "${dest_dir}/autovt@tty1.service"
  mount -o remount,ro /media/root-ro || true
  log "kiosk: persisted getty mask under overlay (/media/root-ro)"
}

start_tv_service() {
  if [[ "${IS_ROOT}" -ne 1 || "${IS_PI}" -ne 1 ]]; then
    return 0
  fi
  if ! have_cmd systemctl; then
    return 0
  fi
  if [[ -e "${LIBRARY_PATH}/.tv90-maintenance" ]]; then
    log "skip start: maintenance flag present"
    return 0
  fi
  systemctl reset-failed 90stv.service >/dev/null 2>&1 || true
  systemctl start 90stv.service || true
  if systemctl is-active --quiet 90stv.service; then
    log "90stv.service is running — the TV should show a calm green slate, not a login"
  else
    log "90stv.service did not stay up; from a laptop run: journalctl -u 90stv.service -n 50"
  fi
}

raspi_config_nonint() {
  local command_name="$1"
  if ! command -v raspi-config >/dev/null 2>&1; then
    log "skip ${command_name}: raspi-config not found"
    return 0
  fi
  if raspi-config nonint "${command_name}"; then
    return 0
  fi
  log "skip ${command_name}: raspi-config does not support this command on this image"
  return 0
}

ensure_overlayroot_local() {
  if [[ -f "${OVERLAYROOT_LOCAL}" ]] && grep -q 'overlayroot=' "${OVERLAYROOT_LOCAL}"; then
    return 0
  fi
  printf '%s\n' "${OVERLAYROOT_LINE}" > "${OVERLAYROOT_LOCAL}"
  OVERLAY_REBOOT_NEEDED=1
}

ensure_maintenance() {
  install -m 755 "${MAINTENANCE_SOURCE}" "${MAINTENANCE_DEST}"
  install -m 755 "${LIBRARY_RW_SOURCE}" "${LIBRARY_RW_DEST}"
  install -m 644 "${LIBRARY_RW_UNIT_SOURCE}" "${LIBRARY_RW_UNIT_DEST}"
  if have_cmd systemctl; then
    systemctl daemon-reload
    systemctl enable 90stv-library-rw.service
  fi
}

ensure_overlay() {
  if [[ "${IS_PI}" -ne 1 ]]; then
    log "skip overlay: not a Raspberry Pi (device-tree / /boot/firmware)"
    return 0
  fi
  ensure_overlayroot_local
  raspi_config_nonint enable_overlayfs
  raspi_config_nonint enable_bootro
  if ! overlay_is_active; then
    OVERLAY_REBOOT_NEEDED=1
  fi
}

overlay_is_active() {
  if [[ -r /proc/mounts ]] && awk '$2 == "/" { print $3 }' /proc/mounts | grep -q overlay; then
    return 0
  fi
  return 1
}

overlay_should_enable() {
  if [[ "${IS_PI}" -ne 1 ]]; then
    return 1
  fi
  if [[ "${SKIP_MEDIA}" -eq 1 ]]; then
    return 0
  fi
  if [[ "$(count_health_hits)" -eq 3 && "$(count_bumper_channels)" -eq 3 ]]; then
    return 0
  fi
  return 1
}

library_has_any_episode() {
  [[ -d "${LIBRARY_PATH}" ]] || return 1
  compgen -G "${LIBRARY_PATH}/*.mp4" >/dev/null \
    || compgen -G "${LIBRARY_PATH}/*.mkv" >/dev/null \
    || compgen -G "${LIBRARY_PATH}/*.avi" >/dev/null
}

note_existing_install() {
  if [[ -x "${VENV_DIR}/bin/python3" ]] && library_has_any_episode; then
    log "existing installation detected; skip valid existing files, only fill gaps"
  fi
}

require_python3() {
  if ! have_cmd python3; then
    log "python3 is required"
    exit 1
  fi
  # Bookworm ships 3.11; Trixie ships 3.13. Use distro python3, not a pinned package.
  if ! python3 -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)'; then
    log "python3 3.11 or newer is required (found $(python3 --version))"
    exit 1
  fi
}

preflight_commands() {
  require_python3
  if [[ "${SKIP_MEDIA}" -eq 1 ]]; then
    return 0
  fi
  if ! have_cmd ffmpeg; then
    log "ffmpeg not found; channel bumpers need ffmpeg (install it or expect missing interstitials)"
  fi
  if ! have_cmd ffprobe; then
    log "ffprobe not found; duration index needs ffprobe"
  fi
}

free_kib_on() {
  local dest="$1"
  local probe="${dest}"
  while [[ ! -d "${probe}" ]]; do
    probe="$(dirname "${probe}")"
  done
  df -Pk "${probe}" | awk 'NR==2 { print $4 }'
}

check_disk_space() {
  local free_kib
  local need_full_kib=$((MIN_FREE_GIB_FULL_LIBRARY * 1024 * 1024))
  local need_bumper_kib=$((MIN_FREE_GIB_BUMPERS_ONLY * 1024 * 1024))
  mkdir -p "${LIBRARY_PATH}" "${INTERSTITIALS_PATH}"
  free_kib="$(free_kib_on "${LIBRARY_PATH}")"
  log "disk: ${free_kib} KiB free on $(dirname "${LIBRARY_PATH}") (need ${MIN_FREE_GIB_FULL_LIBRARY} GiB for full library)"
  if [[ "${free_kib}" -lt "${need_bumper_kib}" ]]; then
    log "disk: less than ${MIN_FREE_GIB_BUMPERS_ONLY} GiB free; skip media"
    SKIP_MEDIA=1
    return 0
  fi
  if [[ "${SKIP_REMOTE_MEDIA}" -eq 0 && "${free_kib}" -lt "${need_full_kib}" ]]; then
    log "disk: less than ${MIN_FREE_GIB_FULL_LIBRARY} GiB free; skip remote episode downloads, still generate bumpers"
    SKIP_REMOTE_MEDIA=1
  fi
}

archive_org_reachable() {
  local python
  python="$(resolve_python)"
  "${python}" - "${NETWORK_TIMEOUT_SECONDS}" "${ARCHIVE_ORG_URL}" <<'PY'
import sys
import urllib.error
import urllib.request

timeout = int(sys.argv[1])
url = sys.argv[2]
request = urllib.request.Request(url, method="HEAD")
try:
    urllib.request.urlopen(request, timeout=timeout)
except Exception:
    request = urllib.request.Request(url, method="GET")
    try:
        urllib.request.urlopen(request, timeout=timeout)
    except (urllib.error.URLError, TimeoutError, OSError):
        sys.exit(1)
PY
}

check_network() {
  if archive_org_reachable; then
    log "network: archive.org reachable"
    return 0
  fi
  log "network: archive.org unreachable; skip remote episode downloads (interstitials are local ffmpeg)"
  SKIP_REMOTE_MEDIA=1
}

run_python_script() {
  local script="$1"
  shift
  local python
  python="$(resolve_python)"
  if ! "${python}" "${script}" "$@"; then
    log "download failed: ${script} (keeping existing files)"
    return 0
  fi
}

run_show_download() {
  local script="$1"
  if [[ "${DRY_RUN}" -eq 1 ]]; then
    run_python_script "${script}" --dest "${LIBRARY_PATH}" --dry-run
  else
    run_python_script "${script}" --dest "${LIBRARY_PATH}"
  fi
}

fetch_remote_shows() {
  log "media [1/${MEDIA_STEP_COUNT}] Kipper → ${LIBRARY_PATH}"
  run_show_download "${DOWNLOAD_KIPPER}"
  log "media [2/${MEDIA_STEP_COUNT}] Oswald → ${LIBRARY_PATH}"
  run_show_download "${DOWNLOAD_OSWALD}"
  log "media [3/${MEDIA_STEP_COUNT}] Harry → ${LIBRARY_PATH}"
  run_show_download "${DOWNLOAD_HARRY}"
  log "media [4/${MEDIA_STEP_COUNT}] Holiday → ${LIBRARY_PATH}"
  run_show_download "${DOWNLOAD_HOLIDAY}"
}

fetch_interstitials() {
  log "media [5/${MEDIA_STEP_COUNT}] interstitials → ${INTERSTITIALS_PATH} (ch01–ch04, not the episode library)"
  if ! have_cmd ffmpeg && [[ "${DRY_RUN}" -ne 1 ]]; then
    log "skip interstitials: ffmpeg not found"
    return 0
  fi
  set -- "${DOWNLOAD_INTERSTITIALS}" --dest "${INTERSTITIALS_PATH}"
  if [[ "${DRY_RUN}" -eq 1 ]]; then
    set -- "$@" --dry-run
  fi
  if [[ "${REPAIR}" -eq 1 ]]; then
    set -- "$@" --repair
  fi
  run_python_script "$@"
}

fetch_content() {
  if overlay_is_active; then
    log "overlay is active; skip media (writes would not last). sudo tv90-maintenance on, then re-run setup.sh"
    return 0
  fi
  ensure_channel_folders
  check_network
  check_disk_space
  if [[ "${SKIP_MEDIA}" -eq 1 ]]; then
    log "skip media (disk floor)"
    return 0
  fi
  if [[ "${SKIP_REMOTE_MEDIA}" -eq 1 ]]; then
    log "skip remote episode downloads"
  else
    fetch_remote_shows
  fi
  fetch_interstitials
  if [[ "${IS_ROOT}" -eq 1 ]]; then
    chown_tv90_if_present "${LIBRARY_PATH}" "${INTERSTITIALS_PATH}"
    local folder
    for folder in "${CHANNEL_FOLDERS[@]}"; do
      chown_tv90_if_present "${INTERSTITIALS_PATH}/${folder}"
    done
    if id -u "${TV90_USER}" >/dev/null 2>&1 && [[ "${DRY_RUN}" -ne 1 ]]; then
      chown -R "${TV90_USER}:${TV90_USER}" "${LIBRARY_PATH}" "${INTERSTITIALS_PATH}" || true
    fi
  fi
}

index_library() {
  if [[ "${DRY_RUN}" -eq 1 ]]; then
    return 0
  fi
  if overlay_is_active; then
    return 0
  fi
  if ! library_has_any_episode; then
    log "skip index: no episode files in ${LIBRARY_PATH}"
    return 0
  fi
  if ! have_cmd ffprobe; then
    log "skip index: ffprobe not found"
    return 0
  fi
  local python
  python="$(resolve_python)"
  if ! "${python}" -c "import tv90" >/dev/null 2>&1; then
    log "skip index: tv90 is not importable"
    return 0
  fi
  log "index durations: ${python} -m tv90 index --library ${LIBRARY_PATH}"
  if ! "${python}" -m tv90 index --library "${LIBRARY_PATH}"; then
    log "index failed (library files kept)"
  fi
  log "tag remains manual (dry-run, needs TVMaze): ${python} -m tv90 tag --library ${LIBRARY_PATH}"
}

prefix_present() {
  local prefix="$1"
  [[ -d "${LIBRARY_PATH}" ]] && compgen -G "${LIBRARY_PATH}/${prefix}*" >/dev/null
}

channel_has_mp4() {
  local channel="$1"
  [[ -d "${INTERSTITIALS_PATH}/${channel}" ]] \
    && compgen -G "${INTERSTITIALS_PATH}/${channel}/*.mp4" >/dev/null
}

count_health_hits() {
  local n=0
  prefix_present "Kipper_" && n=$((n + 1))
  prefix_present "Oswald_" && n=$((n + 1))
  prefix_present "Harry_" && n=$((n + 1))
  printf '%s\n' "${n}"
}

count_bumper_channels() {
  local n=0
  local channel
  for channel in ch01 ch02 ch03; do
    if channel_has_mp4 "${channel}"; then
      n=$((n + 1))
    fi
  done
  printf '%s\n' "${n}"
}

print_health_line() {
  local ok_label="$1"
  local missing_label="$2"
  shift 2
  if "$@"; then
    log "health: ${ok_label}"
    return 0
  fi
  log "health: missing ${missing_label}"
  return 1
}

health_check() {
  local python
  local ready=1
  local show_hits
  local bumper_hits
  python="$(resolve_python)" || python="python3"

  log "=== health ==="
  if "${python}" -c "import tv90" >/dev/null 2>&1; then
    log "health: python import tv90 ok"
  else
    log "health: missing python import tv90"
    ready=0
  fi

  print_health_line "Kipper_ present" "Kipper_ files" prefix_present "Kipper_" || ready=0
  print_health_line "Oswald_ present" "Oswald_ files" prefix_present "Oswald_" || ready=0
  print_health_line "Harry_ present" "Harry_ files" prefix_present "Harry_" || ready=0
  print_health_line "interstitials ch01 mp4" "interstitials/ch01 mp4" channel_has_mp4 ch01 || ready=0
  print_health_line "interstitials ch02 mp4" "interstitials/ch02 mp4" channel_has_mp4 ch02 || ready=0
  print_health_line "interstitials ch03 mp4" "interstitials/ch03 mp4" channel_has_mp4 ch03 || ready=0

  if [[ "${IS_ROOT}" -eq 1 && "${IS_PI}" -eq 1 ]]; then
    if have_cmd systemctl && systemctl is-enabled 90stv.service >/dev/null 2>&1; then
      log "health: 90stv.service enabled"
    else
      log "health: missing enabled 90stv.service"
      ready=0
    fi
    if have_cmd systemctl && systemctl is-enabled 90stv-kiosk-tty.service >/dev/null 2>&1; then
      log "health: 90stv-kiosk-tty.service enabled"
    else
      log "health: missing enabled 90stv-kiosk-tty.service"
      ready=0
    fi
    if have_cmd systemctl && systemctl is-active --quiet getty@tty1.service; then
      log "health: missing masked getty@tty1 (login still active)"
      ready=0
    else
      log "health: getty@tty1 inactive"
    fi
  fi

  show_hits="$(count_health_hits)"
  bumper_hits="$(count_bumper_channels)"

  if [[ "${ready}" -eq 1 ]]; then
    log "READY"
    return 0
  fi

  if [[ "${IS_ROOT}" -eq 1 && "${IS_PI}" -eq 1 && "${SKIP_MEDIA}" -eq 0 ]]; then
    if [[ "${show_hits}" -eq 0 && "${bumper_hits}" -eq 0 ]]; then
      log "NOT READY"
      return 1
    fi
  fi
  log "NOT READY (partial)"
  return 0
}

print_next_steps() {
  local python
  python="$(resolve_python)" || python="python3"
  if [[ "${IS_ROOT}" -eq 1 ]]; then
    log "setup complete: hostname ${HOSTNAME_VALUE}, library ${LIBRARY_PATH}, interstitials ${INTERSTITIALS_PATH}, user ${TV90_USER}"
    if [[ "${IS_PI}" -eq 1 ]]; then
      log "the TV should show a calm green slate — not a desktop, cursor, or 90stv login:"
      log "phone remote: http://90stv.local:5000  then tap CHANNEL UP"
      if [[ "${OVERLAY_REBOOT_NEEDED}" -eq 1 ]]; then
        log "next step: sudo reboot so overlayroot takes effect, then confirm with sudo tv90-maintenance status"
      fi
    fi
  else
    log "laptop setup complete (no systemd/hostname/overlay)"
    log "library: ${LIBRARY_PATH}"
    log "interstitials: ${INTERSTITIALS_PATH}"
    log "venv: ${VENV_DIR}"
    log "run: ${python} -m tv90 simulate --date YYYY-MM-DD --library ${LIBRARY_PATH}"
  fi
  log "index: ${python} -m tv90 index --library ${LIBRARY_PATH}"
  log "tag (dry-run, not applied by setup): ${python} -m tv90 tag --library ${LIBRARY_PATH}"
}

provision_root() {
  ensure_packages
  preflight_commands
  ensure_user
  ensure_hostname
  ensure_avahi
  ensure_timesyncd
  ensure_folders
  ensure_fstab_library
  ensure_venv
  ensure_unit
  ensure_journald
  ensure_kiosk
  ensure_maintenance
}

provision_laptop() {
  preflight_commands
  ensure_channel_folders
  ensure_venv
}

main() {
  parse_args "$@"
  detect_mode
  configure_paths
  if [[ "${IS_PI}" -eq 1 && "${IS_ROOT}" -ne 1 ]]; then
    log "This is a Raspberry Pi. Run: sudo ./setup.sh"
    log "Without sudo, files download here but the TV service is not installed and the screen stays on a login."
    exit 1
  fi
  if [[ "${IS_ROOT}" -eq 1 ]]; then
    if [[ "${IS_PI}" -eq 1 ]]; then
      log "mode: Pi root"
    else
      log "mode: root, not a Raspberry Pi (skip overlay/kiosk)"
    fi
    provision_root
  else
    log "mode: non-root / laptop (skip systemd/hostname/overlay)"
    provision_laptop
  fi
  note_existing_install
  if [[ "${SKIP_MEDIA}" -eq 1 ]]; then
    log "skip media (--skip-media)"
  else
    fetch_content
    index_library
  fi
  if [[ "${IS_ROOT}" -eq 1 ]]; then
    if overlay_should_enable; then
      ensure_overlay
    else
      log "skip overlay until Kipper, Oswald, Harry, and ch01–ch03 bumpers are present (re-run setup.sh after a full fetch, or use --skip-media)"
    fi
  fi
  print_next_steps
  start_tv_service
  health_check
}

main "$@"
