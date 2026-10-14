#!/usr/bin/env python3
"""Create or extend the hand-classified conversation relationship map."""

import json
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent
PAIRS_PATH = PROJECT_ROOT / "data" / "processed_pairs.jsonl"
MAP_PATH = PROJECT_ROOT / "config" / "contact_relationship_map.json"
LEGACY_MAP_PATH = PROJECT_ROOT / "contact_relationship_map.json"
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


def load_existing_map() -> dict[str, str]:
    # Seed the new config path from the existing hand-classified root map once.
    source_path = MAP_PATH if MAP_PATH.is_file() else LEGACY_MAP_PATH
    if not source_path.is_file():
        return {}
    with source_path.open(encoding="utf-8") as map_file:
        relationship_map = json.load(map_file)
    if not isinstance(relationship_map, dict):
        raise ValueError(f"Expected {source_path} to contain a JSON object")
    return relationship_map


def main() -> int:
    try:
        conversation_ids = load_conversation_ids()
        relationship_map = load_existing_map()
    except (OSError, json.JSONDecodeError, ValueError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1

    new_ids = [key for key in conversation_ids if key not in relationship_map]
    for conversation_id in new_ids:
        relationship_map[conversation_id] = PLACEHOLDER
    relationship_map.setdefault("_default", "unknown")

    sorted_map = {key: relationship_map[key] for key in sorted(relationship_map)}
    MAP_PATH.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = MAP_PATH.with_suffix(MAP_PATH.suffix + ".tmp")
    temporary_path.write_text(
        json.dumps(sorted_map, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    temporary_path.replace(MAP_PATH)

    placeholders = [key for key, value in sorted_map.items() if value == PLACEHOLDER]
    print(f"Total conversation_ids: {len(conversation_ids)}")
    print(f"New conversation_ids needing attention: {len(new_ids)}")
    print("conversation_ids still set to REPLACE_ME:")
    if placeholders:
        for conversation_id in placeholders:
            print(f"- {conversation_id}")
    else:
        print("- none")
    print(f"Map written to {MAP_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())