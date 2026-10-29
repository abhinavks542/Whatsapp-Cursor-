import json

import pytest

import bridge


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(bridge, "LOGS_DIR", tmp_path / "logs")
    monkeypatch.setattr(bridge, "CONSOLE_FEED_PATH", tmp_path / "logs" / "feed.jsonl")
    bridge.app.config.update(TESTING=False)
    return bridge.app.test_client()


def test_process_rejects_non_json(client):
    response = client.post("/process", data="{}", content_type="text/plain")

    assert response.status_code == 415
    assert response.json["error"]["code"] == "invalid_content_type"


def test_health_reports_whether_ai_is_configured(client, monkeypatch):
    monkeypatch.setattr(bridge, "is_configured", lambda: False)

    response = client.get("/health")

    assert response.status_code == 200
    assert response.json == {"status": "ok", "aiConfigured": False}


def test_process_rejects_malformed_json(client):
    response = client.post("/process", data="{", content_type="application/json")

    assert response.status_code == 400
    assert response.json["error"]["code"] == "invalid_json"


@pytest.mark.parametrize(
    ("payload", "error_code"),
    [
        ([], "invalid_payload"),
        ({"jid": " ", "text": "hello"}, "invalid_jid"),
        ({"jid": "123@s.whatsapp.net", "text": 42}, "invalid_text"),
        (
            {"jid": "123@s.whatsapp.net", "text": "hello", "message_type": "exe"},
            "invalid_message_type",
        ),
        (
            {"jid": "123@s.whatsapp.net", "text": "hello", "message_type": []},
            "invalid_message_type",
        ),
        (
            {
                "jid": "123@s.whatsapp.net",
                "text": "hello",
                "is_forwarded": "false",
            },
            "invalid_flags",
        ),
    ],
)
def test_process_rejects_invalid_payloads(client, payload, error_code):
    response = client.post("/process", json=payload)

    assert response.status_code == 400
    assert response.json["error"]["code"] == error_code


def test_process_returns_valid_decision(client, monkeypatch):
    monkeypatch.setattr(bridge, "resolve_relationship", lambda _jid: ("family", "history_family"))
    monkeypatch.setattr(bridge, "should_reply", lambda *_args: (True, "passed all gates"))
    monkeypatch.setattr(bridge, "retrieve_similar", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(bridge, "generate_reply", lambda *_args: "Hello")

    response = client.post(
        "/process",
        json={"jid": "123@s.whatsapp.net", "text": "Hi"},
    )

    assert response.status_code == 200
    assert response.json == {
        "should_reply": True,
        "reply": "Hello",
        "relationship": "family",
        "reason": "passed all gates",
    }


def test_process_surfaces_reply_generation_failure(client, monkeypatch):
    monkeypatch.setattr(bridge, "resolve_relationship", lambda _jid: ("family", "history_family"))
    monkeypatch.setattr(bridge, "should_reply", lambda *_args: (True, "passed all gates"))
    monkeypatch.setattr(bridge, "retrieve_similar", lambda *_args, **_kwargs: [])

    def fail_generation(*_args):
        raise RuntimeError("model unavailable")

    monkeypatch.setattr(bridge, "generate_reply", fail_generation)
    response = client.post(
        "/process",
        json={"jid": "123@s.whatsapp.net", "text": "Hi"},
    )

    assert response.status_code == 503
    assert response.json["error"]["code"] == "reply_generation_failed"
    assert not bridge.CONSOLE_FEED_PATH.exists()


def test_process_surfaces_retrieval_failure(client, monkeypatch):
    monkeypatch.setattr(bridge, "resolve_relationship", lambda _jid: ("family", "history_family"))
    monkeypatch.setattr(bridge, "should_reply", lambda *_args: (False, "ignored"))

    def fail_retrieval(*_args, **_kwargs):
        raise OSError("data unavailable")

    monkeypatch.setattr(bridge, "retrieve_similar", fail_retrieval)
    response = client.post(
        "/process",
        json={"jid": "123@s.whatsapp.net", "text": "Hi"},
    )

    assert response.status_code == 503
    assert response.json["error"]["code"] == "retrieval_failed"


def test_process_returns_json_for_unexpected_server_errors(client, monkeypatch):
    def fail_resolution(_jid):
        raise RuntimeError("unexpected failure")

    monkeypatch.setattr(bridge, "resolve_relationship", fail_resolution)
    response = client.post(
        "/process",
        json={"jid": "123@s.whatsapp.net", "text": "Hi"},
    )

    assert response.status_code == 500
    assert response.json == {
        "error": {"code": "internal_error", "message": "An internal error occurred."}
    }


def test_successful_decision_is_written_as_jsonl(client, monkeypatch):
    monkeypatch.setattr(bridge, "resolve_relationship", lambda _jid: ("unknown", "history_unknown"))
    monkeypatch.setattr(bridge, "should_reply", lambda *_args: (False, "sender not in allowlist"))

    response = client.post(
        "/process",
        json={"jid": "123@s.whatsapp.net", "text": "Hi"},
    )

    log_entry = json.loads(bridge.CONSOLE_FEED_PATH.read_text(encoding="utf-8"))
    assert response.status_code == 200
    assert log_entry["decision"] == "ignore"
    assert log_entry["jid"] == "123@s.whatsapp.net"
