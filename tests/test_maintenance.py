import io
from pathlib import Path

import pytest

from tv90.application.maintenance import (
    ARGPARSE_ERROR_EXIT_CODE,
    MAINTENANCE_FLAG_FILENAME,
    MAINTENANCE_MODE_LABEL,
    SERVICE_UNIT,
    SKIP_NOT_MOUNT,
    SKIP_NOT_PI,
    SKIP_RASPI_CONFIG,
    SUCCESS_EXIT_CODE,
    TV_MODE_LABEL,
    CommandOutput,
    OverlayAction,
    SystemCommandRunner,
    SystemMaintenanceHost,
    apply_persisted_maintenance,
    build_production_host,
    current_mode,
    detect_raspberry_pi,
    enter_maintenance,
    is_raspberry_pi,
    leave_maintenance,
    main,
    overlay_is_active,
    run_maintenance_command,
)
from tv90.config import DEFAULT_LIBRARY_PATH

WRAPPER = (
    Path(__file__).resolve().parents[1] / "scripts" / "tv90-maintenance"
).read_text(encoding="utf-8")


class FakeMaintenanceHost:
    def __init__(
        self,
        *,
        service_active: bool,
        overlay_enabled: bool,
        service_enabled: bool | None = None,
        library_writable: bool | None = None,
        maintenance_flag: bool = False,
        reboot_required: bool = True,
        remount_message: str = "",
        overlay_message: str = "",
    ) -> None:
        self.service_active = service_active
        self.overlay_enabled = overlay_enabled
        self.service_enabled = (
            service_active if service_enabled is None else service_enabled
        )
        self.library_writable = (
            not overlay_enabled if library_writable is None else library_writable
        )
        self.maintenance_flag = maintenance_flag
        self.reboot_required = reboot_required
        self.remount_message = remount_message
        self.overlay_message = overlay_message
        self.calls: list[str] = []

    def is_service_active(self) -> bool:
        return self.service_active

    def is_service_enabled(self) -> bool:
        return self.service_enabled

    def is_library_writable(self) -> bool:
        return self.library_writable

    def is_maintenance_flag_present(self) -> bool:
        return self.maintenance_flag

    def retry_disable_bootro(self) -> str:
        self.calls.append("retry_disable_bootro")
        return ""

    def disable_service(self) -> None:
        self.calls.append("disable_service")
        self.service_active = False
        self.service_enabled = False

    def enable_service(self) -> None:
        self.calls.append("enable_service")
        self.service_active = True
        self.service_enabled = True

    def is_overlay_enabled(self) -> bool:
        return self.overlay_enabled

    def disable_overlay(self) -> OverlayAction:
        self.calls.append("disable_overlay")
        self.overlay_enabled = False
        return OverlayAction(self.reboot_required, False, self.overlay_message)

    def enable_overlay(self) -> OverlayAction:
        self.calls.append("enable_overlay")
        self.overlay_enabled = True
        return OverlayAction(self.reboot_required, False, self.overlay_message)

    def remount_library_writable(self) -> str:
        self.calls.append("remount_rw")
        self.library_writable = True
        self.maintenance_flag = True
        return self.remount_message

    def remount_library_readonly(self) -> str:
        self.calls.append("remount_ro")
        self.library_writable = False
        self.maintenance_flag = False
        return self.remount_message

    def reboot(self) -> None:
        self.calls.append("reboot")


class RebootExitsHost(FakeMaintenanceHost):
    def reboot(self) -> None:
        self.calls.append("reboot")
        raise SystemExit(0)


class RecordingRunner:
    def __init__(
        self,
        responses: dict[tuple[str, ...], CommandOutput] | None = None,
        default: CommandOutput | None = None,
    ) -> None:
        self.calls: list[tuple[str, ...]] = []
        self.responses = responses or {}
        self.default = default if default is not None else CommandOutput(0, "", "")

    def __call__(self, arguments: tuple[str, ...]) -> CommandOutput:
        self.calls.append(arguments)
        if arguments in self.responses:
            return self.responses[arguments]
        for prefix, output in self.responses.items():
            if arguments[: len(prefix)] == prefix:
                return output
        return self.default


