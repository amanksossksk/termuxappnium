"""Record taps and typed text from a running Android app.

How it works
============

We spawn `getevent -lt` on the device (over ADB or `su`) and stream input
events back to Python. Each completed touch (BTN_TOUCH down -> up, or
ABS_MT_TRACKING_ID set -> -1) produces a tap; after the tap we dump the UI
hierarchy and look up the element whose `bounds` contain the tap point —
that's how we recover `text`, `resource-id`, `content-desc`.

For typed text we also poll the UI tree at a fixed interval (default 400 ms)
and emit a `TEXT` event whenever the text of any `EditText` in the current
package changes.

All events can be filtered by foreground package, so you can record only
what happens inside e.g. `mark.via.gp` and ignore the keyboard, status bar,
launcher, etc.

Limitations
-----------

* getevent runs in the kernel so it captures every touch, but the input
  device's coordinate space isn't always the screen's. We try to autodetect
  the touchscreen's max ABS_X/ABS_Y from `getevent -lp` and rescale; if that
  fails, we assume 1:1 (which is true on most modern phones).
* The on-screen keyboard's individual key presses are NOT decoded — they
  arrive as touch events on the keyboard surface. We capture the *resulting
  text* by polling EditText fields instead, which is what you actually want.
* Hardware-key events (back, home, volume, ...) are decoded directly.
"""

from __future__ import annotations

import dataclasses
import json
import re
import sys
import threading
import time
from typing import Callable, Optional, TextIO

from .device import Device
from .elements import find_elements_in_xml


_TAP_MOVE_THRESHOLD_PX = 20      # within this radius we call it a tap, not a swipe
_DEFAULT_POLL_TEXT_MS = 400
_RELEASE_TRACKING_ID = 0xFFFFFFFF


# ---------------------------------------------------------------------------
# Event records
# ---------------------------------------------------------------------------


@dataclasses.dataclass
class RecordedEvent:
    kind: str                # "TAP" | "SWIPE" | "KEY" | "TEXT"
    timestamp: float         # epoch seconds
    data: dict

    def to_json(self) -> str:
        return json.dumps(
            {"kind": self.kind, "ts": round(self.timestamp, 3), **self.data},
            ensure_ascii=False,
        )

    def to_pretty(self) -> str:
        ts = time.strftime("%H:%M:%S", time.localtime(self.timestamp))
        ms = int((self.timestamp - int(self.timestamp)) * 1000)
        head = f"[{ts}.{ms:03d}] {self.kind:<5}"
        if self.kind in ("TAP", "SWIPE"):
            from_ = self.data.get("from")
            to = self.data.get("to")
            extra = []
            if self.data.get("resource_id"):
                extra.append(f"id={self.data['resource_id']}")
            if self.data.get("text"):
                extra.append(f"text={self.data['text']!r}")
            if self.data.get("content_desc"):
                extra.append(f"desc={self.data['content_desc']!r}")
            if self.kind == "TAP":
                body = f"{from_}"
            else:
                body = f"{from_} -> {to} ({self.data.get('duration_ms')}ms)"
            return f"{head} {body}  " + "  ".join(extra)
        if self.kind == "KEY":
            return f"{head} {self.data.get('name', self.data.get('code'))}"
        if self.kind == "TEXT":
            extra = []
            if self.data.get("resource_id"):
                extra.append(f"id={self.data['resource_id']}")
            return (
                f"{head} text={self.data['text']!r}  " + "  ".join(extra)
            )
        return f"{head} {self.data}"


# ---------------------------------------------------------------------------
# getevent stream parser
# ---------------------------------------------------------------------------


# Example line we want to parse:
# [   77272.057] /dev/input/event2: EV_ABS       ABS_MT_POSITION_X    000003e8
_GETEVENT_RE = re.compile(
    r"^(?:\[\s*[\d.]+\s*\]\s+)?(?P<dev>/dev/input/event\d+):\s+"
    r"(?P<type>\w+)\s+(?P<code>\w+)\s+(?P<value>\w+)\s*$"
)


def _parse_hex(value: str) -> int:
    """Parse a getevent value (always hex) tolerating both '0000abcd' and 'DOWN'."""
    try:
        return int(value, 16)
    except ValueError:
        return 0


