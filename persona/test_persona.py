import json
from pathlib import Path

from groq_client import generate_text, get_client


PROJECT_ROOT = Path(__file__).resolve().parent.parent
PERSONA_PATH = Path(__file__).with_name("persona.json")
TEST_PROMPTS = [
    ("wife", "I am going to be late today, can you pick me up?"),
    ("family", "diwali pe ghar aaoge kya?"),
    ("professional", "I have a new video ready when can we connect?"),
]


def main():
    if not PERSONA_PATH.is_file():
        raise SystemExit(f"Error: persona file not found: {PERSONA_PATH}")

    with PERSONA_PATH.open(encoding="utf-8") as persona_file:
        persona = json.load(persona_file)

    try:
        get_client()
    except RuntimeError as error:
        raise SystemExit(f"Error: {error}") from error

    output_lines = ["# Sample Persona Replies", ""]
    for relationship, incoming in TEST_PROMPTS:
        relationship_data = persona["relationships"][relationship]
        tone = relationship_data["tone"]
        examples = relationship_data["example_replies"]
        prompt = f"""You are texting as: {persona['identity']}
Tone for {relationship}: {tone}
Example replies in this tone: {examples}
Hinglish ratio to match: {persona['hinglish_ratio']}
Incoming message: "{incoming}"
Reply in character, one short WhatsApp-style message only."""

        reply = generate_text(prompt)
        print(f"[{relationship}] {incoming} -> {reply}")
        output_lines.extend(
            [
                f"## {relationship.title()}",
                f"- Incoming: {incoming}",
                f"- Reply: {reply}",
                "",
            ]
        )

    output_path = PROJECT_ROOT / "sample_output.md"
    output_path.write_text("\n".join(output_lines), encoding="utf-8")
    print(f"\nSaved replies to {output_path}")


if __name__ == "__main__":
    main()
