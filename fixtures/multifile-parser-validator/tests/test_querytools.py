import pytest

from querytools import parse_pairs
from querytools.validator import validate_pairs


def test_parse_pairs_trims_whitespace():
    assert parse_pairs("name = Ada, role = admin") == {"name": "Ada", "role": "admin"}


def test_parse_pairs_rejects_blank_key_after_trim():
    with pytest.raises(ValueError):
        parse_pairs(" = Ada")


def test_validator_rejects_blank_key_after_trim():
    with pytest.raises(ValueError):
        validate_pairs({" ": "Ada"})


def test_validator_rejects_whitespace_only_value():
    with pytest.raises(ValueError):
        validate_pairs({"name": "   "})
