"""Config loading for android_controller.

The config is a JSON file. Example:

    {
      "mode": "adb",                # "adb" or "root"
      "adb": {
        "binary": "adb",
        "serial": null,             # adb -s <serial> if set
        "host": null,               # adb -H <host> if set (remote adb server)
        "port": null,               # adb -P <port> if set
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
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from typing import Any

from .exceptions import ConfigError


_VALID_MODES = {"adb", "root"}


@dataclass
class AdbConfig:
    binary: str = "adb"
    serial: str | None = None
    host: str | None = None
    port: int | None = None
    default_timeout: int = 30


@dataclass
class RootConfig:
    su_binary: str = "su"
    shell_prefix: list[str] = field(default_factory=lambda: ["su", "-c"])
    default_timeout: int = 30


@dataclass
class DevicePathsConfig:
    tmp_dir: str = "/data/local/tmp"
    ui_dump_path: str = "/data/local/tmp/window_dump.xml"
    screenshot_path: str = "/data/local/tmp/screen.png"


@dataclass
class Config:
    mode: str = "adb"
    adb: AdbConfig = field(default_factory=AdbConfig)
    root: RootConfig = field(default_factory=RootConfig)
    device: DevicePathsConfig = field(default_factory=DevicePathsConfig)

    @classmethod
    def from_file(cls, path: str) -> "Config":
        if not os.path.exists(path):
            raise ConfigError(f"Config file not found: {path}")
        with open(path, "r", encoding="utf-8") as f:
            try:
                data = json.load(f)
            except json.JSONDecodeError as e:
                raise ConfigError(f"Invalid JSON in {path}: {e}") from e
        return cls.from_dict(data)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Config":
        mode = data.get("mode", "adb")
        if mode not in _VALID_MODES:
            raise ConfigError(
                f"Invalid mode: {mode!r}. Must be one of {sorted(_VALID_MODES)}"
            )

        adb_data = data.get("adb") or {}
        root_data = data.get("root") or {}
        dev_data = data.get("device") or {}

        return cls(
            mode=mode,
            adb=AdbConfig(
                binary=adb_data.get("binary", "adb"),
                serial=adb_data.get("serial"),
                host=adb_data.get("host"),
                port=adb_data.get("port"),
                default_timeout=int(adb_data.get("default_timeout", 30)),
            ),
            root=RootConfig(
                su_binary=root_data.get("su_binary", "su"),
                shell_prefix=list(root_data.get("shell_prefix", ["su", "-c"])),
                default_timeout=int(root_data.get("default_timeout", 30)),
            ),
            device=DevicePathsConfig(
                tmp_dir=dev_data.get("tmp_dir", "/data/local/tmp"),
                ui_dump_path=dev_data.get(
                    "ui_dump_path", "/data/local/tmp/window_dump.xml"
                ),
                screenshot_path=dev_data.get(
                    "screenshot_path", "/data/local/tmp/screen.png"
                ),
            ),
        )
