"""Shared Groq chat-completion client configuration."""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv
from groq import Groq


PROJECT_ROOT = Path(__file__).resolve().parent
DEFAULT_MODEL = "openai/gpt-oss-20b"

load_dotenv(PROJECT_ROOT / ".env")


@lru_cache(maxsize=1)
def get_client() -> Groq:
    api_key = os.getenv("GROQ_API_KEY")
    if not api_key:
        raise RuntimeError(
            "GROQ_API_KEY is not set in the environment or project .env file."
        )
    return Groq(api_key=api_key)


def generate_text(prompt: str) -> str:
    response = get_client().chat.completions.create(
        model=os.getenv("GROQ_MODEL", DEFAULT_MODEL),
        messages=[{"role": "user", "content": prompt}],
    )
    content = response.choices[0].message.content
    if not isinstance(content, str) or not content.strip():
        raise RuntimeError("Groq returned an empty or non-text response.")
    return content.strip()
