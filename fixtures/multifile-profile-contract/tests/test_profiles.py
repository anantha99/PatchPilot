import pytest

from profiles import create_profile
from profiles.normalizer import normalize_email
from profiles.validators import is_valid_email


def test_normalizer_trims_and_lowercases_email():
    assert normalize_email("  Ada@Example.COM ") == "ada@example.com"


def test_validator_rejects_blank_domain():
    assert is_valid_email("ada@") is False


def test_profile_email_is_trimmed_and_lowercased():
    assert create_profile("  Ada@Example.COM ") == {"email": "ada@example.com"}


def test_blank_domain_is_rejected():
    with pytest.raises(ValueError):
        create_profile("ada@")
