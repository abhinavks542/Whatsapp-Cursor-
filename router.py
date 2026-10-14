#!/usr/bin/env python3
from __future__ import annotations

"""Resolve a WhatsApp JID to its relationship and Chroma collection."""

import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent
DEFAULT_RELATIONSHIP_MAP = REPO_ROOT / "config" / "relationship_map.json"


def resolve_relationship(jid: str, map_path: str | Path = DEFAULT_RELATIONSHIP_MAP) -> tuple[str, str | None]:
    """Resolve a WhatsApp number or group JID to its relationship and collection."""
    if not jid or not isinstance(jid, str):
        return ("unknown", "history_unknown")

    normalized = jid.strip()
    if not normalized:
        return ("unknown", "history_unknown")

    if normalized.endswith("@g.us"):
        return ("group", None)

    number = normalized.split("@", 1)[0]
    if not number:
        return ("unknown", "history_unknown")

    relationship_map_path = Path(map_path)
    if not relationship_map_path.is_absolute():
        relationship_map_path = REPO_ROOT / relationship_map_path

    if relationship_map_path.exists():
        with relationship_map_path.open("r", encoding="utf-8") as map_file:
            relationship_map = json.load(map_file)
    else:
        relationship_map = {}

    if not isinstance(relationship_map, dict):
        relationship_map = {}

    relationship = relationship_map.get(number)
    if relationship is None:
        relationship = relationship_map.get("_default", "unknown") or "unknown"

    if relationship == "group":
        return ("group", None)

    collection_name = f"history_{relationship}"
    return (relationship, collection_name)
