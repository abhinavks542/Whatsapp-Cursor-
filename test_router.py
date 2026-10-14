import json

import pytest

import decision_engine as decision_engine_module
import generator as generator_module
import groq_client
from agent.router import resolve_relationship


@pytest.fixture
def temp_map(tmp_path):
    map_path = tmp_path / "relationship_map.json"
    map_data = {
        "_default": "unknown",
        "919812345670": "friend",
        "919812345671": "family",
        "919812345672": "professional",
    }
    map_path.write_text(json.dumps(map_data), encoding="utf-8")
    return str(map_path)


def test_known_number_resolves_correctly(temp_map):
    assert resolve_relationship("919812345671@s.whatsapp.net", temp_map) == ("family", "history_family")


def test_unknown_number_falls_back_to_default(temp_map):
    assert resolve_relationship("999999999999@s.whatsapp.net", temp_map) == ("unknown", "history_unknown")


def test_group_jid_always_returns_group_none(temp_map):
    assert resolve_relationship("1234567890-123456@g.us", temp_map) == ("group", None)
    assert resolve_relationship("919812345670@s.whatsapp.net", temp_map) != ("group", None)


def test_malformed_or_empty_jid_does_not_crash(temp_map):
    assert resolve_relationship("", temp_map) == ("unknown", "history_unknown")
    assert resolve_relationship("@", temp_map) == ("unknown", "history_unknown")
    assert resolve_relationship("   ", temp_map) == ("unknown", "history_unknown")


def test_generate_reply_surfaces_model_failure(monkeypatch):
    def raising(*args, **kwargs):
        raise RuntimeError("503 UNAVAILABLE")

    monkeypatch.setattr(generator_module, "generate_text", raising)
    with pytest.raises(RuntimeError, match="503 UNAVAILABLE"):
        generator_module.generate_reply("Hi there", "family")


def test_groq_client_uses_configured_model_and_chat_completion(monkeypatch):
    calls = {}

    class FakeCompletions:
        def create(self, **kwargs):
            calls.update(kwargs)
            message = type("Message", (), {"content": "  Hello there  "})()
            choice = type("Choice", (), {"message": message})()
            return type("Response", (), {"choices": [choice]})()

    fake_client = type(
        "Client",
        (),
        {"chat": type("Chat", (), {"completions": FakeCompletions()})()},
    )()
    monkeypatch.setattr(groq_client, "get_client", lambda: fake_client)
    monkeypatch.setenv("GROQ_MODEL", "test-model")

    assert groq_client.generate_text("Say hello") == "Hello there"
    assert calls == {
        "model": "test-model",
        "messages": [{"role": "user", "content": "Say hello"}],
    }


def test_groq_client_requires_api_key(monkeypatch):
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    groq_client.get_client.cache_clear()

    with pytest.raises(RuntimeError, match="GROQ_API_KEY is not set"):
        groq_client.get_client()


def test_intent_classification_fails_closed_when_groq_is_unavailable(monkeypatch):
    def raising(*args, **kwargs):
        raise RuntimeError("GROQ_API_KEY is not set")

    monkeypatch.setattr(decision_engine_module, "generate_text", raising)
    label, error = decision_engine_module._classify_with_llm("Hello")

    assert label == "needs_human_money_or_serious"
    assert error == "LLM error: GROQ_API_KEY is not set"