def _host(
    runner: SystemCommandRunner,
    *,
    is_pi: bool = True,
    cmdline: str = "",
    mounts: str = "",
    library_path: Path = DEFAULT_LIBRARY_PATH,
) -> SystemMaintenanceHost:
    return SystemMaintenanceHost(
        runner,
        library_path=library_path,
        is_pi=is_pi,
        read_cmdline=lambda: cmdline,
        read_mounts=lambda: mounts,
    )


def test_current_mode_is_tv_when_service_or_overlay_is_on() -> None:
    assert (
        current_mode(FakeMaintenanceHost(service_active=True, overlay_enabled=False))
        == TV_MODE_LABEL
    )
    assert (
        current_mode(FakeMaintenanceHost(service_active=False, overlay_enabled=True))
        == TV_MODE_LABEL
    )


def test_current_mode_is_tv_when_service_is_enabled_without_flag() -> None:
    host = FakeMaintenanceHost(
        service_active=False,
        service_enabled=True,
        overlay_enabled=False,
        library_writable=True,
        maintenance_flag=False,
    )

    assert current_mode(host) == TV_MODE_LABEL


def test_current_mode_is_maintenance_when_flag_survives_overlay_discard() -> None:
    # disable --now ran on tmpfs /etc and is gone; lower-root unit is still enabled.
    host = FakeMaintenanceHost(
        service_active=False,
        service_enabled=True,
        overlay_enabled=False,
        library_writable=True,
        maintenance_flag=True,
    )

    assert current_mode(host) == MAINTENANCE_MODE_LABEL
    change = enter_maintenance(host)
    assert change.mode == MAINTENANCE_MODE_LABEL
    assert host.calls == []


def test_current_mode_overlay_wins_over_maintenance_flag() -> None:
    host = FakeMaintenanceHost(
        service_active=True,
        service_enabled=True,
        overlay_enabled=True,
        library_writable=True,
        maintenance_flag=True,
    )

    assert current_mode(host) == TV_MODE_LABEL


def test_current_mode_is_tv_when_library_is_still_read_only() -> None:
    host = FakeMaintenanceHost(
        service_active=False,
        service_enabled=False,
        overlay_enabled=False,
        library_writable=False,
    )

    assert current_mode(host) == TV_MODE_LABEL
    assert enter_maintenance(host).mode == MAINTENANCE_MODE_LABEL
    assert host.calls[0] == "disable_service"


def test_enter_maintenance_is_noop_when_already_there() -> None:
    host = FakeMaintenanceHost(service_active=False, overlay_enabled=False)

    change = enter_maintenance(host)

    assert change.mode == MAINTENANCE_MODE_LABEL
    assert host.calls == []


def test_enter_maintenance_stops_disables_remounts_and_reboots() -> None:
    host = FakeMaintenanceHost(service_active=True, overlay_enabled=True)

    change = enter_maintenance(host)

    assert change.mode == MAINTENANCE_MODE_LABEL
    assert change.reboot_required is True
    assert host.calls == [
        "disable_service",
        "disable_overlay",
        "remount_rw",
    ]


def test_enter_maintenance_skips_reboot_when_overlay_does_not_need_it() -> None:
    host = FakeMaintenanceHost(
        service_active=True,
        overlay_enabled=True,
        reboot_required=False,
        overlay_message=SKIP_NOT_PI,
        remount_message=SKIP_NOT_MOUNT,
    )

    change = enter_maintenance(host)

    assert change.mode == MAINTENANCE_MODE_LABEL
    assert change.reboot_required is False
    assert SKIP_NOT_PI in change.messages
    assert SKIP_NOT_MOUNT in change.messages
    assert "reboot" not in host.calls


def test_leave_maintenance_is_noop_when_already_tv() -> None:
    host = FakeMaintenanceHost(service_active=True, overlay_enabled=True)

    change = leave_maintenance(host)

    assert change.mode == TV_MODE_LABEL
    assert host.calls == []


