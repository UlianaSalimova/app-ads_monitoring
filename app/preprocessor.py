def preprocess_websites(lines: list[str]) -> set[str]:
    websites_set: set[str] = set()

    for line in lines:
        cleaned = line.replace("\r", "").strip()

        if not cleaned:
            continue

        if cleaned.startswith("#"):
            continue

        if "#" in cleaned:
            cleaned = cleaned.split("#", 1)[0].strip()

        cleaned = cleaned.removeprefix("https://")
        cleaned = cleaned.removeprefix("http://")
        cleaned = cleaned.rstrip("/")

        if not cleaned:
            continue

        websites_set.add(cleaned)

    return websites_set


def preprocess_ads_lines(lines: list[str]) -> set[str]:
    result: set[str] = set()

    for line in lines:
        cleaned = line.replace("\r", "").strip()

        if not cleaned:
            continue

        if "#" in cleaned:
            cleaned = cleaned.split("#", 1)[0].strip()

        if not cleaned:
            continue

        parts = [part.strip() for part in cleaned.split(",")]

        if len(parts) < 3:
            continue

        parts[2] = parts[2].upper()

        normalized_line = ", ".join(parts)

        result.add(normalized_line)

    return result