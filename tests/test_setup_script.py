from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SETUP_SCRIPT = (REPO / "setup.sh").read_text(encoding="utf-8")
UNIT_FILE = (REPO / "packaging" / "90stv.service").read_text(encoding="utf-8")
LIBRARY_RW_UNIT = (REPO / "packaging" / "90stv-library-rw.service").read_text(
    encoding="utf-8"
)
APPLY_LIBRARY_MOUNT = (REPO / "scripts" / "tv90-apply-library-mount").read_text(
    encoding="utf-8"
)
JOURNALD_DROPIN = (REPO / "packaging" / "90stv-volatile.conf").read_text(
    encoding="utf-8"
)

REQUIRED_PACKAGES = ("mpv", "ffmpeg", "avahi-daemon")
DEFAULT_DENY_MARKERS = (
    "iptables -P OUTPUT DROP",
    "iptables -P OUTPUT DENY",
    "ufw default deny outgoing",
    "ufw default deny outbound",
    "ufw enable",
)


def test_setup_script_uses_strict_bash() -> None:
    assert SETUP_SCRIPT.startswith("#!/usr/bin/env bash")
    assert "set -euo pipefail" in SETUP_SCRIPT


def test_setup_script_installs_required_packages() -> None:
    for package in REQUIRED_PACKAGES:
        assert package in SETUP_SCRIPT
    assert "python3-venv" in SETUP_SCRIPT
    assert "python3.11" not in SETUP_SCRIPT.split("APT_PACKAGES")[1].split(")")[0]


def test_setup_script_sets_hostname_90stv() -> None:
    assert "90stv" in SETUP_SCRIPT
    assert "hostnamectl" in SETUP_SCRIPT or "hostname" in SETUP_SCRIPT


def test_setup_script_does_not_configure_outbound_firewall() -> None:
    for marker in DEFAULT_DENY_MARKERS:
        assert marker not in SETUP_SCRIPT
    assert "ufw " not in SETUP_SCRIPT
    assert "iptables " not in SETUP_SCRIPT


def test_setup_script_enables_timesyncd() -> None:
    assert "systemd-timesyncd" in SETUP_SCRIPT
    assert "set-ntp" in SETUP_SCRIPT or "timesyncd" in SETUP_SCRIPT


def test_setup_script_installs_volatile_journald() -> None:
    assert "90stv-volatile.conf" in SETUP_SCRIPT
    assert "Storage=volatile" in JOURNALD_DROPIN
    assert "[Journal]" in JOURNALD_DROPIN


def test_setup_script_mentions_overlay_and_pi_guard() -> None:
    assert "overlay" in SETUP_SCRIPT.lower()
    assert "enable_overlayfs" in SETUP_SCRIPT
    assert "enable_bootro" in SETUP_SCRIPT
    assert "Raspberry Pi" in SETUP_SCRIPT
    assert "/boot/firmware" in SETUP_SCRIPT or "device-tree" in SETUP_SCRIPT


def test_setup_script_is_idempotent_about_fstab_and_units() -> None:
    assert "fstab" in SETUP_SCRIPT
    assert "ro" in SETUP_SCRIPT
    assert "/srv/90stv/library" in SETUP_SCRIPT
    assert "/srv/90stv/interstitials" in SETUP_SCRIPT
    assert "90stv.service" in SETUP_SCRIPT
    assert "tv90-maintenance" in SETUP_SCRIPT
    assert "90stv-library-rw.service" in SETUP_SCRIPT
    assert "tv90-apply-library-mount" in SETUP_SCRIPT


def test_setup_script_does_not_install_cec_utils() -> None:
    assert "cec-utils" not in SETUP_SCRIPT


def test_setup_script_supports_non_root_and_skip_media() -> None:
    assert "id -u" in SETUP_SCRIPT
    assert "must run as root" not in SETUP_SCRIPT
    assert ".venv" in SETUP_SCRIPT
    assert "downloads/library" in SETUP_SCRIPT
    assert "downloads/interstitials" in SETUP_SCRIPT
    assert "--skip-media" in SETUP_SCRIPT


def test_setup_script_fetches_shows_and_interstitials() -> None:
    assert "download-kipper" in SETUP_SCRIPT
    assert "download-oswald" in SETUP_SCRIPT
    assert "download-harry" in SETUP_SCRIPT
    assert "download-holiday" in SETUP_SCRIPT
    assert "download-interstitials" in SETUP_SCRIPT
    assert "interstitials" in SETUP_SCRIPT


def test_setup_script_is_resilient_about_existing_disk_network_health() -> None:
    assert "skip valid existing files" in SETUP_SCRIPT
    assert "existing installation detected" in SETUP_SCRIPT
    assert "--repair" in SETUP_SCRIPT
    assert "health" in SETUP_SCRIPT
    assert "disk" in SETUP_SCRIPT
    assert "network" in SETUP_SCRIPT
    assert "MIN_FREE_GIB_FULL_LIBRARY" in SETUP_SCRIPT
    assert "archive.org" in SETUP_SCRIPT
    assert "apt-get upgrade" not in SETUP_SCRIPT
    assert "overlay_should_enable" in SETUP_SCRIPT
    assert "skip overlay until" in SETUP_SCRIPT


def test_unit_file_restarts_always_and_logs_to_journal() -> None:
    assert "Restart=always" in UNIT_FILE
    assert "After=network-online.target sound.target" in UNIT_FILE
    assert "User=tv90" in UNIT_FILE
    assert "Environment=TV90_LIBRARY_PATH=/srv/90stv/library" in UNIT_FILE
    assert "Environment=TV90_INTERSTITIALS_PATH=/srv/90stv/interstitials" in UNIT_FILE
    assert "StandardOutput=journal" in UNIT_FILE
    assert "TTYPath=/dev/tty1" in UNIT_FILE
    assert "StandardInput=tty" in UNIT_FILE
    assert "python3 -m tv90.main" in UNIT_FILE
    assert "ConditionPathExists=!/srv/90stv/library/.tv90-maintenance" in UNIT_FILE
    assert "StandardOutput=file:" not in UNIT_FILE
    assert "StandardError=file:" not in UNIT_FILE


def test_library_rw_boot_unit_remounts_when_flag_present() -> None:
    assert "tv90-apply-library-mount" in LIBRARY_RW_UNIT
    assert "WantedBy=multi-user.target" in LIBRARY_RW_UNIT
    assert APPLY_LIBRARY_MOUNT.startswith("#!/usr/bin/env bash")
    assert "set -euo pipefail" in APPLY_LIBRARY_MOUNT
    assert ".tv90-maintenance" in APPLY_LIBRARY_MOUNT
    assert "remount,rw" in APPLY_LIBRARY_MOUNT
    assert "disable --now" in APPLY_LIBRARY_MOUNT
    assert "90stv.service" in APPLY_LIBRARY_MOUNT
    assert "disable_bootro" in APPLY_LIBRARY_MOUNT