def test_apply_persisted_maintenance_disables_service_on_real_root() -> None:
    host = FakeMaintenanceHost(
        service_active=False,
        service_enabled=True,
        overlay_enabled=False,
        maintenance_flag=True,
    )

    change = apply_persisted_maintenance(host)

    assert change.mode == MAINTENANCE_MODE_LABEL
    assert host.calls == [
        "remount_rw",
        "disable_service",
        "retry_disable_bootro",
    ]
    assert host.service_enabled is False


def test_apply_persisted_maintenance_does_not_fight_off() -> None:
    host = FakeMaintenanceHost(
        service_active=True,
        service_enabled=True,
        overlay_enabled=False,
        maintenance_flag=False,
        library_writable=False,
    )

    change = apply_persisted_maintenance(host)

    assert change.mode == TV_MODE_LABEL
    assert host.calls == []
    assert host.service_enabled is True


def test_leave_maintenance_remounts_enables_starts_and_reboots() -> None:
    host = FakeMaintenanceHost(service_active=False, overlay_enabled=False)

    change = leave_maintenance(host)

    assert change.mode == TV_MODE_LABEL
    assert change.reboot_required is True
    assert host.calls == [
        "remount_ro",
        "enable_overlay",
        "enable_service",
    ]


def test_cli_status_prints_current_mode() -> None:
    stdout = io.StringIO()
    host = FakeMaintenanceHost(service_active=True, overlay_enabled=True)

    exit_code = main(["status"], host, stdout)

    assert exit_code == SUCCESS_EXIT_CODE
    assert stdout.getvalue() == f"{TV_MODE_LABEL}\n"


def test_cli_prints_mode_before_reboot() -> None:
    stdout = io.StringIO()
    host = RebootExitsHost(service_active=True, overlay_enabled=True)

    with pytest.raises(SystemExit):
        main(["on"], host, stdout)

    assert stdout.getvalue().splitlines()[-1] == MAINTENANCE_MODE_LABEL
    assert "reboot" in host.calls


def test_cli_prints_tv_mode_before_leave_reboot() -> None:
    stdout = io.StringIO()
    host = RebootExitsHost(service_active=False, overlay_enabled=False)

    with pytest.raises(SystemExit):
        main(["off"], host, stdout)

    assert stdout.getvalue().splitlines()[-1] == TV_MODE_LABEL
    assert "reboot" in host.calls


def test_cli_on_and_off_print_the_mode() -> None:
    on_out = io.StringIO()
    off_out = io.StringIO()
    tv = FakeMaintenanceHost(service_active=True, overlay_enabled=True)
    box = FakeMaintenanceHost(service_active=False, overlay_enabled=False)

    assert main(["on"], tv, on_out) == SUCCESS_EXIT_CODE
    assert main(["off"], box, off_out) == SUCCESS_EXIT_CODE
    assert on_out.getvalue().splitlines()[-1] == MAINTENANCE_MODE_LABEL
    assert off_out.getvalue().splitlines()[-1] == TV_MODE_LABEL


def test_cli_rejects_unknown_command() -> None:
    stdout = io.StringIO()

    exit_code = main(
        ["maybe"],
        FakeMaintenanceHost(service_active=False, overlay_enabled=False),
        stdout,
    )

    assert exit_code == ARGPARSE_ERROR_EXIT_CODE
    assert "on|off|status" in stdout.getvalue()


def test_cli_rejects_missing_and_extra_arguments() -> None:
    host = FakeMaintenanceHost(service_active=False, overlay_enabled=False)

    assert main([], host, io.StringIO()) == ARGPARSE_ERROR_EXIT_CODE
    assert main(["on", "now"], host, io.StringIO()) == ARGPARSE_ERROR_EXIT_CODE


def test_is_raspberry_pi_requires_device_tree_model() -> None:
    assert is_raspberry_pi("Raspberry Pi 4 Model B Rev 1.5") is True
    assert is_raspberry_pi(None) is False
    assert is_raspberry_pi("QEMU Virtual Machine") is False


def test_detect_raspberry_pi_uses_injected_reader() -> None:
    assert detect_raspberry_pi(lambda: "Raspberry Pi 5") is True
    assert detect_raspberry_pi(lambda: None) is False


