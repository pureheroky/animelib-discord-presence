"""Identity, paths and defaults. Runtime settings arrive from the extension."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

APP_NAME = "AnimeLibPresence"
HOST_NAME = "com.pureheroky.animelib_presence"
EXTENSION_ID = "animelib-presence@pureheroky"

DEFAULT_CLIENT_ID = "737249403470872577"

DEFAULTS = {
    "clientId": DEFAULT_CLIENT_ID,
    "titleInHeader": True,
    "activityType": 3,
    "timestampMode": "remaining",
    "showButton": True,
    "buttonLabel": "Смотреть на AnimeLib",
    "fallbackImage": "",
    "playingImage": "",
    "pausedImage": "",
    "minUpdateIntervalMs": 4000,
    "seekToleranceSec": 5,
    "debug": False,
}


def frozen() -> bool:
    return getattr(sys, "frozen", False)


def data_dir() -> Path:
    """Where the log, the host manifest and the override file live."""
    if os.name == "nt":
        base = Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local")
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
    else:
        base = Path(os.environ.get("XDG_STATE_HOME") or Path.home() / ".local" / "state")
    path = base / APP_NAME
    path.mkdir(parents=True, exist_ok=True)
    return path


def log_path() -> Path:
    return data_dir() / "bridge.log"


def host_manifest_path() -> Path:
    return data_dir() / ("%s.json" % HOST_NAME)


def merged_settings(incoming: dict | None = None) -> dict:
    """DEFAULTS <- override.json <- whatever the extension sent."""
    cfg = dict(DEFAULTS)
    override = data_dir() / "override.json"
    if override.exists():
        try:
            cfg.update(json.loads(override.read_text(encoding="utf-8")))
        except (OSError, ValueError):
            pass
    if incoming:
        cfg.update({k: v for k, v in incoming.items() if k in cfg})
    return cfg
