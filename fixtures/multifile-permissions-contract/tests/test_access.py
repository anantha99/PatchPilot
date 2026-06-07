from access import can_read, default_account


def test_default_account_uses_member_role():
    account = default_account("ada@example.com")
    assert account["role"] == "member"
    assert can_read(account) is True


def test_user_role_is_no_longer_readable():
    assert can_read({"email": "old@example.com", "role": "user"}) is False
