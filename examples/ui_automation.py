"""UI automation example: find elements, tap them, type into them, wait."""

from android_controller import Device


def main() -> None:
    d = Device.from_config("config.json")

    # Open Settings.
    d.start_app("com.android.settings")

    # Wait for the "Network & internet" entry and tap it.
    el = d.wait_for_element(text_contains="Network", timeout=10)
    el.tap()

    # Or use the Appium-style shortcuts.
    if d.exists(text="Wi-Fi"):
        d.tap_text("Wi-Fi")

    # Type into the first EditText we find.
    edit = d.find_element(class_name="android.widget.EditText")
    if edit:
        edit.set_text("hello from android_controller")

    # Inspect the raw UI tree.
    print(d.dump_ui()[:500], "...")

    # Go home.
    d.press_key("HOME")


if __name__ == "__main__":
    main()
