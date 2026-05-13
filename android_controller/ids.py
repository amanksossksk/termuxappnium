"""CLI: dump resource_ids / text / classes currently on screen for an app.

Usage:
    python -m android_controller.ids mark.via.gp
    python -m android_controller.ids mark.via.gp --clickable-only
    python -m android_controller.ids mark.via.gp --watch
    python -m android_controller.ids mark.via.gp --watch 0.5 --clickable-only
    python -m android_controller.ids --all                 # don't filter by package
    python -m android_controller.ids mark.via.gp --json   # JSONL output
    python -m android_controller.ids mark.via.gp --text   # only nodes with text
"""

from __future__ import annotations

import argparse
import json
import sys
import time

from .device import Device


def _print_table(elements, header: bool = True) -> None:
    if header:
        print(f"{'RESOURCE_ID':<48}  {'TEXT':<32}  {'DESC':<24}  {'CLASS':<32}  CLICKABLE  BOUNDS")
        print("-" * 160)
    for el in elements:
        rid = el.resource_id or ""
        text = (el.text or "").replace("\n", "\\n")[:30]
        desc = (el.content_desc or "")[:22]
        cls = el.class_name or ""
        clk = "YES" if el.is_("clickable") else ""
        bounds = el.bounds or ""
        print(
            f"{rid:<48}  {text:<32}  {desc:<24}  {cls:<32}  {clk:<9}  {bounds}"
        )


def _filter(elements, *, clickable_only: bool, text_only: bool):
    out = []
    for el in elements:
        if clickable_only and not el.is_("clickable"):
            continue
        if text_only and not (el.text or el.content_desc):
            continue
        if not (el.resource_id or el.text or el.content_desc):
            continue
        out.append(el)
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m android_controller.ids",
        description=(
            "Dump the resource-ids / text / classes of every UI element "
            "currently visible for a target Android package."
        ),
    )
    parser.add_argument(
        "package",
        nargs="?",
        default=None,
        help="Target package name (e.g. mark.via.gp). Omit with --all to dump everything.",
    )
    parser.add_argument(
        "-c", "--config", default="config.json",
        help="Path to config.json (default: ./config.json)",
    )
    parser.add_argument(
        "--clickable-only", action="store_true",
        help="Only show elements with clickable=true.",
    )
    parser.add_argument(
        "--text", action="store_true",
        help="Only show elements that have non-empty text or content-desc.",
    )
    parser.add_argument(
        "--all", action="store_true",
        help="Don't filter by package.",
    )
    parser.add_argument(
        "--ids-only", action="store_true",
        help="Print only unique resource-ids, one per line (machine-readable).",
    )
    parser.add_argument(
        "--json", action="store_true",
        help="Print one JSON object per element instead of the table.",
    )
    parser.add_argument(
        "--watch", nargs="?", const=1.0, type=float, default=None,
        metavar="SECONDS",
        help="Refresh repeatedly. Defaults to every 1.0s when used without a value.",
    )
    args = parser.parse_args(argv)

    if not args.all and not args.package:
        parser.error("package is required unless --all is set")

    device = Device.from_config(args.config)

    def one_shot() -> None:
        if args.all:
            elements = device.find_elements()
        else:
            elements = device.find_elements(package=args.package)
        elements = _filter(
            elements,
            clickable_only=args.clickable_only,
            text_only=args.text,
        )

        if args.ids_only:
            seen = set()
            for el in elements:
                if el.resource_id and el.resource_id not in seen:
                    seen.add(el.resource_id)
                    print(el.resource_id)
            return

        if args.json:
            for el in elements:
                obj = {
                    "resource_id": el.resource_id,
                    "text": el.text,
                    "content_desc": el.content_desc,
                    "class": el.class_name,
                    "package": el.package,
                    "clickable": el.is_("clickable"),
                    "enabled": el.is_("enabled"),
                    "bounds": list(el.bounds) if el.bounds else None,
                }
                print(json.dumps(obj, ensure_ascii=False))
            return

        _print_table(elements)
        if args.all:
            scope = "all packages"
        else:
            scope = args.package
        print(f"\n# {len(elements)} elements in {scope}", file=sys.stderr)

    if args.watch is None:
        one_shot()
        return 0

    interval = max(0.1, args.watch)
    try:
        while True:
            sys.stdout.write("\x1b[2J\x1b[H")  # clear + home
            sys.stdout.flush()
            print(f"# Refreshing every {interval}s. Ctrl+C to stop.\n", file=sys.stderr)
            one_shot()
            time.sleep(interval)
    except KeyboardInterrupt:
        return 0


if __name__ == "__main__":
    sys.exit(main())
