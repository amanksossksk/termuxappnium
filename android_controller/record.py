"""CLI for the recorder.

Usage:
    python -m android_controller.record mark.via.gp
    python -m android_controller.record mark.via.gp --output via.jsonl
    python -m android_controller.record --config myconfig.json --no-launch <pkg>
"""

from __future__ import annotations

import argparse
import sys

from .device import Device
from .recorder import Recorder


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m android_controller.record",
        description=(
            "Open a target Android app and print every tap, swipe, "
            "hardware key press, and typed text change."
        ),
    )
    parser.add_argument(
        "package",
        nargs="?",
        default=None,
        help="Target package name (e.g. mark.via.gp). "
        "Required unless --no-filter is set.",
    )
    parser.add_argument(
        "-c",
        "--config",
        default="config.json",
        help="Path to config.json (default: ./config.json)",
    )
    parser.add_argument(
        "-o",
        "--output",
        default=None,
        help="Also write events as JSON lines to this file.",
    )
    parser.add_argument(
        "--no-launch",
        action="store_true",
        help="Don't auto-launch the app; just record whatever's foreground.",
    )
    parser.add_argument(
        "--no-filter",
        action="store_true",
        help="Don't filter events by package; record everything.",
    )
    parser.add_argument(
        "--poll-text-ms",
        type=int,
        default=400,
        help="How often to poll EditText fields for text changes (default: 400 ms).",
    )
    parser.add_argument(
        "--one-to-one",
        action="store_true",
        help="Skip touchscreen calibration; assume input coords == screen coords.",
    )
    args = parser.parse_args(argv)

    package = None if args.no_filter else args.package
    if package is None and not args.no_filter:
        parser.error("package is required unless --no-filter is set")

    device = Device.from_config(args.config)
    recorder = Recorder(
        device,
        target_package=package,
        output=args.output,
        poll_text_ms=args.poll_text_ms,
        launch_app=not args.no_launch and bool(package),
        assume_one_to_one=args.one_to_one,
    )
    recorder.run()
    return 0


if __name__ == "__main__":
    sys.exit(main())
