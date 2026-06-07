from shop import cart_total


def test_cart_total_uses_discount_multiplier():
    assert cart_total([100.0, 50.0], 20) == 120.0
