# android_controller

A small, dependency-free Python library that gives you an Appium-style
device API on top of either:

- **`adb`** — running from a host machine that has `adb` installed, or
- **`su` (Termux root)** — running directly on a rooted Android device.

You pick the mode by editing `config.json`. The rest of your code stays
the same.

```python
from android_controller import Device

d = Device.from_config("config.json")

d.tap(500, 1000)
d.swipe(500, 1500, 500, 500, duration_ms=300)
d.type_text("hello world")
d.press_key("BACK")
d.screenshot("out.png")

el = d.wait_for_element(text="Login", timeout=10)
el.tap()
```

## Install

No external Python dependencies. Just drop the folder somewhere on your
PYTHONPATH (or `pip install -e .` if you add a `pyproject.toml`).

Requirements per mode:

| Mode | Where you run the script | Needs |
|------|--------------------------|-------|
| `adb`  | Host machine (Linux / macOS / Windows) | `adb` in `PATH`, USB debugging enabled on the phone |
| `root` | On the phone (Termux) | A rooted device + `su` available to Termux |

For Termux root mode, install Termux and grant it root via your root
manager (e.g. Magisk → Superuser → allow Termux):

```bash
pkg install python
pip install --upgrade pip
# drop this project into your $HOME/android_controller
cd ~/android_controller
python examples/basic_usage.py
```

## Config

`config.json`:

```json
{
  "mode": "adb",
  "adb": {
    "binary": "adb",
    "serial": null,
    "host": null,
    "port": null,
    "default_timeout": 30
  },
  "root": {
    "su_binary": "su",
    "shell_prefix": ["su", "-c"],
    "default_timeout": 30
  },
  "device": {
    "tmp_dir": "/data/local/tmp",
    "ui_dump_path": "/data/local/tmp/window_dump.xml",
    "screenshot_path": "/data/local/tmp/screen.png"
  }
}
```

- `mode`: `"adb"` or `"root"`.
- `adb.serial`: pass `null` for the default device, otherwise the
  `adb devices` serial.
- `adb.host` / `adb.port`: only set these if you talk to a remote
  `adb` server (`-H`/`-P`).
- `root.shell_prefix`: leave as `["su", "-c"]` for Termux. Some custom
  root setups want `["su", "0", "-c"]` or `["sudo"]` — change here.
- `device.tmp_dir`: world-readable on-device staging directory. Used for
  things like installing APKs over `su` (see below).

## Feature matrix

All of the below work in either mode, transparently.

| Category | Methods |
|----------|---------|
| Raw shell | `shell(cmd)`, `run(cmd)` |
| Files | `push(local, remote)`, `pull(remote, local)` |
| Touch | `tap`, `double_tap`, `long_press`, `swipe`, `drag` |
| Scroll | `scroll_up`, `scroll_down`, `scroll_left`, `scroll_right` |
| Keyboard | `press_key`, `long_press_key`, `type_text`, `clear_text` |
| Screen | `screen_size`, `screen_density`, `orientation`, `set_orientation`, `wake`, `sleep_screen`, `is_screen_on`, `unlock`, `swipe_unlock` |
| Screenshot | `screenshot(path)`, `screenshot_bytes()` |
| UI tree | `dump_ui()` (alias `source()`), `find_element`, `find_elements`, `find_element_or_raise`, `wait_for_element`, `wait_until_gone`, `exists` |
| Tap helpers | `tap_text`, `tap_id`, `tap_desc` |
| Apps | `list_packages`, `is_installed`, `install_apk`, `uninstall`, `start_app`, `stop_app`, `clear_app_data`, `current_app`, `open_url` |
| Device info | `device_info`, `get_prop`, `set_prop`, `battery`, `ip_addresses`, `get_setting`, `put_setting` |
| Network | `wifi(on)`, `data(on)`, `airplane_mode(on)` |
| Logging | `logcat(lines, filter_tag=)`, `clear_logcat()` |

### Finding UI elements

`find_element(**filters)` parses the output of `uiautomator dump`.
Filter keys are translated to uiautomator XML attributes:

