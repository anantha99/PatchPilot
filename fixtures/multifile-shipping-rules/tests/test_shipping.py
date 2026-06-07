from shipping import shipping_cost
from shipping.constants import FREE_SHIPPING_THRESHOLD


def test_free_shipping_threshold_constant():
    assert FREE_SHIPPING_THRESHOLD == 75.0


def test_free_shipping_starts_at_seventy_five_inclusive():
    assert shipping_cost(75.0) == 0.0


def test_shipping_still_applies_below_threshold():
    assert shipping_cost(74.99) == 8.5
