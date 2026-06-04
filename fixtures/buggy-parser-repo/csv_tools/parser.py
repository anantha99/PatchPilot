def parse_pair(text: str) -> tuple[str, str]:
    left, right = text.split("-")
    return left.strip(), right.strip()
