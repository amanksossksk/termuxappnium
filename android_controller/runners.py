"""Command runners.

Two runners are provided:

* AdbRunner   - runs shell commands on a remote device via the `adb` binary on
                the host machine.
* RootRunner  - runs shell commands locally on the device itself, using `su -c`
                (i.e. the script is meant to run *on* the device, e.g. via
                Termux on a rooted phone).

Both expose the same interface, so the rest of the library doesn't care which
one is in use.
"""

from __future__ import annotations

import os
import shlex
import subprocess
from abc import ABC, abstractmethod
from typing import Optional

from .config import Config
from .exceptions import CommandError


class CommandResult:
    __slots__ = ("cmd", "returncode", "stdout", "stderr")

    def __init__(self, cmd: str, returncode: int, stdout: str, stderr: str):
        self.cmd = cmd
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr

    @property
    def ok(self) -> bool:
        return self.returncode == 0

    def __repr__(self) -> str:
        return (
            f"CommandResult(rc={self.returncode}, "
            f"stdout={self.stdout[:60]!r}, stderr={self.stderr[:60]!r})"
        )


class BaseRunner(ABC):
    """Common interface for both ADB and root runners."""

    default_timeout: int

    @abstractmethod
    def shell(
        self,
        cmd: str,
        *,
        timeout: Optional[int] = None,
        check: bool = False,
    ) -> CommandResult:
        """Run a shell command on the device and return the result."""

    @abstractmethod
    def popen_shell(self, cmd: str) -> subprocess.Popen:
        """Spawn a streaming shell command on the device.

        Returns a `subprocess.Popen` whose stdout yields lines as they arrive.
        Caller is responsible for `.terminate()` and `.wait()`. Useful for
        long-running commands like `getevent` or `logcat -v threadtime`.
        """

    @abstractmethod
    def push(self, local: str, remote: str, *, timeout: Optional[int] = None) -> None:
        """Copy a file from host to device."""

    @abstractmethod
    def pull(self, remote: str, local: str, *, timeout: Optional[int] = None) -> None:
        """Copy a file from device to host."""

    @abstractmethod
    def install(
        self, apk_path: str, *, replace: bool = True, timeout: Optional[int] = 120
    ) -> CommandResult:
        """Install an APK."""

    @abstractmethod
    def uninstall(
        self, package: str, *, keep_data: bool = False, timeout: Optional[int] = 60
    ) -> CommandResult:
        """Uninstall a package."""

    # convenience
    def run(self, cmd: str, *, check: bool = False) -> str:
        """Mimic the user's original `run(cmd)` API: return stdout."""
        return self.shell(cmd, check=check).stdout

    @staticmethod
    def _quote(cmd: str) -> str:
        """Shell-quote a command string so it can be passed as a single argv."""
        return shlex.quote(cmd)

    def _run_argv(
        self, argv: list[str], *, timeout: Optional[int], input_bytes: bytes | None = None
    ) -> CommandResult:
        try:
            proc = subprocess.run(
                argv,
                capture_output=True,
                timeout=timeout if timeout is not None else self.default_timeout,
                input=input_bytes,
            )
        except subprocess.TimeoutExpired as e:
            raise CommandError(
                cmd=" ".join(argv),
                returncode=-1,
                stdout=(e.stdout or b"").decode("utf-8", "replace"),
                stderr=f"Timed out after {e.timeout}s",
            ) from e
        return CommandResult(
            cmd=" ".join(argv),
            returncode=proc.returncode,
            stdout=proc.stdout.decode("utf-8", "replace").strip(),
            stderr=proc.stderr.decode("utf-8", "replace").strip(),
        )


# ---------------------------------------------------------------------------
# ADB
# ---------------------------------------------------------------------------


