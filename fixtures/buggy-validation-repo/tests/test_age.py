from user_rules import can_register


def test_minor_cannot_register():
    assert can_register(17) is False


def test_adult_can_register():
    assert can_register(18) is True
