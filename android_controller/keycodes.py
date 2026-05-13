"""Common Android keycodes for `input keyevent <code>`.

Mapping is intentionally small; pass the integer code directly for anything
that isn't here. Full list:
https://developer.android.com/reference/android/view/KeyEvent
"""

KEYCODES: dict[str, int] = {
    # Navigation
    "HOME": 3,
    "BACK": 4,
    "MENU": 82,
    "APP_SWITCH": 187,
    "RECENT_APPS": 187,
    "DPAD_UP": 19,
    "DPAD_DOWN": 20,
    "DPAD_LEFT": 21,
    "DPAD_RIGHT": 22,
    "DPAD_CENTER": 23,

    # System
    "POWER": 26,
    "WAKEUP": 224,
    "SLEEP": 223,
    "VOLUME_UP": 24,
    "VOLUME_DOWN": 25,
    "VOLUME_MUTE": 164,
    "CAMERA": 27,
    "CALL": 5,
    "ENDCALL": 6,
    "SEARCH": 84,
    "NOTIFICATION": 83,

    # Editing
    "ENTER": 66,
    "TAB": 61,
    "SPACE": 62,
    "DEL": 67,             # backspace
    "FORWARD_DEL": 112,
    "ESCAPE": 111,
    "CAPS_LOCK": 115,

    # Brightness
    "BRIGHTNESS_UP": 221,
    "BRIGHTNESS_DOWN": 220,

    # Media
    "MEDIA_PLAY_PAUSE": 85,
    "MEDIA_STOP": 86,
    "MEDIA_NEXT": 87,
    "MEDIA_PREVIOUS": 88,
    "MEDIA_REWIND": 89,
    "MEDIA_FAST_FORWARD": 90,
    "MEDIA_PLAY": 126,
    "MEDIA_PAUSE": 127,
}


def resolve_keycode(key: str | int) -> int:
    """Convert a key name or integer into an Android keycode int."""
    if isinstance(key, int):
        return key
    if isinstance(key, str):
        if key.isdigit():
            return int(key)
        k = key.upper().replace("KEYCODE_", "")
        if k in KEYCODES:
            return KEYCODES[k]
    raise ValueError(f"Unknown keycode: {key!r}")
