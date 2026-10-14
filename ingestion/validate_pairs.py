#!/usr/bin/env python3
"""Validate generated WhatsApp conversation/reply pairs."""

import argparse
import collections
import json
import random
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_INPUT_PATH = PROJECT_ROOT / "data" / "processed_pairs.jsonl"
SAMPLE_SIZE = 5
NOISE_MARKERS = ("omitted", "<media", "deleted")
WARNING = "\033[91m"
RESET = "\033[0m"


def build_parser():
    parser = argparse.ArgumentParser(
        description="Validate generated WhatsApp conversation/reply pairs."
    )
    parser.add_argument(
        "--input",
        type=Path,
        default=DEFAULT_INPUT_PATH,
        help="JSONL file to validate (default: data/processed_pairs.jsonl)",
    )
    parser.add_argument(
        "--no-samples",
        action="store_true",
        help="Do not print randomly selected pairs",
    )
    return parser


def warn(message: str) -> None:
    print(f"{WARNING}WARNING: {message}{RESET}")


def word_count(text: str) -> int:
    return len(text.split())


def normalized_words(text: str) -> set[str]:
    words = set()
    for word in text.casefold().split():
        cleaned = "".join(character for character in word if character.isalnum())
        if cleaned:
            words.add(cleaned)
    return words


def is_near_identical(first: str, second: str) -> bool:
    """Detect exact or almost identical text without third-party dependencies."""
    first_words = normalized_words(first)
    second_words = normalized_words(second)
    if not first_words or not second_words:
        return False
    overlap = len(first_words & second_words) / len(first_words | second_words)
    return overlap >= 0.9 and min(len(first_words), len(second_words)) >= 2


def load_pairs(input_path: Path) -> tuple[list[dict], int]:
    pairs = []
    malformed_count = 0
    if not input_path.is_file():
        raise SystemExit(f"Input file not found: {input_path}")

    with input_path.open(encoding="utf-8") as input_file:
        for line_number, line in enumerate(input_file, start=1):
            if not line.strip():
                continue
            try:
                pair = json.loads(line)
            except json.JSONDecodeError as error:
                malformed_count += 1
                warn(f"Line {line_number} is not valid JSON: {error}")
                continue

            if not isinstance(pair, dict):
                malformed_count += 1
                warn(f"Line {line_number} is valid JSON but is not an object")
                continue
            pairs.append(pair)

    return pairs, malformed_count


def print_samples(pairs: list[dict]) -> None:
    sample_count = min(SAMPLE_SIZE, len(pairs))
    print(f"\nRandom samples ({sample_count}):")
    for sample_number, pair in enumerate(random.sample(pairs, sample_count), 1):
        print(
            f"\n--- Sample {sample_number} "
            f"[{pair.get('conversation_id', 'unknown')}] ---"
        )
        print(f"Their message:\n{pair.get('their_message', '')}")
        print(f"\nMy reply:\n{pair.get('my_reply', '')}")
        print(f"\nTimestamp: {pair.get('timestamp', 'unknown')}")


def main() -> None:
    args = build_parser().parse_args()
    pairs, malformed_count = load_pairs(args.input)
    counts = collections.Counter(
        pair.get("conversation_id", "<missing>") for pair in pairs
    )
    issues = malformed_count

    print(f"Pair validation report: {args.input}")
    print(f"Total pairs: {len(pairs)}")
    print("\nPairs by conversation:")
    if counts:
        for conversation_id, count in sorted(counts.items()):
            print(f"- {conversation_id}: {count}")
    else:
        warn("No conversation IDs found")
        issues += 1

    for conversation_id, count in counts.items():
        if count == 0:
            warn(f"conversation_id '{conversation_id}' has 0 pairs")
            issues += 1

    noise_flags = 0
    long_flags = 0
    duplicate_flags = 0
    for pair_number, pair in enumerate(pairs, start=1):
        text_fields = {}
        for field_name in ("their_message", "my_reply"):
            value = pair.get(field_name, "")
            if not isinstance(value, str):
                warn(f"Pair {pair_number}: {field_name} is not text")
                noise_flags += 1
                value = ""
            text_fields[field_name] = value

            lowered = value.casefold()
            if not value.strip():
                warn(f"Pair {pair_number}: empty {field_name}")
                noise_flags += 1
            elif any(marker in lowered for marker in NOISE_MARKERS):
                warn(f"Pair {pair_number}: noise marker leaked into {field_name}")
                noise_flags += 1

        their_message = text_fields["their_message"]
        my_reply = text_fields["my_reply"]
        reply_word_count = word_count(my_reply)
        if reply_word_count > 100:
            warn(f"Pair {pair_number}: my_reply is {reply_word_count} words")
            long_flags += 1

        if their_message.casefold() == my_reply.casefold() or is_near_identical(
            their_message, my_reply
        ):
            warn(
                f"Pair {pair_number}: their_message and my_reply are "
                "identical or near-identical"
            )
            duplicate_flags += 1

    issues += noise_flags + long_flags + duplicate_flags
    if not args.no_samples:
        print_samples(pairs)

    print("\nFlag totals:")
    print(f"- Malformed input lines: {malformed_count}")
    print(f"- Noise/empty: {noise_flags}")
    print(f"- Suspiciously long replies: {long_flags}")
    print(f"- Identical/near-identical pairs: {duplicate_flags}")
    status = "Looks good" if issues == 0 else f"{issues} issues found; review above"
    print(f"\n{status}")


if __name__ == "__main__":
    main()