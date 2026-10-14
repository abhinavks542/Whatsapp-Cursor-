import argparse
import json
import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent
RAW_EXPORT_DIR = PROJECT_ROOT / "data" / "raw_export"
OUTPUT_PATH = PROJECT_ROOT / "data" / "processed_pairs.jsonl"
PER_CONVERSATION_OUTPUT_DIR = PROJECT_ROOT / "data" / "processed_pairs"
MAX_PAIRS_PER_CONVERSATION = 500

SYSTEM_OR_MEDIA_SUBSTRINGS = (
    "Messages and calls are end-to-end encrypted",
    "<Media omitted>",
    "image omitted",
    "video omitted",
    "audio omitted",
    "sticker omitted",
    "GIF omitted",
    "document omitted",
    "This message was deleted",
    "You deleted this message",
    "Missed voice call",
    "Missed video call",
    "Voice call",
    "Contact card omitted",
    "<This message was edited>",
    "created group",
    "changed the subject",
    "added you",
    "changed this group's icon",
)

ACKNOWLEDGEMENTS = {
    "ok",
    "okay",
    "k",
    "kk",
    "haan",
    "hmm",
    "thanks",
    "thank you",
    "cool",
    "nice",
}

# Supports WhatsApp's usual bracketed export and the equivalent unbracketed form.
MESSAGE_START = re.compile(
    r"^(?:\[(?P<bracket_date>[^,\]]+),\s*(?P<bracket_time>[^\]]+)\]|"
    r"(?P<plain_date>[^,]+),\s*(?P<plain_time>\S+(?:\s+[AP]M)?))"
    r"\s*(?:-|)\s*(?P<sender>[^:]+):\s?(?P<message>.*)$",
    re.IGNORECASE,
)


@dataclass
class Message:
    sender: str
    text: str
    timestamp: str


@dataclass
class Turn:
    sender: str
    text: str
    timestamp: str


def parse_args():
    parser = argparse.ArgumentParser(
        description="Convert WhatsApp text exports into consecutive-turn reply pairs."
    )
    parser.add_argument(
        "--name", required=True, help="Exact sender name as shown in the exports"
    )
    return parser.parse_args()


def conversation_id_from_path(file_path):
    name = file_path.stem
    prefix = "WhatsApp Chat with "
    if name.lower().startswith(prefix.lower()):
        name = name[len(prefix):]
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


def parse_messages(file_path):
    messages = []
    current = None

    def save_current():
        if current is not None:
            messages.append(current)

    with file_path.open(encoding="utf-8-sig", errors="replace") as export_file:
        for raw_line in export_file:
            line = raw_line.rstrip("\r\n")
            match = MESSAGE_START.match(line)
            if match:
                save_current()
                date = match.group("bracket_date") or match.group("plain_date")
                time = match.group("bracket_time") or match.group("plain_time")
                current = Message(
                    sender=match.group("sender").strip(),
                    text=match.group("message"),
                    timestamp=f"{date}, {time}",
                )
            elif current is not None:
                current.text += f"\n{line}"

    save_current()
    return messages


def is_system_or_media(message):
    lowered = message.casefold()
    return any(
        substring.casefold() in lowered
        for substring in SYSTEM_OR_MEDIA_SUBSTRINGS
    )


def is_standalone_acknowledgement(message):
    normalized = message.strip().casefold()
    while normalized and unicodedata.category(normalized[-1]).startswith("P"):
        normalized = normalized[:-1].rstrip()
    return normalized in ACKNOWLEDGEMENTS


def build_turns(messages):
    turns = []
    for message in messages:
        text = message.text.strip()
        if (
            not text
            or is_system_or_media(text)
            or is_standalone_acknowledgement(text)
        ):
            continue

        if turns and turns[-1].sender == message.sender:
            turns[-1].text += f"\n{text}"
        else:
            turns.append(
                Turn(
                    sender=message.sender,
                    text=text,
                    timestamp=message.timestamp,
                )
            )
    return turns


def make_pairs(conversation_id, turns, my_name):
    pairs = []
    seen_pairs = set()
    for their_turn, my_turn in zip(turns, turns[1:]):
        if their_turn.sender != my_name and my_turn.sender == my_name:
            pair = {
                "conversation_id": conversation_id,
                "their_message": their_turn.text,
                "my_reply": my_turn.text,
                "timestamp": my_turn.timestamp,
            }
            pair_key = tuple(pair.values())
            if pair_key not in seen_pairs:
                seen_pairs.add(pair_key)
                pairs.append(pair)
    return pairs[-MAX_PAIRS_PER_CONVERSATION:]


def write_jsonl(output_path, pairs):
    with output_path.open("w", encoding="utf-8") as output_file:
        for pair in pairs:
            output_file.write(json.dumps(pair, ensure_ascii=False) + "\n")


def main():
    args = parse_args()
    export_files = sorted(RAW_EXPORT_DIR.glob("*.txt"))
    all_pairs = []

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    PER_CONVERSATION_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    for file_path in export_files:
        conversation_id = conversation_id_from_path(file_path)
        messages = parse_messages(file_path)
        turns = build_turns(messages)
        pairs = make_pairs(conversation_id, turns, args.name)
        all_pairs.extend(pairs)
        write_jsonl(PER_CONVERSATION_OUTPUT_DIR / f"{conversation_id}.jsonl", pairs)

        print(f"{file_path.name}: {len(pairs)} pairs kept")
        if not pairs:
            print(
                f'Warning: conversation_id "{conversation_id}" produced zero pairs; '
                "this may indicate a --name mismatch."
            )

    write_jsonl(OUTPUT_PATH, all_pairs)
    print(f"Wrote {len(all_pairs)} pairs to {OUTPUT_PATH}")


if __name__ == "__main__":
    main()