"""Maintenance mode: stop TV, drop overlay, remount library. Tests inject the host."""

from __future__ import annotations

import os
import subprocess
import sys
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, TextIO

from tv90.config import load_library_path

SERVICE_UNIT = "90stv.service"
ON_COMMAND = "on"
OFF_COMMAND = "off"
STATUS_COMMAND = "status"
MAINTENANCE_MODE_LABEL = "maintenance mode"
TV_MODE_LABEL = "tv mode"
USAGE = "usage: tv90-maintenance on|off|status\n"
SUCCESS_EXIT_CODE = 0
ARGPARSE_ERROR_EXIT_CODE = 2
COMMAND_NOT_FOUND = 127
MAINTENANCE_COMMAND_TIMEOUT_SECONDS = 30

RASPI_CONFIG = "raspi-config"
NONINT = "nonint"
ENABLE_OVERLAYFS = "enable_overlayfs"
DISABLE_OVERLAYFS = "disable_overlayfs"
ENABLE_BOOTRO = "enable_bootro"
DISABLE_BOOTRO = "disable_bootro"
GET_OVERLAY_NOW = "get_overlay_now"

SYSTEMCTL = "systemctl"
MOUNT = "mount"
FINDMNT = "findmnt"
DEVICE_TREE_MODEL_PATH = Path("/proc/device-tree/model")
CMDLINE_PATH = Path("/proc/cmdline")
MOUNTS_PATH = Path("/proc/mounts")
RASPBERRY_PI_MODEL_MARKER = "Raspberry Pi"
OVERLAYROOT_DISABLED = "overlayroot=disabled"
OVERLAYROOT_PREFIX = "overlayroot="
OVERLAY_FSTYPE = "overlay"
ROOT_MOUNT_POINT = "/"

SKIP_NOT_PI = "skip overlay: not a Raspberry Pi"
SKIP_RASPI_CONFIG = "skip overlay: raspi-config is unavailable"
SKIP_NOT_MOUNT = "skip remount: library is not a mount point"
MAINTENANCE_FLAG_FILENAME = ".tv90-maintenance"
FINDMNT_OPTIONS_FLAG = "-no"
FINDMNT_OPTIONS_FIELD = "OPTIONS"

SystemCommandRunner = Callable[[tuple[str, ...]], "CommandOutput"]
TextReader = Callable[[], str]
ModelReader = Callable[[], str | None]


@dataclass(frozen=True)
class CommandOutput:
    returncode: int
    stdout: str
    stderr: str


@dataclass(frozen=True)
class OverlayAction:
    reboot_required: bool
    skipped: bool
    message: str


@dataclass(frozen=True)
class ModeChange:
    mode: str
    messages: tuple[str, ...]
    reboot_required: bool = False


class MaintenanceHost(Protocol):
    def is_service_active(self) -> bool:
        """True when 90stv.service is running."""
        ...

    def is_service_enabled(self) -> bool:
        """True when 90stv.service is enabled to start at boot."""
        ...

    def is_library_writable(self) -> bool:
        """True when the library is rw, has a persist flag, or is not a mount."""
        ...

    def is_maintenance_flag_present(self) -> bool:
        """True when .tv90-maintenance exists on the library partition."""
        ...

    def retry_disable_bootro(self) -> str:
        """Retry disable_bootro after overlay is off. Skip message or empty."""
        ...

    def disable_service(self) -> None:
        """Stop the TV service and prevent autostart. Missing units must not raise."""
        ...

    def enable_service(self) -> None:
        """Enable and start the TV service. Missing units must not raise."""
        ...

    def is_overlay_enabled(self) -> bool:
        """True when the root overlay is active or configured on."""
        ...

    def disable_overlay(self) -> OverlayAction:
        """Disable overlay + boot ro. Laptop/non-Pi skips."""
        ...

    def enable_overlay(self) -> OverlayAction:
        """Enable overlay + boot ro. Laptop/non-Pi skips."""
        ...

    def remount_library_writable(self) -> str:
        """Remount rw and persist a flag on the library partition."""
        ...

    def remount_library_readonly(self) -> str:
        """Remove the persist flag and remount ro."""
        ...

    def reboot(self) -> None:
        """Reboot when overlay enable/disable needs a new boot."""
        ...


def is_raspberry_pi(device_tree_model: str | None) -> bool:
    # A copied /boot/firmware folder on a laptop is not a Pi.
    return (
        device_tree_model is not None and RASPBERRY_PI_MODEL_MARKER in device_tree_model
    )


def detect_raspberry_pi(read_model: ModelReader | None = None) -> bool:
    reader = read_model if read_model is not None else _read_device_tree_model
    return is_raspberry_pi(reader())


