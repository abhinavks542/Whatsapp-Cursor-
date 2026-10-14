from groq_client import generate_text


def main() -> None:
    print(generate_text("Say hello in one word."))


if __name__ == "__main__":
    main()
