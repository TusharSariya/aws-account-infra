"""IMM2 status and idempotent wake; deliberately no forced-off/reset operation."""

from contextlib import contextmanager
from dataclasses import dataclass
import fcntl
import json
from pathlib import Path
import re
import subprocess
import sys
from .errors import RetryObservation


class PowerError(RuntimeError):
    pass


class PowerUnavailable(PowerError, RetryObservation):
    """A transport failure requires a fresh power observation, never assumed off."""


def worker_failure(output, operation):
    try:
        category = json.loads(output).get("error")
    except (ValueError, AttributeError):
        category = None
    if category in {
        "TimeoutError",
        "ConnectionResetError",
        "ConnectionRefusedError",
        "BrokenPipeError",
        "EOFError",
    }:
        return PowerUnavailable(f"{operation}: transport unavailable ({category})")
    # Never echo the arbitrary worker output, even when malformed.
    return PowerError(f"{operation}: rejected or invalid worker response")


@dataclass(frozen=True)
class PowerState:
    power: str
    detail: str | None = None


def response_lines(output: str) -> list[str]:
    lines = [
        re.sub(r"^system>\s*", "", line.strip()).strip()
        for line in output.replace("\r", "").splitlines()
    ]
    lines = [line for line in lines if line]
    if any(
        re.search(r"\b(error|failed|invalid|denied|unexpected)\b", line, re.I)
        for line in lines
    ):
        raise PowerError("IMM2 rejected the command")
    return lines


def parse_power(output: str) -> PowerState:
    lines = response_lines(output)
    # A command echo is not an observed power state.
    lines = [line for line in lines if line != "power state"]
    states = [
        line.removeprefix("power ")
        for line in lines
        if line in ("power on", "power off")
    ]
    if len(states) != 1:
        raise PowerError("Missing or ambiguous IMM2 power state; never assume off")
    other = [line for line in lines if line not in ("power on", "power off")]
    if len(other) > 1 or any(not line.startswith("State:") for line in other):
        raise PowerError("Unrecognized IMM2 power response")
    return PowerState(states[0], other[0][6:].strip() if other else None)


def parse_ack(output: str) -> None:
    lines = [line for line in response_lines(output) if line != "power on"]
    if lines != ["ok"]:
        raise PowerUnavailable("IMM2 did not acknowledge wake; re-observe before retry")


class SSHTransport:
    def get_power(self):
        return parse_power(self.run("power state"))

    def request_on(self):
        parse_ack(self.run("power on"))

    def __init__(self, config: Path, target: str):
        self.config, self.target = config, target

    def run(self, command: str) -> str:
        if command not in ("power state", "power on"):
            raise PowerError("Command is outside the power adapter allowlist")
        # A child deadline bounds connect/auth/channel setup as well as reads.
        try:
            result = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "homelab_capacity.ssh_worker",
                    str(self.config),
                    self.target,
                    command,
                ],
                capture_output=True,
                text=True,
                timeout=30,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise PowerUnavailable(
                "IMM2 operation timed out; outcome unknown, re-observe"
            ) from exc
        if result.returncode:
            raise worker_failure(result.stdout, "IMM2 " + command)
        try:
            return json.loads(result.stdout)["output"]
        except (ValueError, KeyError, TypeError):
            raise PowerUnavailable("IMM2 incomplete response; re-observe") from None


class IPMITransport:
    def __init__(self, config: Path, target: str):
        self.config, self.target = config, target

    def operation(self, action):
        try:
            result = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "homelab_capacity.ipmi_worker",
                    str(self.config),
                    self.target,
                    action,
                ],
                capture_output=True,
                text=True,
                timeout=25,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise PowerUnavailable(
                "IPMI deadline; outcome unknown, re-observe"
            ) from exc
        if result.returncode:
            raise worker_failure(result.stdout, "IPMI " + action)
        try:
            return json.loads(result.stdout)
        except ValueError:
            raise PowerUnavailable("IPMI incomplete response; re-observe") from None

    def get_power(self):
        result = self.operation("status")
        if result.get("powerstate") not in ("on", "off") or "error" in result:
            raise PowerError("IPMI returned unknown power state")
        return PowerState(result["powerstate"])

    def request_on(self):
        result = self.operation("on")
        if result not in ({"powerstate": "on"}, {"pendingpowerstate": "on"}):
            raise PowerError("IPMI did not acknowledge wake; re-observe")


class PowerController:
    def __init__(self, config: Path, target: str, transport=None):
        self.config = Path(config).expanduser().resolve()
        data = json.loads(self.config.read_text())
        if target not in data["hosts"] or not re.fullmatch(
            r"[a-z][a-z0-9-]{0,31}", target
        ):
            raise PowerError("Unknown registered host")
        self.target = target
        self.lock_dir = Path(data["lock_dir"]).expanduser()
        mode = data["hosts"][target].get("transport", "ipmi")
        if mode not in ("ipmi", "ssh"):
            raise PowerError("Unsupported power transport")
        self.transport = transport or (
            IPMITransport if mode == "ipmi" else SSHTransport
        )(self.config, target)

    @contextmanager
    def locked(self):
        self.lock_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
        with (self.lock_dir / (self.target + ".lock")).open("a") as lock:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as exc:
                raise PowerError("Host operation already in progress") from exc
            try:
                yield
            finally:
                fcntl.flock(lock, fcntl.LOCK_UN)

    def get_power(self) -> PowerState:
        return self.transport.get_power()

    def ensure_on(self) -> dict:
        with self.locked():
            before = self.get_power()
            if before.power == "on":
                return {
                    "target": self.target,
                    "power": "on",
                    "changed": False,
                    "detail": before.detail,
                }
            self.transport.request_on()
            after = self.get_power()
            return {
                "target": self.target,
                "power": after.power,
                "changed": True,
                "phase": "on" if after.power == "on" else "wake-requested",
                "detail": after.detail,
            }