class _TouchTracker:
    """Tracks one in-flight touch and emits taps/swipes when it ends."""

    def __init__(self, emit: Callable[[str, dict], None]):
        self._emit = emit
        self._touching = False
        self._start_x: Optional[int] = None
        self._start_y: Optional[int] = None
        self._last_x: Optional[int] = None
        self._last_y: Optional[int] = None
        self._start_time: Optional[float] = None

    def feed(self, ev_type: str, code: str, value: str, now: float) -> None:
        if ev_type == "EV_ABS":
            if code == "ABS_MT_POSITION_X" or code == "ABS_X":
                self._last_x = _parse_hex(value)
                if not self._touching:
                    self._open_touch(now)
            elif code == "ABS_MT_POSITION_Y" or code == "ABS_Y":
                self._last_y = _parse_hex(value)
                if not self._touching:
                    self._open_touch(now)
            elif code == "ABS_MT_TRACKING_ID":
                if _parse_hex(value) == _RELEASE_TRACKING_ID:
                    self._close_touch(now)
                else:
                    self._open_touch(now)
        elif ev_type == "EV_KEY":
            if code == "BTN_TOUCH":
                if value.upper() == "DOWN" or _parse_hex(value) == 1:
                    self._open_touch(now)
                elif value.upper() == "UP" or _parse_hex(value) == 0:
                    self._close_touch(now)

    def _open_touch(self, now: float) -> None:
        if self._touching:
            # update start coords if we now know them
            if self._start_x is None and self._last_x is not None:
                self._start_x = self._last_x
            if self._start_y is None and self._last_y is not None:
                self._start_y = self._last_y
            return
        self._touching = True
        self._start_time = now
        self._start_x = self._last_x
        self._start_y = self._last_y

    def _close_touch(self, now: float) -> None:
        if not self._touching:
            return
        sx, sy = self._start_x, self._start_y
        ex, ey = self._last_x, self._last_y
        dur_ms = int((now - (self._start_time or now)) * 1000)
        self._touching = False
        self._start_x = self._start_y = self._start_time = None

        if sx is None or sy is None or ex is None or ey is None:
            return
        dx, dy = ex - sx, ey - sy
        if (dx * dx + dy * dy) ** 0.5 <= _TAP_MOVE_THRESHOLD_PX:
            self._emit("TAP", {"x": ex, "y": ey, "duration_ms": dur_ms})
        else:
            self._emit(
                "SWIPE",
                {
                    "from": [sx, sy],
                    "to": [ex, ey],
                    "duration_ms": dur_ms,
                },
            )


# ---------------------------------------------------------------------------
# Coordinate calibration
# ---------------------------------------------------------------------------


def _parse_touch_calibration(getevent_p_output: str) -> dict[str, tuple[int, int]]:
    """Parse `getevent -lp` output and return per-device {device_path: (max_x, max_y)}."""
    calib: dict[str, tuple[int, int]] = {}
    current_dev: Optional[str] = None
    current_x: Optional[int] = None
    current_y: Optional[int] = None
    has_touch = False
    for line in getevent_p_output.splitlines():
        if line.startswith("add device"):
            if current_dev and has_touch and current_x and current_y:
                calib[current_dev] = (current_x, current_y)
            current_dev = None
            current_x = current_y = None
            has_touch = False
            m = re.search(r":\s*(/dev/input/event\d+)", line)
            if m:
                current_dev = m.group(1)
        elif "ABS_MT_POSITION_X" in line or "ABS_X" in line:
            m = re.search(r"max\s+(\d+)", line)
            if m:
                current_x = int(m.group(1))
        elif "ABS_MT_POSITION_Y" in line or "ABS_Y" in line:
            m = re.search(r"max\s+(\d+)", line)
            if m:
                current_y = int(m.group(1))
        elif "BTN_TOUCH" in line:
            has_touch = True
    if current_dev and has_touch and current_x and current_y:
        calib[current_dev] = (current_x, current_y)
    return calib


# ---------------------------------------------------------------------------
# UI lookup helpers
# ---------------------------------------------------------------------------


def _element_at_point(xml: str, device, x: int, y: int):
    """Return the deepest UIElement whose bounds contain (x,y), or None."""
    from .elements import iter_nodes, UIElement, _parse_bounds

    best = None
    best_area = None
    for attrib in iter_nodes(xml):
        bounds = _parse_bounds(attrib.get("bounds", ""))
        if not bounds:
            continue
        l, t, r, b = bounds
        if l <= x <= r and t <= y <= b:
            area = (r - l) * (b - t)
            if best_area is None or area < best_area:
                best_area = area
                best = UIElement(attrib=dict(attrib), _device=device)
    return best


