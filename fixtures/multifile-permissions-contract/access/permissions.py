def can_read(account: dict[str, str]) -> bool:
    return account.get("role") in {"admin", "user"}
