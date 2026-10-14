#!/usr/bin/env python3
"""Embed historical WhatsApp pairs and store them in relationship histories."""

import hashlib
import json
import sys
from collections import defaultdict
from pathlib import Path

import chromadb
from sentence_transformers import SentenceTransformer


PROJECT_ROOT = Path(__file__).resolve().parent.parent
PAIRS_PATH = PROJECT_ROOT / "data" / "processed_pairs.jsonl"
MAP_PATH = PROJECT_ROOT / "config" / "contact_relationship_map.json"
MODEL_NAME = "paraphrase-multilingual-mpnet-base-v2"
CHROMA_HOST = "localhost"
CHROMA_PORT = 8000
BATCH_SIZE = 50
RELATIONSHIPS = ("family", "friend", "professional", "unknown")
PLACEHOLDER = "REPLACE_ME"


def load_pairs() -> list[dict[str, str]]:
    pairs = []
    with PAIRS_PATH.open(encoding="utf-8") as pairs_file:
        for line_number, line in enumerate(pairs_file, start=1):
            if not line.strip():
                continue
            try:
                pair = json.loads(line)
            except json.JSONDecodeError as error:
                raise ValueError(f"Invalid JSON on line {line_number}: {error}") from error
            if not isinstance(pair, dict):
                raise ValueError(f"Line {line_number} must contain a JSON object")
            pairs.append(pair)
    return pairs


def load_relationship_map() -> dict[str, str]:
    with MAP_PATH.open(encoding="utf-8") as map_file:
        relationship_map = json.load(map_file)
    if not isinstance(relationship_map, dict):
        raise ValueError(f"Expected {MAP_PATH} to contain a JSON object")
    return relationship_map


def relationship_for(pair: dict[str, str], relationship_map: dict[str, str]) -> str:
    relationship = relationship_map.get(
        pair.get("conversation_id", ""), relationship_map.get("_default", "unknown")
    )
    if relationship == PLACEHOLDER or relationship not in RELATIONSHIPS:
        return "unknown"
    return relationship


def stable_id(pair: dict[str, str], index: int) -> str:
    identity = "\x1f".join(
        (
            pair.get("conversation_id", ""),
            pair.get("timestamp", ""),
            str(index),
        )
    )
    return hashlib.sha256(identity.encode("utf-8")).hexdigest()


def main() -> int:
    try:
        pairs = load_pairs()
        relationship_map = load_relationship_map()
    except (OSError, json.JSONDecodeError, ValueError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1

    client = chromadb.HttpClient(host=CHROMA_HOST, port=CHROMA_PORT)
    collections = {
        relationship: client.get_or_create_collection(f"history_{relationship}")
        for relationship in RELATIONSHIPS
    }
    upsert_counts: defaultdict[str, int] = defaultdict(int)

    if pairs:
        print("Loading multilingual embedding model (first run downloads model files)...")
        embedder = SentenceTransformer(MODEL_NAME)
        for batch_start in range(0, len(pairs), BATCH_SIZE):
            batch = pairs[batch_start : batch_start + BATCH_SIZE]
            tagged_batch = [
                (pair, relationship_for(pair, relationship_map), batch_start + offset)
                for offset, pair in enumerate(batch)
            ]
            embeddings = embedder.encode(
                [pair.get("their_message", "") for pair, _, _ in tagged_batch],
                show_progress_bar=False,
            )

            grouped = defaultdict(list)
            for (pair, relationship, index), embedding in zip(tagged_batch, embeddings):
                grouped[relationship].append((pair, embedding.tolist(), index))

            for relationship, records in grouped.items():
                ids = [stable_id(pair, index) for pair, _, index in records]
                for other_relationship in RELATIONSHIPS:
                    if other_relationship != relationship:
                        collections[other_relationship].delete(ids=ids)
                collections[relationship].upsert(
                    ids=ids,
                    embeddings=[embedding for _, embedding, _ in records],
                    documents=[pair.get("their_message", "") for pair, _, _ in records],
                    metadatas=[
                        {
                            "relationship": relationship,
                            "my_reply": pair.get("my_reply", ""),
                            "timestamp": pair.get("timestamp", ""),
                        }
                        for pair, _, _ in records
                    ],
                )
                upsert_counts[relationship] += len(records)

            processed = min(batch_start + len(batch), len(pairs))
            if processed % BATCH_SIZE == 0 or processed == len(pairs):
                print(f"Processed {processed}/{len(pairs)} pairs")

    print("\nChroma embedding summary:")
    for relationship in RELATIONSHIPS:
        collection_count = collections[relationship].count()
        print(
            f"- history_{relationship}: {upsert_counts[relationship]} pairs "
            f"upserted; {collection_count} total stored"
        )
        if collection_count == 0:
            print(f"  WARNING: history_{relationship} is completely empty")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())