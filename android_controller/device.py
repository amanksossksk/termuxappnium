"""High-level, Appium-flavoured device API."""

from __future__ import annotations

import base64
import os
import re
import shlex
import time
from typing import Any, Optional

from .config import Config
from .elements import UIElement, find_elements_in_xml
from .exceptions import (
    CommandError,
    ElementNotFoundError,
    TimeoutError as ACTimeoutError,
)
from .keycodes import resolve_keycode
from .runners import AdbRunner, BaseRunner, CommandResult, RootRunner, build_runner


class Device:
    """An Android device controllable via either `adb` or on-device `su -c`.

    Construct with `Device.from_config("config.json")` or by passing a
    `Config` / runner directly.
    """

    def __init__(self, config: Config, runner: Optional[BaseRunner] = None):
        self.config = config
        self.runner: BaseRunner = runner or build_runner(config)

    # ------------------------------------------------------------------
    # Construction
    # ------------------------------------------------------------------

    @classmethod
    def from_config(cls, path: str = "config.json") -> "Device":
        return cls(Config.from_file(path))

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Device":
        return cls(Config.from_dict(data))

    @property
    def mode(self) -> str:
        return self.config.mode

    @property
    def is_root(self) -> bool:
        return isinstance(self.runner, RootRunner)

    # ------------------------------------------------------------------
    # Raw shell access
    # ------------------------------------------------------------------

    def shell(self, cmd: str, *, timeout: Optional[int] = None, check: bool = False) -> CommandResult:
        return self.runner.shell(cmd, timeout=timeout, check=check)

    def run(self, cmd: str) -> str:
        """Drop-in replacement for the user's original `run(cmd)` helper."""
        return self.runner.run(cmd)

    # ------------------------------------------------------------------
    # File transfer
    # ------------------------------------------------------------------

    def push(self, local: str, remote: str, *, timeout: Optional[int] = None) -> None:
        self.runner.push(local, remote, timeout=timeout)

    def pull(self, remote: str, local: str, *, timeout: Optional[int] = None) -> None:
        self.runner.pull(remote, local, timeout=timeout)

    # ------------------------------------------------------------------
    # Touch / gestures
    # ------------------------------------------------------------------

    def tap(self, x: int, y: int) -> None:
        self.shell(f"input tap {int(x)} {int(y)}", check=True)

    def double_tap(self, x: int, y: int, interval_ms: int = 100) -> None:
        self.tap(x, y)
        time.sleep(interval_ms / 1000)
        self.tap(x, y)

    def long_press(self, x: int, y: int, duration_ms: int = 800) -> None:
        self.shell(
            f"input swipe {int(x)} {int(y)} {int(x)} {int(y)} {int(duration_ms)}",
            check=True,
        )

    def swipe(
        self,
        x1: int,
        y1: int,
        x2: int,
        y2: int,
        duration_ms: int = 300,
    ) -> None:
        self.shell(
            f"input swipe {int(x1)} {int(y1)} {int(x2)} {int(y2)} {int(duration_ms)}",
            check=True,
        )

    def drag(
        self,
        x1: int,
        y1: int,
        x2: int,
        y2: int,
        duration_ms: int = 1000,
    ) -> None:
        # `input draganddrop` is preferred on newer Androids, but `swipe` with
        # a longer duration is universally supported.
        try:
            self.shell(
                f"input draganddrop {int(x1)} {int(y1)} {int(x2)} {int(y2)} {int(duration_ms)}",
                check=True,
            )
        except CommandError:
            self.swipe(x1, y1, x2, y2, duration_ms=duration_ms)

    def scroll_up(self, distance_ratio: float = 0.5, duration_ms: int = 300) -> None:
        w, h = self.screen_size()
        cx = w // 2
        y1 = int(h * 0.8)
        y2 = int(h * (0.8 - distance_ratio))
        self.swipe(cx, y1, cx, max(0, y2), duration_ms=duration_ms)

    def scroll_down(self, distance_ratio: float = 0.5, duration_ms: int = 300) -> None:
        w, h = self.screen_size()
        cx = w // 2
        y1 = int(h * 0.2)
        y2 = int(h * (0.2 + distance_ratio))
        self.swipe(cx, y1, cx, min(h - 1, y2), duration_ms=duration_ms)

    def scroll_left(self, distance_ratio: float = 0.5, duration_ms: int = 300) -> None:
        w, h = self.screen_size()
        cy = h // 2
        x1 = int(w * 0.2)
        x2 = int(w * (0.2 + distance_ratio))
        self.swipe(x1, cy, min(w - 1, x2), cy, duration_ms=duration_ms)

    def scroll_right(self, distance_ratio: float = 0.5, duration_ms: int = 300) -> None:
        w, h = self.screen_size()
        cy = h // 2
        x1 = int(w * 0.8)
        x2 = int(w * (0.8 - distance_ratio))
        self.swipe(x1, cy, max(0, x2), cy, duration_ms=duration_ms)

    # ------------------------------------------------------------------
    # Keyboard / text
    # ------------------------------------------------------------------

    def press_key(self, key) -> None:
        code = resolve_keycode(key)
        self.shell(f"input keyevent {code}", check=True)

    def long_press_key(self, key) -> None:
        code = resolve_keycode(key)
        self.shell(f"input keyevent --longpress {code}", check=True)

    def type_text(self, text: str) -> None:
        """Type a literal string via `input text`.

        `input text` does not accept spaces directly on all Androids, so we
        replace spaces with %s (which `input text` interprets as a space).
        Non-ASCII characters may not work on stock keyboards; consider using
        an IME like Appium's UnicodeIME for full Unicode support.
        """
        if not text:
            return
        safe = text.replace(" ", "%s")
        # Escape characters that are special to the shell.
        safe = (
            safe.replace("\\", "\\\\")
            .replace("'", "\\'")
            .replace('"', '\\"')
            .replace("`", "\\`")
            .replace("$", "\\$")
            .replace("(", "\\(")
            .replace(")", "\\)")
            .replace("&", "\\&")
            .replace("<", "\\<")
            .replace(">", "\\>")
            .replace("|", "\\|")
            .replace(";", "\\;")
        )
        self.shell(f'input text "{safe}"', check=True)

    def clear_text(self, count: int = 100) -> None:
        """Press backspace `count` times (defaults to 100, plenty to clear most fields)."""
        for _ in range(count):
            self.shell("input keyevent 67")

    # ------------------------------------------------------------------
    # Screen / display
    # ------------------------------------------------------------------

    def screen_size(self) -> tuple[int, int]:
        """Return (width, height) in pixels."""
        out = self.shell("wm size").stdout
        # Output looks like "Physical size: 1080x2340" possibly followed by
        # "Override size: 1080x1920". Prefer override if present.
        match = re.search(r"Override size:\s*(\d+)x(\d+)", out) or re.search(
            r"Physical size:\s*(\d+)x(\d+)", out
        )
        if not match:
            raise CommandError("wm size", -1, out, "Unable to parse screen size")
        return int(match.group(1)), int(match.group(2))

    def screen_density(self) -> int:
        out = self.shell("wm density").stdout
        match = re.search(r"Override density:\s*(\d+)", out) or re.search(
            r"Physical density:\s*(\d+)", out
        )
        if not match:
            raise CommandError("wm density", -1, out, "Unable to parse density")
        return int(match.group(1))

    def orientation(self) -> int:
        """0=portrait, 1=landscape, 2=reverse portrait, 3=reverse landscape (best effort)."""
        out = self.shell(
            "dumpsys input | grep SurfaceOrientation"
        ).stdout
        match = re.search(r"SurfaceOrientation:\s*(\d+)", out)
        return int(match.group(1)) if match else 0

    def set_orientation(self, rotation: int) -> None:
        """rotation: 0|1|2|3."""
        self.shell("settings put system accelerometer_rotation 0", check=True)
        self.shell(
            f"settings put system user_rotation {int(rotation) % 4}", check=True
        )

    def wake(self) -> None:
        self.press_key("WAKEUP")

    def sleep_screen(self) -> None:
        self.press_key("SLEEP")

    def is_screen_on(self) -> bool:
        out = self.shell("dumpsys power | grep 'mWakefulness='").stdout
        return "Awake" in out

    def unlock(self) -> None:
        """Wake + dismiss the lock screen (only works on unsecured locks)."""
        self.wake()
        self.press_key("MENU")
        self.swipe_unlock()

    def swipe_unlock(self) -> None:
        w, h = self.screen_size()
        self.swipe(w // 2, int(h * 0.85), w // 2, int(h * 0.15), duration_ms=300)

    # ------------------------------------------------------------------
    # Screenshot
    # ------------------------------------------------------------------

    def screenshot(self, local_path: str) -> str:
        """Capture a PNG screenshot and save it to `local_path`. Returns the path."""
        remote = self.config.device.screenshot_path
        self.shell(f"screencap -p {shlex.quote(remote)}", check=True, timeout=60)
        # In root mode the file is already local to the device; copy is a no-op
        # if it happens to be the same path.
        if isinstance(self.runner, AdbRunner):
            self.pull(remote, local_path)
        else:
            if os.path.abspath(remote) != os.path.abspath(local_path):
                os.makedirs(os.path.dirname(os.path.abspath(local_path)) or ".", exist_ok=True)
                # copy from device path to user's local path
                self.pull(remote, local_path)
        return local_path

    def screenshot_bytes(self) -> bytes:
        """Return raw PNG bytes (uses base64 over the wire to avoid binary issues)."""
        # `screencap -p` writes a PNG to stdout; we base64-encode it on-device
        # to safely pipe through the shell.
        cmd = "screencap -p | base64"
        result = self.shell(cmd, check=True, timeout=60)
        # Strip whitespace/newlines and decode.
        return base64.b64decode("".join(result.stdout.split()))

    # ------------------------------------------------------------------
    # UI hierarchy / element queries
    # ------------------------------------------------------------------

    def dump_ui(self) -> str:
        """Run `uiautomator dump` and return the XML."""
        remote = self.config.device.ui_dump_path
        self.shell(f"uiautomator dump {shlex.quote(remote)}", check=True, timeout=30)
        out = self.shell(f"cat {shlex.quote(remote)}", timeout=30)
        return out.stdout

    def source(self) -> str:
        """Appium alias for `dump_ui`."""
        return self.dump_ui()

    def find_elements(self, **filters) -> list[UIElement]:
        xml = self.dump_ui()
        return find_elements_in_xml(xml, self, filters)

    def find_element(self, **filters) -> UIElement | None:
        els = self.find_elements(**filters)
        return els[0] if els else None

    def find_element_or_raise(self, **filters) -> UIElement:
        el = self.find_element(**filters)
        if el is None:
            raise ElementNotFoundError(f"No element matched {filters!r}")
        return el

    def wait_for_element(
        self,
        timeout: float = 10.0,
        poll: float = 0.5,
        **filters,
    ) -> UIElement:
        """Poll the UI hierarchy until an element matching filters appears."""
        deadline = time.time() + timeout
        last_xml = ""
        while time.time() < deadline:
            xml = self.dump_ui()
            last_xml = xml
            els = find_elements_in_xml(xml, self, filters)
            if els:
                return els[0]
            time.sleep(poll)
        raise ACTimeoutError(
            f"Timed out after {timeout}s waiting for element {filters!r}"
        )

    def wait_until_gone(
        self,
        timeout: float = 10.0,
        poll: float = 0.5,
        **filters,
    ) -> None:
        deadline = time.time() + timeout
        while time.time() < deadline:
            xml = self.dump_ui()
            els = find_elements_in_xml(xml, self, filters)
            if not els:
                return
            time.sleep(poll)
        raise ACTimeoutError(
            f"Element {filters!r} still present after {timeout}s"
        )

    def exists(self, **filters) -> bool:
        return self.find_element(**filters) is not None

    # Appium-style helpers
    def tap_text(self, text: str) -> None:
        self.find_element_or_raise(text=text).tap()

    def tap_id(self, resource_id: str) -> None:
        self.find_element_or_raise(resource_id=resource_id).tap()

    def tap_desc(self, content_desc: str) -> None:
        self.find_element_or_raise(content_desc=content_desc).tap()

    # ------------------------------------------------------------------
    # App / package management
    # ------------------------------------------------------------------

    def list_packages(self, filter_str: str | None = None) -> list[str]:
        """Return installed package names."""
        cmd = "pm list packages"
        if filter_str:
            cmd += f" {shlex.quote(filter_str)}"
        out = self.shell(cmd).stdout
        return sorted(
            line.split(":", 1)[1].strip()
            for line in out.splitlines()
            if line.startswith("package:")
        )

    def is_installed(self, package: str) -> bool:
        return package in self.list_packages(package)

    def install_apk(self, apk_path: str, *, replace: bool = True) -> CommandResult:
        """Install an APK.

        On Termux/root mode we cannot let `pm install` see a file under
        /data/data/com.termux/... because pm runs as `system` and won't have
        permission. We stage the APK under `/data/local/tmp` first.
        """
        if isinstance(self.runner, RootRunner):
            return self._install_apk_root(apk_path, replace=replace)
        return self.runner.install(apk_path, replace=replace)

    def _install_apk_root(self, apk_path: str, *, replace: bool) -> CommandResult:
        if not os.path.exists(apk_path):
            raise FileNotFoundError(apk_path)
        tmp = self.config.device.tmp_dir.rstrip("/")
        staged = f"{tmp}/{os.path.basename(apk_path)}"
        self.shell(f"mkdir -p {shlex.quote(tmp)}", check=True)
        # Copy via the root shell so the file ends up owned in a place pm can read.
        self.shell(
            f"cp {shlex.quote(os.path.abspath(apk_path))} {shlex.quote(staged)}",
            check=True,
            timeout=120,
        )
        self.shell(f"chmod 644 {shlex.quote(staged)}", check=True)
        flags = "-r" if replace else ""
        return self.shell(f"pm install {flags} {shlex.quote(staged)}".strip(), timeout=120)

    def uninstall(self, package: str, *, keep_data: bool = False) -> CommandResult:
        return self.runner.uninstall(package, keep_data=keep_data)

    def start_app(self, package: str, *, activity: str | None = None) -> None:
        """Launch an app by package (optionally specifying activity).

        Prefers `cmd package resolve-activity` + `am start -n PKG/ACT`, which
        is the modern, reliable way. Falls back to `monkey` if the launcher
        activity can't be resolved.
        """
        if not activity:
            activity = self.resolve_launcher_activity(package)
        if activity:
            component = activity if "/" in activity else f"{package}/{activity}"
            self.shell(
                "am start -W "
                "-a android.intent.action.MAIN "
                "-c android.intent.category.LAUNCHER "
                f"-n {shlex.quote(component)}",
                check=True,
            )
            return
        # Fallback: monkey. We don't check= here because monkey often returns
        # weird exit codes even on success.
        self.shell(
            "monkey -p " + shlex.quote(package) + " -c android.intent.category.LAUNCHER 1",
            timeout=30,
        )

    def resolve_launcher_activity(self, package: str) -> str | None:
        """Return 'package/Activity' for the LAUNCHER activity, or None.

        Works on Android 7+ via `cmd package`. Falls back to parsing
        `dumpsys package` for older devices.
        """
        # Modern path
        out = self.shell(
            "cmd package resolve-activity --brief "
            "-c android.intent.category.LAUNCHER " + shlex.quote(package)
        ).stdout
        for line in out.splitlines():
            line = line.strip()
            if "/" in line and " " not in line:
                return line
        # Older fallback: dumpsys package
        out = self.shell(
            "dumpsys package " + shlex.quote(package)
        ).stdout
        match = re.search(
            r"([A-Za-z][\w.]*\." + re.escape(package.split(".")[-1])
            + r"|" + re.escape(package) + r")/([A-Za-z0-9_.$]+)",
            out,
        )
        if match:
            # Try a more specific search first
            pass
        match = re.search(
            re.escape(package) + r"/([A-Za-z0-9_.$]+)",
            out,
        )
        if match:
            return f"{package}/{match.group(1)}"
        return None

    def stop_app(self, package: str) -> None:
        self.shell(f"am force-stop {shlex.quote(package)}", check=True)

    def clear_app_data(self, package: str) -> CommandResult:
        return self.shell(f"pm clear {shlex.quote(package)}")

    def current_app(self) -> dict[str, str]:
        """Return {'package': ..., 'activity': ...} for the foreground app."""
        out = self.shell(
            "dumpsys window windows | grep -E 'mCurrentFocus|mFocusedApp'"
        ).stdout
        match = re.search(r"([A-Za-z][\w.]+)/([A-Za-z][\w.$]*)", out)
        if not match:
            return {"package": "", "activity": ""}
        return {"package": match.group(1), "activity": match.group(2)}

    def open_url(self, url: str) -> None:
        self.shell(
            "am start -a android.intent.action.VIEW -d " + shlex.quote(url),
            check=True,
        )

    # ------------------------------------------------------------------
    # Device info / settings
    # ------------------------------------------------------------------

    def get_prop(self, name: str) -> str:
        return self.shell(f"getprop {shlex.quote(name)}").stdout.strip()

    def set_prop(self, name: str, value: str) -> CommandResult:
        return self.shell(f"setprop {shlex.quote(name)} {shlex.quote(value)}")

    def device_info(self) -> dict[str, str]:
        keys = [
            "ro.product.model",
            "ro.product.manufacturer",
            "ro.product.brand",
            "ro.product.device",
            "ro.build.version.release",
            "ro.build.version.sdk",
            "ro.serialno",
        ]
        info: dict[str, str] = {}
        for k in keys:
            info[k] = self.get_prop(k)
        return info

    def battery(self) -> dict[str, str]:
        out = self.shell("dumpsys battery").stdout
        result: dict[str, str] = {}
        for line in out.splitlines():
            line = line.strip()
            if ":" in line:
                k, v = line.split(":", 1)
                result[k.strip()] = v.strip()
        return result

    def ip_addresses(self) -> list[str]:
        out = self.shell("ip -o addr show").stdout
        return re.findall(r"inet\s+([\d.]+)/", out)

    def get_setting(self, namespace: str, name: str) -> str:
        """namespace in {system,secure,global}."""
        return self.shell(
            f"settings get {namespace} {shlex.quote(name)}"
        ).stdout.strip()

    def put_setting(self, namespace: str, name: str, value: str) -> CommandResult:
        return self.shell(
            f"settings put {namespace} {shlex.quote(name)} {shlex.quote(value)}"
        )

    # ------------------------------------------------------------------
    # Network / connectivity
    # ------------------------------------------------------------------

    def wifi(self, on: bool) -> CommandResult:
        return self.shell(f"svc wifi {'enable' if on else 'disable'}")

    def data(self, on: bool) -> CommandResult:
        return self.shell(f"svc data {'enable' if on else 'disable'}")

    def airplane_mode(self, on: bool) -> None:
        self.put_setting("global", "airplane_mode_on", "1" if on else "0")
        self.shell(
            "am broadcast -a android.intent.action.AIRPLANE_MODE --ez state "
            + ("true" if on else "false")
        )

    # ------------------------------------------------------------------
    # Logging
    # ------------------------------------------------------------------

    def logcat(self, lines: int = 200, *, filter_tag: str | None = None) -> str:
        if filter_tag:
            return self.shell(
                f"logcat -d -t {int(lines)} -s {shlex.quote(filter_tag)}"
            ).stdout
        return self.shell(f"logcat -d -t {int(lines)}").stdout

    def clear_logcat(self) -> None:
        self.shell("logcat -c", check=True)