def _editable_snapshot(xml: str) -> dict[str, str]:
    """Snapshot all EditText fields in the dump: {resource_id_or_index: text}."""
    from .elements import iter_nodes

    out: dict[str, str] = {}
    for i, attrib in enumerate(iter_nodes(xml)):
        cls = attrib.get("class", "")
        if "EditText" not in cls and attrib.get("password", "").lower() != "true":
            # Capture password fields too even if not literally EditText
            pass
        if "EditText" in cls or attrib.get("password", "").lower() == "true":
            rid = attrib.get("resource-id") or f"#{i}"
            out[rid] = attrib.get("text", "")
    return out


# ---------------------------------------------------------------------------
# Recorder
# ---------------------------------------------------------------------------


class Recorder:
    """Record user interactions with a target Android app.

    Example
    -------

        from android_controller import Device
        from android_controller.recorder import Recorder

        d = Device.from_config("config.json")
        Recorder(d, target_package="mark.via.gp", output="via.jsonl").run()
    """

    def __init__(
        self,
        device: Device,
        target_package: Optional[str] = None,
        output: Optional[str] = None,
        *,
        poll_text_ms: int = _DEFAULT_POLL_TEXT_MS,
        launch_app: bool = True,
        print_events: bool = True,
        assume_one_to_one: bool = False,
    ):
        self.device = device
        self.target_package = target_package
        self.output_path = output
        self.poll_text_ms = poll_text_ms
        self.launch_app = launch_app
        self.print_events = print_events
        self.assume_one_to_one = assume_one_to_one

        self._proc = None
        self._stop = threading.Event()
        self._out_fp: Optional[TextIO] = None
        self._calib: dict[str, tuple[int, int]] = {}
        self._screen_w = 0
        self._screen_h = 0
        self._last_edit_snapshot: dict[str, str] = {}
        self._last_xml: str = ""
        self._xml_lock = threading.Lock()

    # ----- lifecycle ---------------------------------------------------

    def run(self) -> None:
        try:
            self._setup()
            self._loop()
        except KeyboardInterrupt:
            self._log_status("Interrupted, shutting down...")
        finally:
            self._teardown()

    def stop(self) -> None:
        self._stop.set()
        if self._proc is not None:
            try:
                self._proc.terminate()
            except Exception:
                pass

    # ----- internals ---------------------------------------------------

    def _setup(self) -> None:
        if self.output_path:
            self._out_fp = open(self.output_path, "w", encoding="utf-8")
        if self.launch_app and self.target_package:
            self._log_status(f"Launching {self.target_package} ...")
            try:
                self.device.start_app(self.target_package)
            except Exception as e:
                self._log_status(f"Failed to launch app ({e}); continuing anyway.")
            time.sleep(1.0)

        self._screen_w, self._screen_h = self.device.screen_size()
        self._log_status(f"Screen: {self._screen_w}x{self._screen_h}")

        if not self.assume_one_to_one:
            try:
                cal_out = self.device.shell("getevent -lp", timeout=10).stdout
                self._calib = _parse_touch_calibration(cal_out)
                if self._calib:
                    self._log_status(f"Touch calibration: {self._calib}")
            except Exception as e:
                self._log_status(f"Couldn't read getevent -lp ({e}); assuming 1:1.")

        # Kick off the UI poller (for text changes)
        threading.Thread(target=self._text_poll_loop, daemon=True).start()

        # Kick off the getevent stream
        self._proc = self.device.runner.popen_shell("getevent -lt")
        threading.Thread(target=self._drain_stderr, daemon=True).start()
        self._log_status(
            "Recording... (Ctrl+C to stop)"
            + (f"  -> {self.output_path}" if self.output_path else "")
        )

    def _teardown(self) -> None:
        self.stop()
        if self._proc is not None:
            try:
                self._proc.wait(timeout=2)
            except Exception:
                try:
                    self._proc.kill()
                except Exception:
                    pass
        if self._out_fp:
            try:
                self._out_fp.flush()
                self._out_fp.close()
            except Exception:
                pass

    def _loop(self) -> None:
        assert self._proc is not None
        tracker = _TouchTracker(emit=self._emit_touch)
        active_dev: Optional[str] = None
        for raw_line in self._proc.stdout:  # type: ignore[union-attr]
            if self._stop.is_set():
                break
            line = raw_line.rstrip()
            m = _GETEVENT_RE.match(line)
            if not m:
                continue
            dev = m.group("dev")
            ev_type = m.group("type")
            code = m.group("code")
            value = m.group("value")
            now = time.time()
            # Pin to the first device that emits touch events; ignore the rest.
            if ev_type == "EV_ABS" and code in (
                "ABS_MT_POSITION_X",
                "ABS_MT_POSITION_Y",
                "ABS_X",
                "ABS_Y",
                "ABS_MT_TRACKING_ID",
            ) or (ev_type == "EV_KEY" and code == "BTN_TOUCH"):
                if active_dev is None:
                    active_dev = dev
                if dev == active_dev:
                    tracker.feed(ev_type, code, value, now)
                continue
            if ev_type == "EV_KEY" and code.startswith("KEY_"):
                if value.upper() == "DOWN" or _parse_hex(value) == 1:
                    self._emit_key(code, now)

    def _drain_stderr(self) -> None:
        proc = self._proc
        if proc is None or proc.stderr is None:
            return
        for line in proc.stderr:
            # getevent prints non-fatal warnings; ignore unless very chatty.
            if "Permission denied" in line:
                self._log_status(f"getevent: {line.strip()}")

    # ----- emit ---------------------------------------------------------

    def _emit_touch(self, kind: str, data: dict) -> None:
        # scale device coords -> screen coords
        if kind == "TAP":
            x, y = self._scale(data["x"], data["y"])
            data = {**data, "x": x, "y": y, "from": [x, y]}
        else:
            fx, fy = self._scale(*data["from"])
            tx, ty = self._scale(*data["to"])
            data = {**data, "from": [fx, fy], "to": [tx, ty]}

        # Only tag with element/package on TAPs (swipes don't have a clear target)
        if kind == "TAP":
            xml = self._capture_ui()
            pkg = self._current_package(xml)
            if self.target_package and pkg != self.target_package:
                return
            el = _element_at_point(xml, self.device, data["x"], data["y"])
            if el is not None:
                data["resource_id"] = el.resource_id
                data["text"] = el.text
                data["content_desc"] = el.content_desc
                data["class"] = el.class_name
            data["package"] = pkg

        self._emit(RecordedEvent(kind=kind, timestamp=time.time(), data=data))

    def _emit_key(self, code: str, now: float) -> None:
        name = code.replace("KEY_", "")
        self._emit(RecordedEvent(kind="KEY", timestamp=now, data={"name": name, "code": code}))

    def _emit(self, ev: RecordedEvent) -> None:
        if self.print_events:
            print(ev.to_pretty(), flush=True)
        if self._out_fp:
            self._out_fp.write(ev.to_json() + "\n")
            self._out_fp.flush()

    # ----- helpers ------------------------------------------------------

    def _scale(self, x: int, y: int) -> tuple[int, int]:
        if not self._calib:
            return x, y
        # If any device matches our active tracker, use the first calibration.
        max_x, max_y = next(iter(self._calib.values()))
        sx = int(round(x * self._screen_w / max_x)) if max_x else x
        sy = int(round(y * self._screen_h / max_y)) if max_y else y
        return sx, sy

    def _capture_ui(self) -> str:
        try:
            xml = self.device.dump_ui()
            with self._xml_lock:
                self._last_xml = xml
            return xml
        except Exception:
            with self._xml_lock:
                return self._last_xml

    def _current_package(self, xml: str) -> str:
        # The hierarchy nodes all have the same package; grab the first.
        m = re.search(r'package="([^"]+)"', xml or "")
        if m:
            return m.group(1)
        try:
            return self.device.current_app().get("package", "")
        except Exception:
            return ""

    def _text_poll_loop(self) -> None:
        while not self._stop.is_set():
            time.sleep(self.poll_text_ms / 1000)
            try:
                xml = self._capture_ui()
            except Exception:
                continue
            if not xml:
                continue
            pkg = self._current_package(xml)
            if self.target_package and pkg != self.target_package:
                self._last_edit_snapshot = {}
                continue
            snap = _editable_snapshot(xml)
            for rid, text in snap.items():
                prev = self._last_edit_snapshot.get(rid)
                if prev is not None and prev != text and text:
                    self._emit(
                        RecordedEvent(
                            kind="TEXT",
                            timestamp=time.time(),
                            data={
                                "resource_id": rid if not rid.startswith("#") else "",
                                "text": text,
                                "previous": prev,
                                "package": pkg,
                            },
                        )
                    )
            self._last_edit_snapshot = snap

    def _log_status(self, msg: str) -> None:
        if self.print_events:
            print(f"# {msg}", file=sys.stderr, flush=True)
