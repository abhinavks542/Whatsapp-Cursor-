#!/usr/bin/env python3
"""Layered reply-or-ignore decision engine."""

from __future__ import annotations

import json
import os
import string
from datetime import datetime, timezone
from pathlib import Path

from config.constants import ONE_WORD_ACKS
from groq_client import generate_text


REPO_ROOT = Path(__file__).resolve().parent
DECISION_LOG_PATH = REPO_ROOT / "logs" / "decision_log.jsonl"
EXPECTED_LABELS = {"safe_to_auto_reply", "needs_human_money_or_serious"}


def _log_decision(
    message_text: str,
    relationship: str,
    decision: str,
    reason: str,
    raw_response: str | None = None,
) -> None:
    os.makedirs("logs", exist_ok=True)
    entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "message": message_text,
        "relationship": relationship,
        "decision": decision,
        "reason": reason,
    }
    if raw_response is not None:
        entry["raw_response"] = raw_response
    with DECISION_LOG_PATH.open("a", encoding="utf-8") as log_file:
        log_file.write(json.dumps(entry, ensure_ascii=False) + "\n")


def _finish(
    message_text: str,
    relationship: str,
    should_reply: bool,
    reason: str,
    raw_response: str | None = None,
) -> tuple[bool, str]:
    _log_decision(
        message_text,
        relationship,
        "reply" if should_reply else "ignore",
        reason,
        raw_response,
    )
    return should_reply, reason

def _classify_with_llm(text: str) -> tuple[str, str | None]:
    prompt = (
        "Classify the following incoming message as exactly one label: "
        "safe_to_auto_reply or needs_human_money_or_serious.\n"
        "Use needs_human_money_or_serious for anything involving money, payments, "
        "loans, medical, legal, serious personal matters, or genuine ambiguity.\n"
        "Return exactly one label and no other text.\n\n"
        f"Message: {text}"
    )
    try:
        raw_response = generate_text(prompt)
    except Exception as error:
        return "needs_human_money_or_serious", f"LLM error: {error}"

    if raw_response in EXPECTED_LABELS:
        return raw_response, None
    return "needs_human_money_or_serious", raw_response


def should_reply(message: dict, relationship: str) -> tuple[bool, str]:
    """Apply cheap safety gates before making one guarded intent-classification call."""
    text = message.get("text", "")
    if not isinstance(text, str):
        text = ""

    if message.get("from_me") is True:
        return _finish(text, relationship, False, "own message")
    if relationship == "group":
        return _finish(text, relationship, False, "group chat, not allowlisted")
    if relationship == "unknown":
        return _finish(text, relationship, False, "sender not in allowlist")

    message_type = message.get("message_type", "")
    if message_type in ("image", "audio", "video") and not text.strip():
        # Session 4.1 will upgrade this into a rule-based contextual acknowledgement.
        return _finish(text, relationship, False, "media-only, no text to ground a reply")
    if message.get("is_forwarded") is True:
        return _finish(text, relationship, False, "forwarded content, not a real question")

    normalized_text = text.strip().lower().translate(
        str.maketrans("", "", string.punctuation)
    )
    if normalized_text in ONE_WORD_ACKS:
        return _finish(text, relationship, False, "low-signal ack, no reply needed")

    label, raw_response = _classify_with_llm(text)
    if label == "safe_to_auto_reply":
        return _finish(text, relationship, True, "passed all gates")

    reason = "needs human review: money or serious/ambiguous intent"
    if raw_response is not None:
        reason = "intent check failed closed"
    return _finish(text, relationship, False, reason, raw_response)
