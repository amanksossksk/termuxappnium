"""Basic usage example.

Run on a host machine (with `adb` installed) **or** directly on the device
(via Termux with root + `su` available). Change `mode` in `config.json` to
switch between the two without touching this script.
"""

from android_controller import Device


def main() -> None:
    d = Device.from_config("config.json")

    print("Mode:", d.mode)
    print("Device info:", d.device_info())
    print("Screen size:", d.screen_size())
    print("Current app:", d.current_app())

    # Wake the device and unlock if needed.
    d.wake()

    # Tap, swipe, type.
    w, h = d.screen_size()
    d.tap(w // 2, h // 2)
    d.swipe(w // 2, int(h * 0.8), w // 2, int(h * 0.2), duration_ms=300)
    d.press_key("HOME")

    # Take a screenshot.
    d.screenshot("home.png")
    print("Saved home.png")

    # Open Chrome to a URL.
    d.open_url("https://example.com")


if __name__ == "__main__":
    main()
