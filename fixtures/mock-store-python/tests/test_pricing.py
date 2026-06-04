from mock_store.pricing import apply_discount


def test_apply_discount_uses_percentage():
    assert apply_discount(200, 20) == 160


def test_apply_discount_handles_zero_percent():
    assert apply_discount(55, 0) == 55
