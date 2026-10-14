#!/usr/bin/env python3
"""Run retrieval checks against relationship-specific Chroma histories."""

import argparse
import sys
from contextlib import redirect_stdout
from pathlib import Path

import chromadb
from sentence_transformers import SentenceTransformer


PROJECT_ROOT = Path(__file__).resolve().parent.parent
MODEL_NAME = "paraphrase-multilingual-mpnet-base-v2"
CHROMA_HOST = "localhost"
CHROMA_PORT = 8000
RELATIONSHIPS = ("family", "friend", "professional", "unknown")
RESULTS_PATH = PROJECT_ROOT / "retrieval_results.txt"
SAMPLE_QUERIES = {
    "family": (
        "What are we doing this weekend?",
        "Can you remind me about the family plans?",
        "I reached home safely.",
    ),
    "friend": (
        "Want to meet up for coffee?",
        "That was really fun, let's do it again.",
        "Are you free this evening?",
    ),
    "professional": (
        "Could you share an update on the project timeline?",
        "Please confirm the meeting time and next steps.",
        "I will review this and get back to you shortly.",
    ),
    "unknown": (
        "Can you send me an update?",
        "What time should we meet?",
        "Thanks, I will check and let you know.",
    ),
}


class Tee:
    """Write the report to both the terminal and results file."""

    def __init__(self, terminal, report_file):
        self.terminal = terminal
        self.report_file = report_file

    def write(self, text: str) -> int:
        self.terminal.write(text)
        self.report_file.write(text)
        self.report_file.flush()
        return len(text)

    def flush(self) -> None:
        self.terminal.flush()
        self.report_file.flush()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Demo retrieval from relationship-specific Chroma histories."
    )
    parser.add_argument(
        "--relationship",
        choices=("all", *RELATIONSHIPS),
        default="all",
        help="Relationship collection to search (default: all four).",
    )
    parser.add_argument(
        "--query",
        help="Use one query for each selected relationship instead of sample queries.",
    )
    return parser


def print_results(relationship: str, query: str, result: dict) -> bool:
    distances = result.get("distances", [[]])[0]
    documents = result.get("documents", [[]])[0]
    metadatas = result.get("metadatas", [[]])[0]

    print("\n" + "=" * 72)
    print(f"Relationship: {relationship}")
    print(f"Test query: {query}")
    print("=" * 72)
    for number, (distance, document, metadata) in enumerate(
        zip(distances, documents, metadatas), start=1
    ):
        print("---")
        print(f"Result {number} | distance: {distance:.6f}")
        print(f"Their message: {document}")
        print(f"My reply: {metadata.get('my_reply', '')}")
        print(f"Timestamp: {metadata.get('timestamp', '')}")
    print("---")
    return all(left <= right for left, right in zip(distances, distances[1:]))


def run_demo(args: argparse.Namespace) -> None:
    relationships = RELATIONSHIPS if args.relationship == "all" else (args.relationship,)
    client = chromadb.HttpClient(host=CHROMA_HOST, port=CHROMA_PORT)
    collections = {
        relationship: client.get_or_create_collection(f"history_{relationship}")
        for relationship in relationships
    }
    counts = {relationship: collection.count() for relationship, collection in collections.items()}
    active = [relationship for relationship in relationships if counts[relationship] > 0]

    # Load the model only once, and skip downloading it when all collections are empty.
    model = SentenceTransformer(MODEL_NAME) if active else None
    checks: dict[str, list[bool]] = {relationship: [] for relationship in relationships}

    for relationship in relationships:
        collection_name = f"history_{relationship}"
        if counts[relationship] == 0:
            print(f"⚠️ no data in {collection_name}, skipping")
            continue

        collection = collections[relationship]
        queries = (args.query,) if args.query else SAMPLE_QUERIES[relationship]
        for query in queries:
            query_embedding = model.encode([query], show_progress_bar=False)[0].tolist()
            result = collection.query(
                query_embeddings=[query_embedding],
                n_results=min(3, counts[relationship]),
                include=["documents", "metadatas", "distances"],
            )
            checks[relationship].append(print_results(relationship, query, result))

    print("\nSanity checks:")
    for relationship in relationships:
        relationship_checks = checks[relationship]
        if not relationship_checks:
            print(f"- {relationship}: skipped (no data)")
        elif all(relationship_checks):
            print(f"- {relationship}: distances monotonically increasing (expected/good)")
        else:
            print(
                f"- {relationship}: distances not monotonically increasing "
                "(worth a second look)"
            )


def main() -> None:
    args = build_parser().parse_args()
    with RESULTS_PATH.open("w", encoding="utf-8") as report_file:
        with redirect_stdout(Tee(sys.stdout, report_file)):
            run_demo(args)
    print(f"\nSaved retrieval results to {RESULTS_PATH}")


if __name__ == "__main__":
    main()