def test_overlay_is_active_from_cmdline_and_mounts() -> None:
    assert overlay_is_active("console=tty1 overlayroot=tmpfs", "") is True
    assert overlay_is_active("console=tty1 overlayroot=disabled", "") is False
    assert overlay_is_active("", "overlay / overlay rw 0 0") is True
    assert overlay_is_active("", "ext4 / ext4 rw 0 0") is False


def test_system_host_skips_overlay_when_not_a_pi() -> None:
    runner = RecordingRunner()
    host = _host(runner, is_pi=False)

    action = host.disable_overlay()

    assert action.skipped is True
    assert action.reboot_required is False
    assert action.message == SKIP_NOT_PI
    assert runner.calls == []


def test_system_host_skips_overlay_when_raspi_config_missing() -> None:
    runner = RecordingRunner(
        default=CommandOutput(127, "", "not found"),
        responses={
            ("findmnt", "--noheadings", "--mountpoint", str(DEFAULT_LIBRARY_PATH)): (
                CommandOutput(1, "", "")
            ),
        },
    )
    host = _host(runner, is_pi=True, cmdline="overlayroot=tmpfs")

    action = host.disable_overlay()

    assert action.skipped is True
    assert action.message == SKIP_RASPI_CONFIG


def test_system_host_disables_overlay_and_bootro_when_active() -> None:
    runner = RecordingRunner(
        responses={
            ("raspi-config", "nonint", "get_overlay_now"): CommandOutput(0, "0\n", ""),
            ("raspi-config", "nonint", "disable_overlayfs"): CommandOutput(0, "", ""),
            ("raspi-config", "nonint", "disable_bootro"): CommandOutput(0, "", ""),
        }
    )
    host = _host(runner, cmdline="overlayroot=tmpfs")

    action = host.disable_overlay()

    assert action.reboot_required is True
    assert action.skipped is False
    assert (
        "raspi-config",
        "nonint",
        "disable_overlayfs",
    ) in runner.calls
    assert ("raspi-config", "nonint", "disable_bootro") in runner.calls


def test_system_host_enable_overlay_is_noop_when_already_on() -> None:
    runner = RecordingRunner()
    host = _host(runner, cmdline="overlayroot=tmpfs")

    action = host.enable_overlay()

    assert action.reboot_required is False
    assert action.skipped is True
    assert ("raspi-config", "nonint", "enable_overlayfs") not in runner.calls


def test_system_host_enables_overlay_when_off() -> None:
    runner = RecordingRunner(
        responses={
            ("raspi-config", "nonint", "get_overlay_now"): CommandOutput(0, "1\n", ""),
            ("raspi-config", "nonint", "enable_overlayfs"): CommandOutput(0, "", ""),
            ("raspi-config", "nonint", "enable_bootro"): CommandOutput(0, "", ""),
        }
    )
    host = _host(runner, cmdline="console=tty1")

    action = host.enable_overlay()

    assert action.reboot_required is True
    assert ("raspi-config", "nonint", "enable_overlayfs") in runner.calls
    assert ("raspi-config", "nonint", "enable_bootro") in runner.calls


def test_system_host_overlay_enable_skips_when_command_fails() -> None:
    runner = RecordingRunner(
        responses={
            ("raspi-config", "nonint", "get_overlay_now"): CommandOutput(1, "1\n", ""),
            ("raspi-config", "nonint", "enable_overlayfs"): CommandOutput(1, "", "no"),
        }
    )
    host = _host(runner)

    action = host.enable_overlay()

    assert action.skipped is True
    assert action.message == SKIP_RASPI_CONFIG


def test_system_host_service_and_reboot_use_systemctl() -> None:
    runner = RecordingRunner(
        responses={
            ("systemctl", "is-active", "--quiet", SERVICE_UNIT): CommandOutput(
                0, "", ""
            )
        }
    )
    host = _host(runner)

    assert host.is_service_active() is True
    host.disable_service()
    host.enable_service()
    host.reboot()

    assert ("systemctl", "disable", "--now", SERVICE_UNIT) in runner.calls
    assert ("systemctl", "enable", "--now", SERVICE_UNIT) in runner.calls
    assert ("systemctl", "reboot") in runner.calls