def overlay_is_active(cmdline: str, mounts: str) -> bool:
    if OVERLAYROOT_DISABLED in cmdline:
        return False
    if OVERLAYROOT_PREFIX in cmdline:
        return True
    for line in mounts.splitlines():
        fields = line.split()
        if (
            len(fields) >= 3
            and fields[1] == ROOT_MOUNT_POINT
            and fields[2] == OVERLAY_FSTYPE
        ):
            return True
    return False


def current_mode(host: MaintenanceHost) -> str:
    if host.is_overlay_enabled():
        return TV_MODE_LABEL
    # Flag lives on the library partition; disable --now on overlay /etc does not.
    if host.is_maintenance_flag_present():
        return MAINTENANCE_MODE_LABEL
    if host.is_service_enabled() or host.is_service_active():
        return TV_MODE_LABEL
    if host.is_library_writable():
        return MAINTENANCE_MODE_LABEL
    return TV_MODE_LABEL


def apply_persisted_maintenance(host: MaintenanceHost) -> ModeChange:
    """After overlay is off: remount, disable on the real root, retry bootro."""
    if not host.is_maintenance_flag_present():
        return ModeChange(current_mode(host), (), False)
    remount_message = host.remount_library_writable()
    host.disable_service()
    bootro_message = host.retry_disable_bootro()
    return ModeChange(
        MAINTENANCE_MODE_LABEL,
        _messages(remount_message, bootro_message),
        False,
    )


def enter_maintenance(host: MaintenanceHost) -> ModeChange:
    if current_mode(host) == MAINTENANCE_MODE_LABEL:
        return ModeChange(MAINTENANCE_MODE_LABEL, (), False)
    host.disable_service()
    overlay = host.disable_overlay()
    remount_message = host.remount_library_writable()
    return ModeChange(
        MAINTENANCE_MODE_LABEL,
        _messages(overlay.message, remount_message),
        overlay.reboot_required,
    )


def leave_maintenance(host: MaintenanceHost) -> ModeChange:
    if current_mode(host) == TV_MODE_LABEL:
        return ModeChange(TV_MODE_LABEL, (), False)
    remount_message = host.remount_library_readonly()
    overlay = host.enable_overlay()
    host.enable_service()
    return ModeChange(
        TV_MODE_LABEL,
        _messages(remount_message, overlay.message),
        overlay.reboot_required,
    )


def main(argv: Sequence[str], host: MaintenanceHost, stdout: TextIO) -> int:
    if len(argv) != 1 or argv[0] not in {
        ON_COMMAND,
        OFF_COMMAND,
        STATUS_COMMAND,
    }:
        stdout.write(USAGE)
        return ARGPARSE_ERROR_EXIT_CODE
    command = argv[0]
    if command == STATUS_COMMAND:
        stdout.write(f"{current_mode(host)}\n")
        return SUCCESS_EXIT_CODE
    change = (
        enter_maintenance(host) if command == ON_COMMAND else leave_maintenance(host)
    )
    for message in change.messages:
        stdout.write(f"{message}\n")
    stdout.write(f"{change.mode}\n")
    # systemctl reboot does not return; the mode line must already be on stdout.
    stdout.flush()
    if change.reboot_required:
        host.reboot()
    return SUCCESS_EXIT_CODE


def run() -> int:
    return main(sys.argv[1:], build_production_host(), sys.stdout)