| Python kwarg | Matches XML attribute |
|--------------|----------------------|
| `text` | `text` (exact) |
| `text_contains` | `text` (substring) |
| `text_matches` | `text` (regex) |
| `content_desc` / `desc` | `content-desc` |
| `desc_contains` | `content-desc` (substring) |
| `resource_id` / `id` | `resource-id` |
| `resource_id_contains` | `resource-id` (substring) |
| `class_name` / `cls` | `class` |
| `package` | `package` |
| `clickable`, `enabled`, `checked`, `focused`, `scrollable`, `selected` | the matching boolean attribute |

Anything else is matched as an exact attribute equality, so you can
pass raw uiautomator attribute names too.

```python
btn = d.find_element(resource_id="com.example:id/login", clickable=True)
btn.tap()

# Substring + regex filters
d.find_elements(text_contains="Settings")
d.find_elements(content_desc_matches=r"^Notif.*")
```

### Typing text

`type_text` uses `input text` under the hood. Spaces and shell
metacharacters are escaped. For full Unicode support you'll want to
install an IME (e.g. Appium UnicodeIME) like Appium does — that's out
of scope here but easy to add.

### Installing APKs from Termux

When `mode = "root"`, `install_apk(path)` stages the APK to
`device.tmp_dir` (default `/data/local/tmp`) before calling
`pm install`, because `pm` runs as `system` and cannot read files under
`/data/data/com.termux/...`. You don't need to do anything special — it
just works:

```python
d.install_apk("/sdcard/Download/my-app.apk")
```

## Mapping from your original snippet

Both of your `run()` helpers map directly:

```python
# Your "adb" version:
def run(cmd):
    result = subprocess.run(f"adb shell {cmd}", shell=True, ...)
    return result.stdout.strip()

# Your "root" version:
def run(cmd):
    if cmd.startswith("adb shell"):
        cmd = cmd.replace("adb shell ", "")
    result = subprocess.run(['su', '-c', cmd], ...)
    return result.stdout.strip()
```

Equivalent here:

```python
d = Device.from_config("config.json")   # mode in config.json picks one
print(d.run("input tap 500 500"))       # same return value (stdout)
```

Both also tolerate the `adb shell` prefix being present or absent.

## Recording user interactions

Open a target app and stream every tap, swipe, hardware key, and typed-text
change to stdout (and optionally a `.jsonl` file):

```
python -m android_controller.record mark.via.gp
python -m android_controller.record mark.via.gp -o via.jsonl
```

Sample output:

```
# Launching mark.via.gp ...
# Screen: 1080x2400
# Touch calibration: {'/dev/input/event2': (1080, 2400)}
# Recording... (Ctrl+C to stop)
[19:12:03.412] TAP   [540, 1820]  id=mark.via.gp:id/url_bar  text=''
[19:12:05.103] TEXT  text='example.com'  id=mark.via.gp:id/url_bar
[19:12:06.812] KEY   ENTER
[19:12:09.991] SWIPE [540, 2100] -> [540, 600] (310ms)
```

How it works:

* `getevent -lt` is streamed over your shell (ADB or root) and parsed in real
  time → produces `TAP` / `SWIPE` / hardware-`KEY` events.
* After every tap we run `uiautomator dump` and look up the deepest element
  whose bounds contain the tap point → fills in `resource_id` / `text` /
  `content-desc`.
* For typed text we poll the UI hierarchy and diff `EditText.text` values
  per `resource-id`, so the *resulting* text is logged regardless of which
  IME or autocomplete the user used.
* Everything is filtered by the foreground package, so unrelated taps in the
  status bar / launcher / keyboard are ignored.

Programmatic API:

```python
from android_controller import Device, Recorder

d = Device.from_config("config.json")
Recorder(d, target_package="mark.via.gp", output="via.jsonl").run()
```

CLI options: `--no-launch`, `--no-filter`, `--poll-text-ms`, `--one-to-one`,
`--config`.

## Scrolling inside a specific view

Full-screen `scroll_down()` / `scroll_up()` swipes from screen-wide
coordinates, which can miss scrollable regions inside dialogs (e.g. the
date-picker year list). Use these instead when the target lives inside a
container:

