#!/usr/bin/env python3
"""Load runtime settings and enforce the relationship-derived allowlist."""

from __future__ import annotations

import json
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent
SETTINGS_PATH = REPO_ROOT / "config" / "settings.json"
RELATIONSHIP_MAP_PATH = REPO_ROOT / "config" / "relationship_map.json"
KILL_SWITCH_PATH = REPO_ROOT / "kill_switch.flag"
DEFAULT_SETTINGS = {
    "dry_run": True,
    "min_delay_seconds": 3,
    "max_delay_seconds": 12,
}


def load_settings() -> dict:
    """Load settings, falling back safely when the settings file is invalid."""
    target_path = SETTINGS_PATH if SETTINGS_PATH.exists() else (REPO_ROOT / "settings.json")
    try:
        with target_path.open("r", encoding="utf-8") as settings_file:
            settings = json.load(settings_file)
    except (OSError, json.JSONDecodeError, TypeError):
        return DEFAULT_SETTINGS.copy()

    if not isinstance(settings, dict):
        return DEFAULT_SETTINGS.copy()
    merged = DEFAULT_SETTINGS.copy()
    merged.update(settings)
    return merged


def save_settings(new_settings: dict) -> dict:
    """Save settings to config/settings.json and REPO_ROOT/settings.json."""
    current = load_settings()
    current.update(new_settings)
    SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
    with SETTINGS_PATH.open("w", encoding="utf-8") as handle:
        json.dump(current, handle, indent=2)
    try:
        with (REPO_ROOT / "settings.json").open("w", encoding="utf-8") as handle:
            json.dump(current, handle, indent=2)
    except OSError:
        pass
    return current


def is_dry_run() -> bool:
    """Return whether outgoing replies should remain in dry-run mode."""
    return bool(load_settings().get("dry_run", True))


def is_kill_switch_active() -> bool:
    """Return whether the repository kill-switch flag exists."""
    return KILL_SWITCH_PATH.exists()


def get_allowlist() -> set[str]:
    """Return relationship-map keys that resolve to an allowed relationship."""
    try:
        with RELATIONSHIP_MAP_PATH.open("r", encoding="utf-8") as map_file:
            relationship_map = json.load(map_file)
    except (OSError, json.JSONDecodeError, TypeError):
        return set()

    if not isinstance(relationship_map, dict):
        return set()

    return {
        key
        for key, relationship in relationship_map.items()
        if key != "_default" and relationship != "unknown"
    }


def enforce_allowlist(jid: str) -> bool:
    """Return whether a JID's number is present in the derived allowlist."""
    if not isinstance(jid, str):
        return False

    number = jid.strip().split("@", 1)[0]
    return bool(number) and number in get_allowlist()
