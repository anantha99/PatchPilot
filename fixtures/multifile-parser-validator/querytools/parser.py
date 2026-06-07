from .validator import validate_pairs


def parse_pairs(text: str) -> dict[str, str]:
    pairs = {}
    for item in text.split(","):
        key, value = item.split("=", 1)
        pairs[key] = value
    validate_pairs(pairs)
    return pairs
