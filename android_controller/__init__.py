"""android_controller - Appium-style Android device control over ADB or on-device root (su).

Quick start:

    from android_controller import Device

    d = Device.from_config("config.json")
    d.tap(500, 1000)
    d.swipe(500, 1500, 500, 500, duration_ms=300)
    d.type_text("hello world")
    d.press_key("BACK")
    d.screenshot("out.png")

    # UI elements (parsed from `uiautomator dump`)
    el = d.find_element(text="Settings")
    if el:
        el.tap()
"""

from .config import Config
from .device import Device
from .elements import UIElement
from .exceptions import (
    AndroidControllerError,
    CommandError,
    ElementNotFoundError,
    ConfigError,
)
from .recorder import Recorder, RecordedEvent

__all__ = [
    "Config",
    "Device",
    "UIElement",
    "Recorder",
    "RecordedEvent",
    "AndroidControllerError",
    "CommandError",
    "ElementNotFoundError",
    "ConfigError",
]

__version__ = "0.1.0"
