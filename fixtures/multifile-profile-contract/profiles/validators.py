def is_valid_email(email: str) -> bool:
    return "@" in email and email == email.lower()