class AdbRunner(BaseRunner):
    def __init__(self, config: Config):
        self.config = config
        self.default_timeout = config.adb.default_timeout
        self._adb_argv_prefix = self._build_adb_prefix()

    def _build_adb_prefix(self) -> list[str]:
        argv = [self.config.adb.binary]
        if self.config.adb.host:
            argv += ["-H", str(self.config.adb.host)]
        if self.config.adb.port:
            argv += ["-P", str(self.config.adb.port)]
        if self.config.adb.serial:
            argv += ["-s", str(self.config.adb.serial)]
        return argv

    def _strip_adb_shell(self, cmd: str) -> str:
        # Tolerate users passing "adb shell foo" / "shell foo" / "foo".
        cmd = cmd.strip()
        for prefix in ("adb shell ", "adb -s "):
            if cmd.startswith(prefix):
                cmd = cmd[len(prefix):]
                break
        if cmd.startswith("shell "):
            cmd = cmd[len("shell "):]
        return cmd

    def shell(
        self,
        cmd: str,
        *,
        timeout: Optional[int] = None,
        check: bool = False,
    ) -> CommandResult:
        cmd = self._strip_adb_shell(cmd)
        argv = self._adb_argv_prefix + ["shell", cmd]
        result = self._run_argv(argv, timeout=timeout)
        if check and not result.ok:
            raise CommandError(result.cmd, result.returncode, result.stdout, result.stderr)
        return result

    def popen_shell(self, cmd: str) -> subprocess.Popen:
        cmd = self._strip_adb_shell(cmd)
        argv = self._adb_argv_prefix + ["shell", cmd]
        return subprocess.Popen(
            argv,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            bufsize=1,
            text=True,
        )

    def push(self, local: str, remote: str, *, timeout: Optional[int] = None) -> None:
        if not os.path.exists(local):
            raise FileNotFoundError(local)
        argv = self._adb_argv_prefix + ["push", local, remote]
        result = self._run_argv(argv, timeout=timeout)
        if not result.ok:
            raise CommandError(result.cmd, result.returncode, result.stdout, result.stderr)

    def pull(self, remote: str, local: str, *, timeout: Optional[int] = None) -> None:
        argv = self._adb_argv_prefix + ["pull", remote, local]
        result = self._run_argv(argv, timeout=timeout)
        if not result.ok:
            raise CommandError(result.cmd, result.returncode, result.stdout, result.stderr)

    def install(
        self, apk_path: str, *, replace: bool = True, timeout: Optional[int] = 120
    ) -> CommandResult:
        if not os.path.exists(apk_path):
            raise FileNotFoundError(apk_path)
        argv = self._adb_argv_prefix + ["install"]
        if replace:
            argv.append("-r")
        argv.append(apk_path)
        return self._run_argv(argv, timeout=timeout)

    def uninstall(
        self, package: str, *, keep_data: bool = False, timeout: Optional[int] = 60
    ) -> CommandResult:
        argv = self._adb_argv_prefix + ["uninstall"]
        if keep_data:
            argv.append("-k")
        argv.append(package)
        return self._run_argv(argv, timeout=timeout)


# ---------------------------------------------------------------------------
# Root (on-device, via su)
# ---------------------------------------------------------------------------


class RootRunner(BaseRunner):
    """Runs commands locally on the device using `su -c <cmd>`.

    This expects the script to be running *on* the Android device, e.g. inside
    Termux or any Linux environment that can spawn the device's `su` binary.
    """

    def __init__(self, config: Config):
        self.config = config
        self.default_timeout = config.root.default_timeout
        self._prefix = list(config.root.shell_prefix)
        if not self._prefix:
            self._prefix = [config.root.su_binary, "-c"]

    def _strip_adb_shell(self, cmd: str) -> str:
        cmd = cmd.strip()
        if cmd.startswith("adb shell "):
            cmd = cmd[len("adb shell "):]
        return cmd

    def shell(
        self,
        cmd: str,
        *,
        timeout: Optional[int] = None,
        check: bool = False,
    ) -> CommandResult:
        cmd = self._strip_adb_shell(cmd)
        # Most su implementations want the whole command as ONE arg after -c.
        argv = self._prefix + [cmd]
        result = self._run_argv(argv, timeout=timeout)
        if check and not result.ok:
            raise CommandError(result.cmd, result.returncode, result.stdout, result.stderr)
        return result

    def popen_shell(self, cmd: str) -> subprocess.Popen:
        cmd = self._strip_adb_shell(cmd)
        argv = self._prefix + [cmd]
        return subprocess.Popen(
            argv,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            bufsize=1,
            text=True,
        )

    def push(self, local: str, remote: str, *, timeout: Optional[int] = None) -> None:
        # Local-to-device "push" on the device itself is just a copy.
        if not os.path.exists(local):
            raise FileNotFoundError(local)
        cmd = f"cp {self._quote(local)} {self._quote(remote)}"
        result = self.shell(cmd, timeout=timeout)
        if not result.ok:
            raise CommandError(result.cmd, result.returncode, result.stdout, result.stderr)

    def pull(self, remote: str, local: str, *, timeout: Optional[int] = None) -> None:
        cmd = f"cp {self._quote(remote)} {self._quote(local)}"
        result = self.shell(cmd, timeout=timeout)
        if not result.ok:
            raise CommandError(result.cmd, result.returncode, result.stdout, result.stderr)

    def install(
        self, apk_path: str, *, replace: bool = True, timeout: Optional[int] = 120
    ) -> CommandResult:
        # `pm install` works fine over root.
        flags = "-r" if replace else ""
        cmd = f"pm install {flags} {self._quote(apk_path)}".strip()
        return self.shell(cmd, timeout=timeout)

    def uninstall(
        self, package: str, *, keep_data: bool = False, timeout: Optional[int] = 60
    ) -> CommandResult:
        flags = "-k" if keep_data else ""
        cmd = f"pm uninstall {flags} {self._quote(package)}".strip()
        return self.shell(cmd, timeout=timeout)


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------


def build_runner(config: Config) -> BaseRunner:
    if config.mode == "adb":
        return AdbRunner(config)
    if config.mode == "root":
        return RootRunner(config)
    raise ValueError(f"Unknown mode: {config.mode!r}")
