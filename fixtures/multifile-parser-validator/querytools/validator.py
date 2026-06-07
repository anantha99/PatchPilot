def validate_pairs(pairs: dict[str, str]) -> None:
    for key, value in pairs.items():
        if not key:
            raise ValueError("blank key")
        if value == "":
            raise ValueError("blank value")
