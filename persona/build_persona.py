import argparse
import json
import re
import sys
from collections import Counter
from pathlib import Path


MESSAGE_PATTERN = re.compile(
    r"^\[?(?P<date>\d{1,2}[/-]\d{1,2}[/-]\d{2,4}),\s+"
    r"(?P<time>\d{1,2}:\d{2}(?::\d{2})?(?:\s*[AP]M)?)\]?\s*"
    r"(?:-\s*)?(?P<sender>[^:]+):\s?(?P<message>.*)$"
)
HINGLISH_PATTERN = re.compile(
    r"\b(?:hai|kya|nahi|yaar|matlab|acha|theek|bhai|haan|toh)\b",
    re.IGNORECASE,
)
WORD_PATTERN = re.compile(r"\b[\w']+\b", re.UNICODE)
EMOJI_PATTERN = re.compile(
    r"(?:"
    r"[\U0001F1E6-\U0001F1FF]{2}"
    r"|"
    r"[\U0001F300-\U0001FAFF\u2600-\u27BF]"
    r"(?:\uFE0F|\uFE0E)?"
    r"(?:[\U0001F3FB-\U0001F3FF])?"
    r"(?:\u200D[\U0001F300-\U0001FAFF\u2600-\u27BF]"
    r"(?:\uFE0F|\uFE0E)?(?:[\U0001F3FB-\U0001F3FF])?)*"
    r")"
)


def parse_args():
    parser = argparse.ArgumentParser(
        description="Summarize style signals from your WhatsApp messages."
    )
    parser.add_argument("--file", required=True, type=Path, help="WhatsApp .txt export")
    parser.add_argument(
        "--name", required=True, help="Exact sender name as shown in the export"
    )
    return parser.parse_args()


def collect_messages(file_path, sender_name):
    messages = []
    with file_path.open(encoding="utf-8", errors="ignore") as export_file:
        for line in export_file:
            match = MESSAGE_PATTERN.match(line.rstrip("\r\n"))
            if match and match.group("sender").strip() == sender_name:
                messages.append(match.group("message"))
    return messages


def build_stats(messages):
    hinglish_count = sum(bool(HINGLISH_PATTERN.search(message)) for message in messages)
    word_counts = [len(WORD_PATTERN.findall(message)) for message in messages]
    emoji_counts = Counter(
        emoji for message in messages for emoji in EMOJI_PATTERN.findall(message)
    )

    return {
        "total_messages": len(messages),
        "hinglish_messages": hinglish_count,
        "hinglish_ratio_percent": round(hinglish_count / len(messages) * 100, 2),
        "average_message_length_words": round(sum(word_counts) / len(messages), 2),
        "top_emojis": [
            {"emoji": emoji, "frequency": count}
            for emoji, count in emoji_counts.most_common(15)
        ],
    }


def print_summary(stats):
    print("Persona style signals")
    print(f"Total messages: {stats['total_messages']}")
    print(
        f"Hinglish messages: {stats['hinglish_messages']} "
        f"({stats['hinglish_ratio_percent']:.2f}%)"
    )
    print(
        "Average message length: "
        f"{stats['average_message_length_words']:.2f} words"
    )
    print("Top emojis:")
    if stats["top_emojis"]:
        for item in stats["top_emojis"]:
            print(f"  {item['emoji']}: {item['frequency']}")
    else:
        print("  None found")


def main():
    args = parse_args()
    messages = collect_messages(args.file, args.name)
    if not messages:
        print(
            f"Warning: no messages found for sender {args.name!r}. "
            "Double-check the exact sender name in the raw export.",
            file=sys.stderr,
        )
        return 1

    stats = build_stats(messages)
    print_summary(stats)

    output_path = Path(__file__).with_name("style_signals.json")
    output_path.write_text(
        json.dumps(stats, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(f"\nJSON written to {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())