class SystemMaintenanceHost:
    def __init__(
        self,
        run_command: SystemCommandRunner,
        *,
        library_path: Path,
        is_pi: bool,
        read_cmdline: TextReader,
        read_mounts: TextReader,
    ) -> None:
        self._run_command = run_command
        self._library_path = library_path
        self._is_pi = is_pi
        self._read_cmdline = read_cmdline
        self._read_mounts = read_mounts

    def is_service_active(self) -> bool:
        result = self._run((SYSTEMCTL, "is-active", "--quiet", SERVICE_UNIT))
        return result.returncode == 0

    def is_service_enabled(self) -> bool:
        result = self._run((SYSTEMCTL, "is-enabled", "--quiet", SERVICE_UNIT))
        return result.returncode == 0

    def is_library_writable(self) -> bool:
        if self._flag_path().is_file():
            return True
        if not self._library_is_mount():
            return True
        result = self._run(
            (
                FINDMNT,
                FINDMNT_OPTIONS_FLAG,
                FINDMNT_OPTIONS_FIELD,
                str(self._library_path),
            )
        )
        options = [
            part.strip() for part in result.stdout.replace("\n", "").split(",") if part
        ]
        return "rw" in options

    def is_maintenance_flag_present(self) -> bool:
        return self._flag_path().is_file()

    def retry_disable_bootro(self) -> str:
        if not self._is_pi:
            return ""
        result = self._run((RASPI_CONFIG, NONINT, DISABLE_BOOTRO))
        if result.returncode != 0:
            return "skip bootro: raspi-config disable_bootro is unavailable"
        return ""

    def disable_service(self) -> None:
        self._run((SYSTEMCTL, "disable", "--now", SERVICE_UNIT))

    def enable_service(self) -> None:
        self._run((SYSTEMCTL, "enable", "--now", SERVICE_UNIT))

    def is_overlay_enabled(self) -> bool:
        if overlay_is_active(self._read_cmdline(), self._read_mounts()):
            return True
        result = self._run((RASPI_CONFIG, NONINT, GET_OVERLAY_NOW))
        token = result.stdout.strip()
        if token in {"0", "1"}:
            return token == "0"
        return result.returncode == 0

    def disable_overlay(self) -> OverlayAction:
        return self._set_overlay(enable=False)

    def enable_overlay(self) -> OverlayAction:
        return self._set_overlay(enable=True)

    def remount_library_writable(self) -> str:
        message = self._remount("rw")
        if message:
            return message
        self._write_flag()
        return ""

    def remount_library_readonly(self) -> str:
        self._remove_flag()
        return self._remount("ro")

    def reboot(self) -> None:
        self._run((SYSTEMCTL, "reboot"))

    def _set_overlay(self, *, enable: bool) -> OverlayAction:
        if not self._is_pi:
            return OverlayAction(False, True, SKIP_NOT_PI)
        already_enabled = self.is_overlay_enabled()
        if enable and already_enabled:
            return OverlayAction(False, True, "")
        if (not enable) and (not already_enabled):
            return OverlayAction(False, True, "")
        if not self._raspi_config_available():
            return OverlayAction(False, True, SKIP_RASPI_CONFIG)
        overlay_command = ENABLE_OVERLAYFS if enable else DISABLE_OVERLAYFS
        boot_command = ENABLE_BOOTRO if enable else DISABLE_BOOTRO
        overlay_result = self._run((RASPI_CONFIG, NONINT, overlay_command))
        if overlay_result.returncode != 0:
            return OverlayAction(False, True, SKIP_RASPI_CONFIG)
        self._run((RASPI_CONFIG, NONINT, boot_command))
        return OverlayAction(True, False, "")

    def _raspi_config_available(self) -> bool:
        result = self._run((RASPI_CONFIG, NONINT, GET_OVERLAY_NOW))
        return result.returncode != COMMAND_NOT_FOUND

    def _flag_path(self) -> Path:
        return self._library_path / MAINTENANCE_FLAG_FILENAME

    def _write_flag(self) -> None:
        try:
            self._flag_path().write_text("rw\n", encoding="utf-8")
        except OSError:
            return

    def _remove_flag(self) -> None:
        try:
            self._flag_path().unlink()
        except OSError:
            return

    def _library_is_mount(self) -> bool:
        result = self._run(
            (FINDMNT, "--noheadings", "--mountpoint", str(self._library_path))
        )
        return result.returncode == 0

    def _remount(self, mode: str) -> str:
        if not self._library_is_mount():
            return SKIP_NOT_MOUNT
        result = self._run((MOUNT, "-o", f"remount,{mode}", str(self._library_path)))
        if result.returncode != 0:
            return f"skip remount: mount exited {result.returncode}"
        return ""

    def _run(self, arguments: tuple[str, ...]) -> CommandOutput:
        try:
            return self._run_command(arguments)
        except (OSError, subprocess.SubprocessError):
            return CommandOutput(COMMAND_NOT_FOUND, "", "command failed")


def build_production_host(
    environ: Mapping[str, str] | None = None,
) -> SystemMaintenanceHost:
    return SystemMaintenanceHost(
        run_maintenance_command,
        library_path=load_library_path(os.environ if environ is None else environ),
        is_pi=detect_raspberry_pi(),
        read_cmdline=_read_optional_text(CMDLINE_PATH),
        read_mounts=_read_optional_text(MOUNTS_PATH),
    )


def run_maintenance_command(arguments: tuple[str, ...]) -> CommandOutput:
    try:
        completed = subprocess.run(
            arguments,
            check=False,
            capture_output=True,
            text=True,
            timeout=MAINTENANCE_COMMAND_TIMEOUT_SECONDS,
        )
    except FileNotFoundError:
        return CommandOutput(COMMAND_NOT_FOUND, "", "not found")
    except (OSError, subprocess.SubprocessError):
        return CommandOutput(COMMAND_NOT_FOUND, "", "failed")
    return CommandOutput(completed.returncode, completed.stdout, completed.stderr)


def _messages(*parts: str) -> tuple[str, ...]:
    return tuple(part for part in parts if part)


def _read_device_tree_model() -> str | None:
    try:
        return DEVICE_TREE_MODEL_PATH.read_text(encoding="utf-8")
    except OSError:
        return None


def _read_optional_text(path: Path) -> TextReader:
    def _read() -> str:
        try:
            return path.read_text(encoding="utf-8")
        except OSError:
            return ""

    return _read


if __name__ == "__main__":
    raise SystemExit(run())
