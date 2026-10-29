#!/usr/bin/env python3
"""Lightweight retrieval fallback used when the Chroma-backed pipeline is unavailable."""

from __future__ import annotations

import json
import re
from collections import Counter
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
PAIRS_PATH = PROJECT_ROOT / "data" / "processed_pairs.jsonl"
RELATIONSHIP_MAP_PATH = PROJECT_ROOT / "config" / "relationship_map.json"


def _load_pairs() -> list[dict]:
    if not PAIRS_PATH.exists():
        return []
    pairs: list[dict] = []
    with PAIRS_PATH.open("r", encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            try:
                value = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(value, dict):
                pairs.append(value)
    return pairs


def _normalized_tokens(text: str) -> Counter[str]:
    words = re.findall(r"[\w']+", (text or "").lower())
    return Counter(words)


def _candidate_pairs(relationship: str, query: str) -> list[dict]:
    query_tokens = _normalized_tokens(query)
    pairs = _load_pairs()
    scored: list[tuple[float, dict]] = []

    for pair in pairs:
        pair_relationship = str(pair.get("conversation_id") or "").strip()
        if relationship and pair_relationship and pair_relationship != relationship:
            continue
        text = str(pair.get("their_message") or "")
        tokens = _normalized_tokens(text)
        overlap = sum(min(query_tokens.get(token, 0), count) for token, count in tokens.items())
        if overlap == 0:
            overlap = 1 if query.strip() and text.strip() else 0
        scored.append((float(overlap), pair))

    return [pair for _, pair in sorted(scored, key=lambda item: item[0], reverse=True)]


def retrieve_similar(relationship: str, incoming_text: str, k: int = 3) -> list[dict]:
    """Return the closest conversation examples for a relationship and query.

    This keeps the project functional even when the local Chroma vector store is absent.
    It falls back to lightweight lexical matching over processed pairs.
    """
    if not isinstance(incoming_text, str):
        return []

    if not incoming_text.strip():
        return []

    pairs = _candidate_pairs(relationship, incoming_text)
    return pairs[: max(0, int(k))]


__all__ = ["retrieve_similar"]
