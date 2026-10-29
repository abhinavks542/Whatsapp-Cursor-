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
    if not is_configured():
        raise RuntimeError(
            "GROQ_API_KEY is not set in the environment or project .env file."
        )
    return Groq(api_key=os.environ["GROQ_API_KEY"])


def reload_config() -> None:
    """Reload environment from .env file and invalidate client cache."""
    load_dotenv(PROJECT_ROOT / ".env", override=True)
    get_client.cache_clear()


def is_configured() -> bool:
    """Return whether a non-empty Groq API key is available."""
    return bool(os.getenv("GROQ_API_KEY", "").strip())


def save_api_key(api_key: str, model: str | None = None) -> None:
    """Save Groq API key and optional model to .env and reload."""
    env_path = PROJECT_ROOT / ".env"
    existing_lines = []
    if env_path.exists():
        existing_lines = env_path.read_text(encoding="utf-8").splitlines()

    updated_key = False
    updated_model = False
    new_lines = []
    for line in existing_lines:
        trimmed = line.strip()
        if trimmed.startswith("GROQ_API_KEY="):
            new_lines.append(f"GROQ_API_KEY={api_key.strip()}")
            updated_key = True
        elif model and trimmed.startswith("GROQ_MODEL="):
            new_lines.append(f"GROQ_MODEL={model.strip()}")
            updated_model = True
        else:
            new_lines.append(line)

    if not updated_key:
        new_lines.append(f"GROQ_API_KEY={api_key.strip()}")
    if model and not updated_model:
        new_lines.append(f"GROQ_MODEL={model.strip()}")

    env_path.write_text("\n".join(new_lines) + "\n", encoding="utf-8")
    os.environ["GROQ_API_KEY"] = api_key.strip()
    if model:
        os.environ["GROQ_MODEL"] = model.strip()
    reload_config()


def generate_text(prompt: str) -> str:
    response = get_client().chat.completions.create(
        model=os.getenv("GROQ_MODEL", DEFAULT_MODEL),
        messages=[{"role": "user", "content": prompt}],
    )
    content = response.choices[0].message.content
    if not isinstance(content, str) or not content.strip():
        raise RuntimeError("Groq returned an empty or non-text response.")
    return content.strip()
