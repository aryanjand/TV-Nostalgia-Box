"""HDMI-CEC TvPower via cec-client. Tests inject a runner; never spawn cec-client."""

from __future__ import annotations

import subprocess
from collections.abc import Callable
from dataclasses import dataclass

CEC_CLIENT_COMMAND = "cec-client"
CEC_CLIENT_SINGLE_COMMAND_FLAG = "-s"
CEC_CLIENT_LOG_LEVEL_FLAG = "-d"
CEC_CLIENT_LOG_LEVEL = "1"
CEC_TV_LOGICAL_ADDRESS = 0
CEC_STANDBY_VERB = "standby"
CEC_POWER_ON_VERB = "on"
CEC_CLIENT_TIMEOUT_SECONDS = 10
CEC_COMMAND_NEWLINE = "\n"


class CecCommandError(Exception):
    """cec-client returned a non-zero status or could not be run."""

    def __init__(
        self, arguments: tuple[str, ...], stdin_text: str, reason: str
    ) -> None:
        self.arguments = arguments
        self.stdin_text = stdin_text
        self.reason = reason
        super().__init__(reason)


@dataclass(frozen=True)
class CecCommandResult:
    stdout: str
    returncode: int


CecCommandRunner = Callable[[tuple[str, ...], str], CecCommandResult]


def cec_client_arguments() -> tuple[str, ...]:
    return (
        CEC_CLIENT_COMMAND,
        CEC_CLIENT_SINGLE_COMMAND_FLAG,
        CEC_CLIENT_LOG_LEVEL_FLAG,
        CEC_CLIENT_LOG_LEVEL,
    )


def cec_standby_stdin() -> str:
    return f"{CEC_STANDBY_VERB} {CEC_TV_LOGICAL_ADDRESS}{CEC_COMMAND_NEWLINE}"


def cec_power_on_stdin() -> str:
    return f"{CEC_POWER_ON_VERB} {CEC_TV_LOGICAL_ADDRESS}{CEC_COMMAND_NEWLINE}"


class CecClientTvPower:
    """Starts powered on in memory; standby/on are sent to cec-client."""

    def __init__(self, run_command: CecCommandRunner) -> None:
        self._run_command = run_command
        self._in_standby = False

    def standby(self) -> None:
        self._send(cec_standby_stdin())
        self._in_standby = True

    def power_on(self) -> None:
        self._send(cec_power_on_stdin())
        self._in_standby = False

    def is_in_standby(self) -> bool:
        return self._in_standby

    def _send(self, stdin_text: str) -> None:
        arguments = cec_client_arguments()
        try:
            result = self._run_command(arguments, stdin_text)
        except (OSError, subprocess.SubprocessError) as error:
            raise CecCommandError(
                arguments, stdin_text, "cec-client command failed"
            ) from error
        if result.returncode != 0:
            raise CecCommandError(
                arguments,
                stdin_text,
                f"cec-client exited with status {result.returncode}",
            )


def run_cec_client_command(
    arguments: tuple[str, ...], stdin_text: str
) -> CecCommandResult:
    """T15 wires this runner; tests inject a fake instead."""
    completed = subprocess.run(
        arguments,
        input=stdin_text,
        capture_output=True,
        text=True,
        timeout=CEC_CLIENT_TIMEOUT_SECONDS,
    )
    return CecCommandResult(stdout=completed.stdout, returncode=completed.returncode)


def build_cec_client_tv_power() -> CecClientTvPower:
    return CecClientTvPower(run_cec_client_command)
