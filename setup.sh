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
OVERLAYROOT_LOCAL="/etc/overlayroot.local.conf"
# recurse=0 keeps /srv/90stv/library remountable; Bookworm default recurse=1 overlays every mount.
OVERLAYROOT_LINE='overlayroot="tmpfs:recurse=0"'

DOWNLOAD_LITTLE_BEAR="${SCRIPT_DIR}/scripts/download-little-bear.py"
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
  python3.11
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

ensure_kiosk() {
  if [[ "${IS_PI}" -ne 1 ]]; then
    log "skip kiosk: not a Raspberry Pi (systemd + mpv --force-window --fullscreen is the kiosk)"
    return 0
  fi
  if ! have_cmd systemctl; then
    return 0
  fi
  # Headless: no desktop/cursor fallback. mpv fullscreen is the picture.
  systemctl set-default multi-user.target
  local dm
  for dm in lightdm gdm3 sddm; do
    if systemctl list-unit-files "${dm}.service" >/dev/null 2>&1; then
      systemctl disable "${dm}.service" >/dev/null 2>&1 || true
      systemctl stop "${dm}.service" >/dev/null 2>&1 || true
    fi
  done
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
  log "media [1/${MEDIA_STEP_COUNT}] Little Bear → ${LIBRARY_PATH}"
  run_show_download "${DOWNLOAD_LITTLE_BEAR}"
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
  prefix_present "LittleBear_" && n=$((n + 1))
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

  print_health_line "LittleBear_ present" "LittleBear_ files" prefix_present "LittleBear_" || ready=0
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
    if [[ "${IS_PI}" -eq 1 && "${OVERLAY_REBOOT_NEEDED}" -eq 1 ]]; then
      log "next step: reboot so overlayroot takes effect, then confirm with sudo tv90-maintenance status"
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
    ensure_overlay
  fi
  print_next_steps
  health_check
}

main "$@"