def test_system_host_is_service_enabled() -> None:
    enabled = _host(
        RecordingRunner(
            responses={
                ("systemctl", "is-enabled", "--quiet", SERVICE_UNIT): CommandOutput(
                    0, "", ""
                )
            }
        )
    )
    disabled = _host(
        RecordingRunner(
            responses={
                ("systemctl", "is-enabled", "--quiet", SERVICE_UNIT): CommandOutput(
                    1, "disabled\n", ""
                )
            }
        )
    )

    assert enabled.is_service_enabled() is True
    assert disabled.is_service_enabled() is False


def test_system_host_service_inactive_and_oserror_are_not_active() -> None:
    inactive = _host(
        RecordingRunner(
            responses={
                ("systemctl", "is-active", "--quiet", SERVICE_UNIT): CommandOutput(
                    3, "inactive\n", ""
                )
            }
        )
    )
    exploding = _host(_ExplodingRunner())

    assert inactive.is_service_active() is False
    assert exploding.is_service_active() is False


def test_system_host_skips_remount_when_library_is_not_a_mount() -> None:
    runner = RecordingRunner(
        responses={
            ("findmnt", "--noheadings", "--mountpoint", str(DEFAULT_LIBRARY_PATH)): (
                CommandOutput(1, "", "")
            )
        }
    )
    host = _host(runner)

    assert host.remount_library_writable() == SKIP_NOT_MOUNT
    assert host.remount_library_readonly() == SKIP_NOT_MOUNT
    assert not any(call[0] == "mount" for call in runner.calls)


def test_system_host_remounts_library_when_it_is_a_mount() -> None:
    runner = RecordingRunner(
        responses={
            ("findmnt", "--noheadings", "--mountpoint", str(DEFAULT_LIBRARY_PATH)): (
                CommandOutput(0, "/srv/90stv/library\n", "")
            )
        }
    )
    host = _host(runner)

    assert host.remount_library_writable() == ""
    assert host.remount_library_readonly() == ""
    assert ("mount", "-o", "remount,rw", str(DEFAULT_LIBRARY_PATH)) in runner.calls
    assert ("mount", "-o", "remount,ro", str(DEFAULT_LIBRARY_PATH)) in runner.calls


def test_system_host_reports_failed_remount() -> None:
    runner = RecordingRunner(
        responses={
            ("findmnt", "--noheadings", "--mountpoint", str(DEFAULT_LIBRARY_PATH)): (
                CommandOutput(0, "/srv/90stv/library\n", "")
            ),
            ("mount", "-o", "remount,rw", str(DEFAULT_LIBRARY_PATH)): CommandOutput(
                32, "", "busy"
            ),
        }
    )
    host = _host(runner)

    message = host.remount_library_writable()

    assert "skip remount" in message
    assert "32" in message


def test_system_host_treats_already_disabled_overlay_as_noop() -> None:
    runner = RecordingRunner(
        responses={
            ("raspi-config", "nonint", "get_overlay_now"): CommandOutput(0, "1\n", "")
        }
    )
    host = _host(runner, cmdline="console=tty1")

    action = host.disable_overlay()

    assert action.skipped is True
    assert action.reboot_required is False
    assert ("raspi-config", "nonint", "disable_overlayfs") not in runner.calls


def test_build_production_host_uses_injected_environ() -> None:
    host = build_production_host({"TV90_LIBRARY_PATH": "/mnt/cartoons"})

    assert isinstance(host, SystemMaintenanceHost)
    assert host._library_path == Path("/mnt/cartoons")
    assert host.is_overlay_enabled() in {True, False}


def test_detect_raspberry_pi_without_injection_does_not_raise() -> None:
    assert detect_raspberry_pi() in {True, False}


def test_run_maintenance_command_captures_stdout() -> None:
    result = run_maintenance_command(("echo", "hello-maintenance"))

    assert result.returncode == 0
    assert "hello-maintenance" in result.stdout


def test_run_maintenance_command_missing_binary_is_not_found() -> None:
    result = run_maintenance_command(("tv90-definitely-missing-binary",))

    assert result.returncode == 127


