from mock_store.cart import cart_total


def test_cart_total_applies_discount_to_subtotal():
    assert cart_total([100, 100], discount_percent=10) == 180
