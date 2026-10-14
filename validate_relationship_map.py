#!/usr/bin/env python3
"""Validate relationship-map entries for WhatsApp-style number keys."""

import json
import re
import sys
from pathlib import Path


MAP_PATH = Path("config/relationship_map.json")
VALID_RELATIONSHIPS = {"family", "friend", "professional", "unknown"}


def load_map() -> dict:
    with MAP_PATH.open("r", encoding="utf-8") as map_file:
        data = json.load(map_file)
    if not isinstance(data, dict):
        raise ValueError(f"{MAP_PATH} must contain a JSON object at the top level")
    return data


def key_looks_like_contact_copy_paste(key: str) -> bool:
    return bool(re.search(r"[+\s\-A-Za-z]", key))


def digit_length_looks_implausible(key: str) -> bool:
    digits = re.sub(r"\D", "", key)
    return len(digits) < 8 or len(digits) > 15


def main() -> int:
    issues: list[str] = []

    try:
        relationship_map = load_map()
    except (FileNotFoundError, json.JSONDecodeError, ValueError) as exc:
        print(f"FAIL: unable to load {MAP_PATH}: {exc}", file=sys.stderr)
        return 1

    default_value = relationship_map.get("_default")
    if "_default" not in relationship_map:
        issues.append('Missing required key "_default"')
    elif default_value not in VALID_RELATIONSHIPS:
        issues.append(
            f'Invalid "_default" value: {default_value!r}; expected one of {sorted(VALID_RELATIONSHIPS)}'
        )

    for key, value in sorted(relationship_map.items()):
        if key == "_default":
            continue

        if key_looks_like_contact_copy_paste(key):
            issues.append(
                f'Key {key!r} looks like a copy-paste/contact-format mistake: contains +, spaces, dashes, or letters'
            )

        if digit_length_looks_implausible(key):
            digits_only = re.sub(r"\D", "", key)
            issues.append(
                f"Key {key!r} has implausible digit length ({len(digits_only)} digits)"
            )

        if value is None:
            issues.append(f'Key {key!r} has a null value; expected a relationship string')
        elif not isinstance(value, str):
            issues.append(f'Key {key!r} has a non-string value: {value!r}')

    if issues:
        print("FAIL: relationship map validation issues found:")
        for issue in issues:
            print(f"- {issue}")
        return 1

    print("PASS: relationship map looks valid.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