def test_system_host_persists_writable_library_with_flag(tmp_path: Path) -> None:
    runner = RecordingRunner(
        responses={
            ("findmnt", "--noheadings", "--mountpoint", str(tmp_path)): CommandOutput(
                0, f"{tmp_path}\n", ""
            )
        }
    )
    host = _host(runner, library_path=tmp_path)

    assert host.remount_library_writable() == ""
    assert (tmp_path / MAINTENANCE_FLAG_FILENAME).is_file()
    assert host.is_library_writable() is True
    assert host.remount_library_readonly() == ""
    assert not (tmp_path / MAINTENANCE_FLAG_FILENAME).exists()


def test_system_host_retry_disable_bootro_after_overlay_is_off() -> None:
    runner = RecordingRunner(
        responses={
            ("raspi-config", "nonint", "disable_bootro"): CommandOutput(0, "", ""),
        }
    )
    host = _host(runner, is_pi=True, cmdline="console=tty1")

    assert host.retry_disable_bootro() == ""
    assert ("raspi-config", "nonint", "disable_bootro") in runner.calls


def test_system_host_retry_disable_bootro_skips_when_not_a_pi() -> None:
    runner = RecordingRunner()
    host = _host(runner, is_pi=False)

    assert host.retry_disable_bootro() == ""
    assert runner.calls == []


def test_system_host_retry_disable_bootro_skips_when_command_fails() -> None:
    runner = RecordingRunner(
        responses={
            ("raspi-config", "nonint", "disable_bootro"): CommandOutput(1, "", "busy"),
        }
    )
    host = _host(runner, is_pi=True)

    assert "skip bootro" in host.retry_disable_bootro()


def test_system_host_reports_flag_presence(tmp_path: Path) -> None:
    host = _host(RecordingRunner(), library_path=tmp_path)

    assert host.is_maintenance_flag_present() is False
    (tmp_path / MAINTENANCE_FLAG_FILENAME).write_text("rw\n", encoding="utf-8")
    assert host.is_maintenance_flag_present() is True


def test_system_host_treats_flag_as_writable_even_if_mount_is_ro(
    tmp_path: Path,
) -> None:
    (tmp_path / MAINTENANCE_FLAG_FILENAME).write_text("rw\n", encoding="utf-8")
    runner = RecordingRunner(
        responses={
            ("findmnt", "--noheadings", "--mountpoint", str(tmp_path)): CommandOutput(
                0, f"{tmp_path}\n", ""
            ),
            ("findmnt", "-no", "OPTIONS", str(tmp_path)): CommandOutput(
                0, "ro,relatime\n", ""
            ),
        }
    )
    host = _host(runner, library_path=tmp_path)

    assert host.is_library_writable() is True


def test_system_host_library_without_mount_counts_as_writable() -> None:
    runner = RecordingRunner(
        responses={
            ("findmnt", "--noheadings", "--mountpoint", str(DEFAULT_LIBRARY_PATH)): (
                CommandOutput(1, "", "")
            )
        }
    )
    host = _host(runner)

    assert host.is_library_writable() is True


def test_system_host_ro_mount_without_flag_is_not_writable() -> None:
    runner = RecordingRunner(
        responses={
            (
                "findmnt",
                "--noheadings",
                "--mountpoint",
                str(DEFAULT_LIBRARY_PATH),
            ): CommandOutput(0, f"{DEFAULT_LIBRARY_PATH}\n", ""),
            ("findmnt", "-no", "OPTIONS", str(DEFAULT_LIBRARY_PATH)): CommandOutput(
                0, "ro,noload,nofail\n", ""
            ),
        }
    )
    host = _host(runner)

    assert host.is_library_writable() is False


def test_wrapper_is_strict_bash_and_calls_the_module() -> None:
    assert WRAPPER.startswith("#!/usr/bin/env bash")
    assert "set -euo pipefail" in WRAPPER
    assert "tv90.application.maintenance" in WRAPPER
    assert "dry_run" not in WRAPPER


class _ExplodingRunner:
    def __call__(self, arguments: tuple[str, ...]) -> CommandOutput:
        raise OSError("systemctl missing")