```python
# Swipe inside a specific element/region.
# `direction` is the direction *content* should scroll:
#   "down"  -> reveals items above (finger swipes top->bottom)
#   "up"    -> reveals items below (finger swipes bottom->top)
d.swipe_in(year_list, direction="down")           # year_list is a UIElement
d.swipe_in((100, 500, 1000, 1500), direction="up")  # raw (l,t,r,b)
year_list.swipe(direction="down")                  # convenience on UIElement
```

`d.scroll_to(...)` ties it all together: it autodetects the scrollable
container on screen (the largest `scrollable=true` / `ScrollView` /
`ListView` / `RecyclerView`) and keeps swiping until your target element
appears:

```python
# Open the year list, scroll to 2004, tap it.
d.tap_id("android:id/date_picker_header_year")
d.scroll_to(text="2004", direction="down").tap()

# direction="auto" tries down first, then up.
d.scroll_to(resource_id="...:id/foo", direction="auto", max_swipes=15)

# Or scroll inside a specific container:
list_view = d.find_element(class_name="android.widget.ListView")
list_view.scroll_to(text="2004", direction="down").tap()
```

`scroll_to` returns the matching `UIElement` on success, or `None` after
`max_swipes` (default 25).

## Handling random pop-up screens (ScreenRouter)

App onboarding throws notifications/location/cookies/welcome dialogs at you
in unpredictable order. `ScreenRouter` lets you declare each case once and
run a loop that dispatches whichever screen shows up:

```python
from android_controller import Device, ScreenRouter

d = Device.from_config("config.json")
d.start_app("mark.via.gp")

router = ScreenRouter(d)
router.when(text_contains="notifications").tap_label("Skip", "Not now")
router.when(text_contains="location").tap_label("Don't allow", "Deny")
router.when(text_contains="cookies").tap_label("Accept all", "Agree")
router.when(text="Welcome").tap_label("Get started", "Continue")
router.when(text_contains="update").tap_label("Later", "Not now")
router.when(text="I agree", clickable=True).tap_match()

# Run until the main screen shows up (or 120s timeout).
router.run(
    stop_when={"resource_id": "mark.via.gp:id/url_bar"},
    timeout=120,
)
```

Available rule actions: `.tap_label(*labels)` (taps the first clickable
text label), `.tap_match()` (taps the matched element itself),
`.tap_id(resource_id)`, `.tap_desc(*descs)`, `.press_key(key)`, and
`.do(callable)` for arbitrary logic — the callable receives
`(device, matched_element)`.

Tips:

- Rules fire in registration order — register the most specific first.
- Always add `clickable=True` when filtering by button text (Android often
  duplicates the label in surrounding paragraph TextViews).
- `stop_when` can be a filter dict (as above) or a callable
  `(device) -> bool`.
- `verbose=True` (default) prints which rule matched each iteration.

## Inspecting the current UI

Quick way to dump every `resource-id` / `text` / `class` for the app
currently on screen — useful when writing automation against an unfamiliar
app:

```
python -m android_controller.ids mark.via.gp
python -m android_controller.ids mark.via.gp --clickable-only
python -m android_controller.ids mark.via.gp --text
python -m android_controller.ids mark.via.gp --ids-only        # one id per line
python -m android_controller.ids mark.via.gp --json            # one JSON obj per element
python -m android_controller.ids mark.via.gp --watch 0.5       # live-refresh
python -m android_controller.ids --all                         # ignore package filter
```

Sample:

```
RESOURCE_ID                          TEXT          DESC          CLASS                       CLICKABLE  BOUNDS
--------------------------------------------------------------------------------------------------------------
mark.via.gp:id/url_bar                                          android.widget.EditText     YES        (24, 144, 1056, 240)
mark.via.gp:id/btn_back               Back          Go back     android.widget.ImageButton  YES        (0, 144, 144, 240)
mark.via.gp:id/tab_list               Tabs                      android.widget.ImageButton  YES        (936, 144, 1056, 240)
...
```

## License

MIT (or whatever you prefer — drop a LICENSE file in).
