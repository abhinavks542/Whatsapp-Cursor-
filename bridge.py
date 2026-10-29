#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from flask import Flask, jsonify, request
from flask.typing import ResponseReturnValue
from flask.wrappers import Response
from groq import APIError
from werkzeug.exceptions import BadRequest

REPO_ROOT = Path(__file__).resolve().parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from agent.decision_engine import should_reply
from agent.generator import generate_reply
from agent.router import resolve_relationship
from ingestion.retrieval import retrieve_similar
from groq_client import is_configured

app = Flask(__name__)
LOGS_DIR = REPO_ROOT / "logs"
CONSOLE_FEED_PATH = LOGS_DIR / "console_feed.jsonl"
MESSAGE_TYPES: frozenset[str] = frozenset({"text", "image", "video", "audio", "other"})


def _error_response(code: str, message: str, status: int) -> tuple[Response, int]:
    return jsonify({"error": {"code": code, "message": message}}), status


def _ensure_log_dir() -> None:
    LOGS_DIR.mkdir(parents=True, exist_ok=True)


@app.post("/process")
def process_message() -> ResponseReturnValue:
    if not request.is_json:
        return _error_response(
            "invalid_content_type", "Request body must be JSON.", 415
        )

    try:
        payload = request.get_json()
    except BadRequest:
        return _error_response("invalid_json", "Request body is not valid JSON.", 400)

    if not isinstance(payload, dict):
        return _error_response(
            "invalid_payload", "Request body must be a JSON object.", 400
        )

    jid = payload.get("jid")
    text = payload.get("text")
    message_type = payload.get("message_type", "text")
    is_forwarded = payload.get("is_forwarded", False)
    from_me = payload.get("from_me", False)

    if not isinstance(jid, str) or not jid.strip():
        return _error_response("invalid_jid", "'jid' must be a non-empty string.", 400)
    if not isinstance(text, str):
        return _error_response("invalid_text", "'text' must be a string.", 400)
    if not isinstance(message_type, str) or message_type not in MESSAGE_TYPES:
        return _error_response(
            "invalid_message_type", "'message_type' is not supported.", 400
        )
    if not isinstance(is_forwarded, bool) or not isinstance(from_me, bool):
        return _error_response(
            "invalid_flags", "'is_forwarded' and 'from_me' must be booleans.", 400
        )

    jid = jid.strip()
    message_dict = {
        "jid": jid,
        "text": text,
        "message_type": message_type,
        "is_forwarded": is_forwarded,
        "from_me": from_me,
    }

    try:
        relationship, _ = resolve_relationship(jid)
    except (OSError, ValueError):
        app.logger.exception("Could not resolve the sender relationship.")
        return _error_response(
            "relationship_resolution_failed",
            "The sender relationship could not be resolved.",
            500,
        )

    try:
        decision, reason = should_reply(message_dict, relationship)
    except OSError:
        app.logger.exception("Could not record the reply decision.")
        return _error_response(
            "decision_recording_failed",
            "The reply decision could not be recorded.",
            500,
        )

    retrieval_trace = []
    if relationship not in {"group", "unknown"}:
        try:
            retrieval_trace = retrieve_similar(relationship, text, k=3)
        except (OSError, TypeError, ValueError):
            app.logger.exception("Could not retrieve conversation examples.")
            return _error_response(
                "retrieval_failed",
                "Conversation examples could not be retrieved.",
                503,
            )

    reply = None
    if decision:
        try:
            reply = generate_reply(text, relationship)
        except (APIError, OSError, RuntimeError, TypeError, ValueError):
            app.logger.exception("Could not generate the reply.")
            return _error_response(
                "reply_generation_failed",
                "The reply could not be generated.",
                503,
            )

    response = {
        "should_reply": bool(decision),
        "reply": reply,
        "relationship": relationship,
        "reason": reason,
    }

    try:
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
    except OSError:
        app.logger.exception("Could not record the message decision.")
        return _error_response(
            "decision_logging_failed",
            "The message decision could not be recorded.",
            500,
        )

    return jsonify(response)


@app.errorhandler(500)
def internal_server_error(_error: Exception) -> tuple[Response, int]:
    return _error_response("internal_error", "An internal error occurred.", 500)


@app.get("/health")
def health_check() -> Response:
    return jsonify({"status": "ok", "aiConfigured": is_configured()})


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5001, debug=False)
