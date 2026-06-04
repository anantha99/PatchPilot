import pytest

from csv_tools import parse_pair


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("name,email", ("name", "email")),
        (" first , second ", ("first", "second")),
    ],
)
def test_parse_comma_pair(text, expected):
    assert parse_pair(text) == expected
