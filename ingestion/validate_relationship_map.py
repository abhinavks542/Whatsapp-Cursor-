#!/usr/bin/env python3
"""Validate that each processed conversation has a classified relationship."""

import json
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent
PAIRS_PATH = PROJECT_ROOT / "data" / "processed_pairs.jsonl"
MAP_PATH = PROJECT_ROOT / "config" / "contact_relationship_map.json"
PLACEHOLDER = "REPLACE_ME"


def load_conversation_ids() -> list[str]:
    conversation_ids = set()
    with PAIRS_PATH.open(encoding="utf-8") as pairs_file:
        for line_number, line in enumerate(pairs_file, start=1):
            if not line.strip():
                continue
            try:
                pair = json.loads(line)
            except json.JSONDecodeError as error:
                raise ValueError(f"Invalid JSON on line {line_number}: {error}") from error
            if not isinstance(pair, dict):
                raise ValueError(f"Line {line_number} must contain a JSON object")
            conversation_id = pair.get("conversation_id")
            if not isinstance(conversation_id, str) or not conversation_id:
                raise ValueError(f"Line {line_number} has no valid conversation_id")
            conversation_ids.add(conversation_id)
    return sorted(conversation_ids)


def main() -> int:
    try:
        conversation_ids = load_conversation_ids()
        with MAP_PATH.open(encoding="utf-8") as map_file:
            relationship_map = json.load(map_file)
    except (OSError, json.JSONDecodeError, ValueError) as error:
        print(f"Relationship map validation failed: {error}", file=sys.stderr)
        return 1

    if not isinstance(relationship_map, dict):
        print(
            f"Relationship map validation failed: expected a JSON object in {MAP_PATH}",
            file=sys.stderr,
        )
        return 1

    missing = [
        conversation_id
        for conversation_id in conversation_ids
        if not isinstance(relationship_map.get(conversation_id), str)
        or not relationship_map[conversation_id].strip()
        or relationship_map[conversation_id] == PLACEHOLDER
    ]
    if missing:
        print("Relationship map validation failed.", file=sys.stderr)
        print("Missing classifications:", file=sys.stderr)
        for conversation_id in missing:
            print(f"- {conversation_id}", file=sys.stderr)
        return 1

    print(
        f"Relationship map validation passed for {len(conversation_ids)} "
        "conversation_ids."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())