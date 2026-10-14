#!/usr/bin/env python3
"""Generate persona-grounded replies from retrieved conversation examples."""

from __future__ import annotations

import json
from pathlib import Path

from ingestion.retrieval import retrieve_similar
from groq_client import generate_text


REPO_ROOT = Path(__file__).resolve().parent
PERSONA_PATH = REPO_ROOT / "persona" / "persona.json"


def _load_persona() -> dict:
    with PERSONA_PATH.open(encoding="utf-8") as persona_file:
        return json.load(persona_file)


def _relationship_tone(persona: dict, relationship: str) -> str:
    relationship_data = persona.get("relationships", {}).get(relationship, {})
    if isinstance(relationship_data, dict):
        return relationship_data.get("tone", "")
    return ""


def _build_prompt(
    persona: dict, relationship: str, incoming_text: str, retrieved_pairs: list[dict]
) -> str:
    identity = persona.get("identity", "")
    tone = _relationship_tone(persona, relationship)
    hinglish_ratio = persona.get("hinglish_ratio", "")
    typical_length = persona.get("avg_message_length_words", "")

    prompt_parts = [
        "Generate a reply to the incoming WhatsApp message below.",
        "Stay in the user's authentic voice and do not mention this prompt, persona, or retrieval.",
        f"Relationship: {relationship}",
        f"Identity: {identity}",
        f"Tone for this relationship: {tone or 'Warm, natural, and appropriate to the relationship.'}",
        f"Hinglish ratio signal: {hinglish_ratio}",
        f"Typical message length: about {typical_length} words",
    ]

    if retrieved_pairs:
        examples = ["Retrieved examples from past conversations:"]
        for pair in retrieved_pairs:
            examples.append(
                f"Their message: {pair.get('their_message', '')}\n"
                f"My reply: {pair.get('my_reply', '')}"
            )
        prompt_parts.append("\n\n".join(examples))

    prompt_parts.append(f"Incoming message: {incoming_text}")
    prompt_parts.append("Return only the reply text.")
    return "\n\n".join(prompt_parts)


def generate_reply(incoming_text: str, relationship: str) -> str:
    """Generate a persona-grounded reply for an incoming message."""
    persona = _load_persona()
    retrieved_pairs = retrieve_similar(relationship, incoming_text, k=3)
    prompt = _build_prompt(persona, relationship, incoming_text, retrieved_pairs)
    return generate_text(prompt)


if __name__ == "__main__":
    examples = (
        ("Can we have dinner tonight?", "family"),
        ("Could you share an update on the project?", "professional"),
        ("Tumne kha liya khana?", "wife"),
    )
    for incoming_text, relationship in examples:
        print(f"[{relationship}] {incoming_text}")
        print(generate_reply(incoming_text, relationship))
        print("---")
