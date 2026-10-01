#!/usr/bin/env bash
# Idempotent Raspberry Pi OS Bookworm provisioning for the 90s TV box.
# Safe-ish to run twice: folders, fstab markers, and unit copies overwrite in place.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LIBRARY_PATH="/srv/90stv/library"
INSTALL_ROOT="/opt/90stv"
VENV_DIR="${INSTALL_ROOT}/venv"
TV90_USER="tv90"
HOSTNAME_VALUE="90stv"
FSTAB_MARKER="90stv-library-mount"
UNIT_SOURCE="${SCRIPT_DIR}/packaging/90stv.service"
UNIT_DEST="/etc/systemd/system/90stv.service"
JOURNALD_SOURCE="${SCRIPT_DIR}/packaging/90stv-volatile.conf"
JOURNALD_DEST="/etc/systemd/journald.conf.d/90stv-volatile.conf"
OVERLAYROOT_LOCAL="/etc/overlayroot.local.conf"
# recurse=0 keeps /srv/90stv/library remountable; Bookworm default recurse=1 overlays every mount.
OVERLAYROOT_LINE='overlayroot="tmpfs:recurse=0"'

log() {
  printf '%s\n' "$*"
}

require_root() {
  if [[ "$(id -u)" -ne 0 ]]; then
    log "setup.sh must run as root on the Pi"
    exit 1
  fi
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

ensure_packages() {
  export DEBIAN_FRONTEND=noninteractive
  apt-get update
  apt-get install -y \
    mpv \
    python3 \
    python3-venv \
    python3-pip \
    python3.11 \
    avahi-daemon \
    ffmpeg \
    cec-utils
}

ensure_user() {
  if ! id -u "${TV90_USER}" >/dev/null 2>&1; then
    useradd --system --home /srv/90stv --shell /usr/sbin/nologin "${TV90_USER}"
  fi
  usermod -aG video,audio,render,gpio "${TV90_USER}" 2>/dev/null || true
}

ensure_hostname() {
  hostnamectl set-hostname "${HOSTNAME_VALUE}"
  if ! grep -qE '[[:space:]]90stv([[:space:]]|$)' /etc/hosts; then
    printf '127.0.1.1 %s\n' "${HOSTNAME_VALUE}" >> /etc/hosts
  fi
}

ensure_avahi() {
  systemctl enable avahi-daemon
  systemctl start avahi-daemon
}

ensure_timesyncd() {
  # NTP only; no outbound firewall is configured.
  timedatectl set-ntp true || true
  systemctl enable systemd-timesyncd
  systemctl start systemd-timesyncd
}

ensure_folders() {
  mkdir -p /srv/90stv "${LIBRARY_PATH}" "${INSTALL_ROOT}" /etc/systemd/journald.conf.d
  chown "${TV90_USER}:${TV90_USER}" /srv/90stv "${LIBRARY_PATH}"
}

ensure_fstab_library() {
  # Separate partition should be mounted here read-only. Device UUID is household-specific.
  if grep -q "${FSTAB_MARKER}" /etc/fstab; then
    return 0
  fi
  {
    printf '# %s — uncomment and set UUID after partitioning; keep ro at runtime\n' "${FSTAB_MARKER}"
    printf '# UUID=CHANGE-ME  %s  ext4  defaults,ro,noload,nofail  0  2\n' "${LIBRARY_PATH}"
  } >> /etc/fstab
}

ensure_venv() {
  if [[ ! -x "${VENV_DIR}/bin/python3" ]]; then
    python3 -m venv "${VENV_DIR}"
  fi
  "${VENV_DIR}/bin/pip" install --upgrade pip
  "${VENV_DIR}/bin/pip" install "${SCRIPT_DIR}"
}

ensure_unit() {
  install -m 644 "${UNIT_SOURCE}" "${UNIT_DEST}"
  systemctl daemon-reload
  systemctl enable 90stv.service
}

ensure_journald() {
  install -m 644 "${JOURNALD_SOURCE}" "${JOURNALD_DEST}"
  systemctl restart systemd-journald || true
}

ensure_kiosk() {
  if ! is_raspberry_pi; then
    log "skip kiosk: not a Raspberry Pi (systemd + mpv --force-window --fullscreen is the kiosk)"
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
}

ensure_overlay() {
  if ! is_raspberry_pi; then
    log "skip overlay: not a Raspberry Pi (device-tree / /boot/firmware)"
    return 0
  fi
  ensure_overlayroot_local
  raspi_config_nonint enable_overlayfs
  raspi_config_nonint enable_bootro
}

main() {
  require_root
  ensure_packages
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
  ensure_overlay
  log "setup complete: hostname ${HOSTNAME_VALUE}, library ${LIBRARY_PATH}, user ${TV90_USER}"
}

main "$@"
