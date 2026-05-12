from pathlib import Path

from app.preprocessor import preprocess_websites, preprocess_ads_lines


BASE_DIR = Path(__file__).resolve().parent.parent
CONFIG_DIR = BASE_DIR / "config"


def load_reference_lines() -> set[str]:
    reference_path = CONFIG_DIR / "reference.txt"

    with open(reference_path, "r", encoding="utf-8") as file:
        raw_lines = [line.rstrip("\n") for line in file]

    return preprocess_ads_lines(raw_lines)


def load_websites() -> set[str]:
    websites_path = CONFIG_DIR / "websites.txt"

    with open(websites_path, "r", encoding="utf-8") as file:
        raw_lines = [line.rstrip("\n") for line in file]

    return preprocess_websites(raw_lines)