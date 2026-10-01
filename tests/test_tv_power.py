import subprocess
from pathlib import Path

import pytest

from tv90.adapters.cec_client_tv_power import (
    CEC_CLIENT_COMMAND,
    CecClientTvPower,
    CecCommandError,
    CecCommandResult,
    cec_client_arguments,
    cec_power_on_stdin,
    cec_standby_stdin,
)
from tv90.adapters.fake_tv_power import FakeTvPower, PowerOnCommand, StandbyCommand
from tv90.ports import TvPower


class RecordingCecRunner:
    def __init__(self, returncode: int = 0, stdout: str = "") -> None:
        self.returncode = returncode
        self.stdout = stdout
        self.calls: list[tuple[tuple[str, ...], str]] = []

    def __call__(self, arguments: tuple[str, ...], stdin_text: str) -> CecCommandResult:
        self.calls.append((arguments, stdin_text))
        return CecCommandResult(stdout=self.stdout, returncode=self.returncode)


def test_cec_client_arguments_are_single_command_error_log() -> None:
    assert cec_client_arguments() == ("cec-client", "-s", "-d", "1")
    assert cec_standby_stdin() == "standby 0\n"
    assert cec_power_on_stdin() == "on 0\n"


def test_fake_tv_power_starts_powered_on() -> None:
    power = FakeTvPower()

    assert power.is_in_standby() is False
    assert power.commands == ()


def test_fake_tv_power_standby_tracks_state_and_records_command() -> None:
    power = FakeTvPower()

    power.standby()

    assert power.is_in_standby() is True
    assert power.commands == (StandbyCommand(),)


def test_fake_tv_power_power_on_clears_standby_and_records_command() -> None:
    power = FakeTvPower()
    power.standby()

    power.power_on()

    assert power.is_in_standby() is False
    assert power.commands == (StandbyCommand(), PowerOnCommand())


def test_fake_tv_power_is_in_standby_does_not_record_a_command() -> None:
    power = FakeTvPower()

    assert power.is_in_standby() is False
    assert power.commands == ()


def test_cec_adapter_standby_sends_expected_argv_and_stdin() -> None:
    runner = RecordingCecRunner()
    power = CecClientTvPower(runner)

    power.standby()

    assert runner.calls == [(cec_client_arguments(), cec_standby_stdin())]
    assert power.is_in_standby() is True


def test_cec_adapter_power_on_sends_expected_argv_and_stdin() -> None:
    runner = RecordingCecRunner()
    power = CecClientTvPower(runner)

    power.power_on()

    assert runner.calls == [(cec_client_arguments(), cec_power_on_stdin())]
    assert power.is_in_standby() is False


def test_cec_adapter_starts_powered_on_without_calling_cec_client() -> None:
    runner = RecordingCecRunner()
    power = CecClientTvPower(runner)

    assert power.is_in_standby() is False
    assert runner.calls == []


def test_cec_adapter_non_zero_exit_raises() -> None:
    runner = RecordingCecRunner(returncode=1)
    power = CecClientTvPower(runner)

    with pytest.raises(CecCommandError) as raised:
        power.standby()

    assert raised.value.arguments == cec_client_arguments()
    assert raised.value.stdin_text == cec_standby_stdin()
    assert power.is_in_standby() is False


def test_cec_adapter_os_error_raises_cec_command_error() -> None:
    def fail_run(_arguments: tuple[str, ...], _stdin_text: str) -> CecCommandResult:
        raise FileNotFoundError(CEC_CLIENT_COMMAND)

    power = CecClientTvPower(fail_run)

    with pytest.raises(CecCommandError):
        power.power_on()

    assert power.is_in_standby() is False


def test_cec_adapter_does_not_spawn_real_cec_client(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_run(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("tests must not spawn cec-client")

    monkeypatch.setattr(subprocess, "run", fail_run)
    monkeypatch.setattr(subprocess, "Popen", fail_run)
    runner = RecordingCecRunner()
    power = CecClientTvPower(runner)

    power.standby()
    power.power_on()

    assert runner.calls == [
        (cec_client_arguments(), cec_standby_stdin()),
        (cec_client_arguments(), cec_power_on_stdin()),
    ]


def test_cec_adapter_does_not_write_disk(tmp_path: Path) -> None:
    before = {path.name: path.read_bytes() for path in tmp_path.iterdir()}
    power = CecClientTvPower(RecordingCecRunner())

    power.standby()
    power.power_on()
    power.is_in_standby()

    after = {path.name: path.read_bytes() for path in tmp_path.iterdir()}
    assert after == before


def test_fake_and_cec_adapter_satisfy_tv_power_protocol() -> None:
    powers: list[TvPower] = [
        FakeTvPower(),
        CecClientTvPower(RecordingCecRunner()),
    ]

    for power in powers:
        power.power_on()
        assert power.is_in_standby() is False
        power.standby()
        assert power.is_in_standby() is True
        power.power_on()
        assert power.is_in_standby() is False
