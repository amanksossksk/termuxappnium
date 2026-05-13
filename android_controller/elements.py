"""UI element abstraction backed by `uiautomator dump`.

The Android `uiautomator` tool dumps the current window hierarchy as XML.
We parse that XML and offer a small Appium-flavoured element API:

    el = device.find_element(text="Login")
    el.tap()
    el.bounds       # (left, top, right, bottom)
    el.center       # (x, y)
    el.attrib       # full attribute dict

`find_elements(...)` returns a list. Lookup keys map directly to common
uiautomator attributes:

    text                -> "text"
    content_desc        -> "content-desc"
    resource_id         -> "resource-id"
    class_name          -> "class"
    package             -> "package"
    clickable, enabled, checked, focused, scrollable  (booleans)

Use `text_contains`, `desc_contains`, `resource_id_contains` for partial
matches. Anything else passed in **kwargs is matched as an exact attribute
equality, so you can use raw uiautomator attribute names too.
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Iterable

if TYPE_CHECKING:
    from .device import Device


_BOUNDS_RE = re.compile(r"\[(-?\d+),(-?\d+)\]\[(-?\d+),(-?\d+)\]")


def _parse_bounds(value: str) -> tuple[int, int, int, int] | None:
    if not value:
        return None
    m = _BOUNDS_RE.search(value)
    if not m:
        return None
    return tuple(int(x) for x in m.groups())  # type: ignore[return-value]


_BOOL_ATTRS = {
    "clickable",
    "enabled",
    "checked",
    "checkable",
    "focused",
    "focusable",
    "scrollable",
    "selected",
    "long-clickable",
    "password",
}


_KW_TO_ATTR = {
    "text": "text",
    "content_desc": "content-desc",
    "desc": "content-desc",
    "resource_id": "resource-id",
    "id": "resource-id",
    "class_name": "class",
    "cls": "class",
    "package": "package",
}


@dataclass
class UIElement:
    attrib: dict[str, str]
    _device: "Device"

    # ----- convenience properties ---------------------------------------

    @property
    def text(self) -> str:
        return self.attrib.get("text", "")

    @property
    def content_desc(self) -> str:
        return self.attrib.get("content-desc", "")

    @property
    def resource_id(self) -> str:
        return self.attrib.get("resource-id", "")

    @property
    def class_name(self) -> str:
        return self.attrib.get("class", "")

    @property
    def package(self) -> str:
        return self.attrib.get("package", "")

    @property
    def bounds(self) -> tuple[int, int, int, int] | None:
        return _parse_bounds(self.attrib.get("bounds", ""))

    @property
    def center(self) -> tuple[int, int] | None:
        b = self.bounds
        if not b:
            return None
        l, t, r, btm = b
        return ((l + r) // 2, (t + btm) // 2)

    def is_(self, attr: str) -> bool:
        return self.attrib.get(attr, "false").lower() == "true"

    # ----- actions ------------------------------------------------------

    def tap(self) -> None:
        c = self.center
        if c is None:
            raise ValueError("Element has no bounds, cannot tap")
        self._device.tap(*c)

    def long_press(self, duration_ms: int = 800) -> None:
        c = self.center
        if c is None:
            raise ValueError("Element has no bounds, cannot long_press")
        self._device.long_press(*c, duration_ms=duration_ms)

    def clear(self) -> None:
        """Tap the element then select-all + delete."""
        self.tap()
        self._device.shell("input keyevent KEYCODE_MOVE_END")
        self._device.shell(
            "input keyevent --longpress "
            + " ".join(["67"] * max(1, len(self.text) or 1))
        )

    def set_text(self, value: str) -> None:
        self.tap()
        self._device.type_text(value)

    def __repr__(self) -> str:
        return (
            f"UIElement(text={self.text!r}, "
            f"resource_id={self.resource_id!r}, "
            f"class={self.class_name!r}, "
            f"bounds={self.bounds})"
        )


# ---------------------------------------------------------------------------
# Matching
# ---------------------------------------------------------------------------


def _matches(node_attrib: dict[str, str], filters: dict[str, Any]) -> bool:
    for key, expected in filters.items():
        # contains-style helpers
        if key.endswith("_contains"):
            base = key[: -len("_contains")]
            attr = _KW_TO_ATTR.get(base, base.replace("_", "-"))
            if expected not in node_attrib.get(attr, ""):
                return False
            continue
        if key.endswith("_matches"):
            base = key[: -len("_matches")]
            attr = _KW_TO_ATTR.get(base, base.replace("_", "-"))
            if not re.search(expected, node_attrib.get(attr, "")):
                return False
            continue

        attr = _KW_TO_ATTR.get(key, key.replace("_", "-"))
        if attr in _BOOL_ATTRS:
            actual = node_attrib.get(attr, "false").lower() == "true"
            if bool(expected) != actual:
                return False
        else:
            if node_attrib.get(attr, "") != str(expected):
                return False
    return True


def iter_nodes(xml_text: str) -> Iterable[dict[str, str]]:
    """Yield every node's attribute dict from a uiautomator dump."""
    if not xml_text.strip():
        return
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return
    # uiautomator wraps in <hierarchy>; recursively yield all <node>s
    for el in root.iter("node"):
        yield dict(el.attrib)


def find_elements_in_xml(
    xml_text: str, device: "Device", filters: dict[str, Any]
) -> list[UIElement]:
    out: list[UIElement] = []
    for attrib in iter_nodes(xml_text):
        if _matches(attrib, filters):
            out.append(UIElement(attrib=attrib, _device=device))
    return out
