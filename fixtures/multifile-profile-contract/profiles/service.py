from .normalizer import normalize_email
from .validators import is_valid_email


def create_profile(email: str) -> dict[str, str]:
    normalized = normalize_email(email)
    if not is_valid_email(normalized):
        raise ValueError("invalid email")
    return {"email": normalized}
