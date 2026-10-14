#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from flask import Flask, jsonify, request

REPO_ROOT = Path(__file__).resolve().parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from agent.decision_engine import should_reply
from agent.generator import generate_reply
from agent.router import resolve_relationship
from ingestion.retrieval import retrieve_similar

app = Flask(__name__)
LOGS_DIR = REPO_ROOT / "logs"
CONSOLE_FEED_PATH = LOGS_DIR / "console_feed.jsonl"


def _ensure_log_dir() -> None:
    LOGS_DIR.mkdir(parents=True, exist_ok=True)


@app.post("/process")
def process_message():
    payload = request.get_json(silent=True) or {}
    if not isinstance(payload, dict):
        payload = {}

    jid = str(payload.get("jid", ""))
    text = str(payload.get("text", ""))
    message_type = payload.get("message_type", "text")
    is_forwarded = bool(payload.get("is_forwarded", False))
    from_me = bool(payload.get("from_me", False))

    relationship, _ = resolve_relationship(jid)
    message_dict = {
        "jid": jid,
        "text": text,
        "message_type": message_type,
        "is_forwarded": is_forwarded,
        "from_me": from_me,
    }

    decision, reason = should_reply(message_dict, relationship)

    retrieval_trace = []
    if relationship not in {"group", "unknown"}:
        try:
            retrieval_trace = retrieve_similar(relationship, text or "", k=3)
        except Exception as exc:  # pragma: no cover - defensive logging path
            retrieval_trace = [{"error": str(exc)}]

    reply = None
    if decision:
        try:
            reply = generate_reply(text, relationship)
        except Exception as exc:  # pragma: no cover - defensive generation path
            reply = None
            reason = f"{reason}; generation error: {exc}"

    response = {
        "should_reply": bool(decision),
        "reply": reply,
        "relationship": relationship,
        "reason": reason,
    }

    _ensure_log_dir()
    with CONSOLE_FEED_PATH.open("a", encoding="utf-8") as log_file:
        log_entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "jid": jid,
            "relationship": relationship,
            "decision": "reply" if decision else "ignore",
            "reason": reason,
            "reply": reply,
            "retrieval_trace": retrieval_trace,
        }
        log_file.write(json.dumps(log_entry, ensure_ascii=False) + "\n")

    return jsonify(response)


@app.get("/health")
def health_check():
    return jsonify({"status": "ok"})


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5001, debug=False)
