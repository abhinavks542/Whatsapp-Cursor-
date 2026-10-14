#!/usr/bin/env python3
"""Exercise every reply-or-ignore gate in one readable dry run."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from agent.decision_engine import should_reply
from agent.generator import generate_reply
from agent.router import resolve_relationship


TEST_CASES = [
    {
        "name": "own message",
        "jid": "919812345673@s.whatsapp.net",
        "from_me": True,
        "text": "I already sent this update.",
        "message_type": "text",
        "is_forwarded": False,
    },
    {
        "name": "group chat",
        "jid": "120363000000000000@g.us",
        "from_me": False,
        "text": "What time are we meeting?",
        "message_type": "text",
        "is_forwarded": False,
    },
    {
        "name": "unknown number",
        "jid": "919899999999@s.whatsapp.net",
        "from_me": False,
        "text": "Hello, are you available?",
        "message_type": "text",
        "is_forwarded": False,
    },
    {
        "name": "media only",
        "jid": "919812345673@s.whatsapp.net",
        "from_me": False,
        "text": "",
        "message_type": "image",
        "is_forwarded": False,
    },
    {
        "name": "forwarded message",
        "jid": "919812345670@s.whatsapp.net",
        "from_me": False,
        "text": "Please share this important update.",
        "message_type": "text",
        "is_forwarded": True,
    },
    {
        "name": "one-word ack",
        "jid": "919812345673@s.whatsapp.net",
        "from_me": False,
        "text": "thanks",
        "message_type": "text",
        "is_forwarded": False,
    },
    {
        "name": "money request",
        "jid": "919812345672@s.whatsapp.net",
        "from_me": False,
        "text": "Can you send me 5000 rupees?",
        "message_type": "text",
        "is_forwarded": False,
    },
    {
        "name": "casual family",
        "jid": "919812345673@s.whatsapp.net",
        "from_me": False,
        "text": "Are you free for dinner tonight?",
        "message_type": "text",
        "is_forwarded": False,
    },
    {
        "name": "casual friend",
        "jid": "919812345670@s.whatsapp.net",
        "from_me": False,
        "text": "Want to catch a movie this weekend?",
        "message_type": "text",
        "is_forwarded": False,
    },
    {
        "name": "casual professional",
        "jid": "919812345672@s.whatsapp.net",
        "from_me": False,
        "text": "Can we sync tomorrow on the project update?",
        "message_type": "text",
        "is_forwarded": False,
    },
]


def compact(value: str, limit: int = 42) -> str:
    value = " ".join(value.split())
    return value if len(value) <= limit else f"{value[: limit - 3]}..."


def main() -> None:
    results: list[dict[str, str]] = []
    print("Running decision-engine batch test...\n")

    for test_case in TEST_CASES:
        relationship, _ = resolve_relationship(test_case["jid"])
        message = {
            key: test_case[key]
            for key in ("from_me", "text", "message_type", "is_forwarded")
        }
        should_reply_result, reason = should_reply(message, relationship)
        reply = ""
        if should_reply_result:
            try:
                reply = generate_reply(test_case["text"], relationship)
            except Exception as error:
                reply = f"[generation error: {error}]"

        results.append(
            {
                "message": test_case["text"],
                "relationship": relationship,
                "decision": "reply" if should_reply_result else "ignore",
                "reason": reason,
                "reply": reply,
            }
        )
        print(f"{test_case['name']}: {results[-1]['decision']} ({reason})")
        if reply:
            print(f"  Reply: {compact(reply, 100)}")

    print("\n" + "=" * 120)
    print("SUMMARY")
    print("=" * 120)
    print(f"{'Message':<42} {'Relationship':<14} {'Decision':<8} {'Reason':<42} Reply")
    print("-" * 120)
    for result in results:
        print(
            f"{compact(result['message']):<42} "
            f"{result['relationship']:<14} "
            f"{result['decision']:<8} "
            f"{compact(result['reason']):<42} "
            f"{compact(result['reply'], 80)}"
        )


if __name__ == "__main__":
    main()
