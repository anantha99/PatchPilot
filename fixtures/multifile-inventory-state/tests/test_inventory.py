from inventory import can_reserve
from inventory.policy import MINIMUM_REMAINING_STOCK


def test_inventory_policy_keeps_twelve_items_available():
    assert MINIMUM_REMAINING_STOCK == 12


def test_reservation_keeps_twelve_items_available():
    assert can_reserve(20, 8) is True


def test_reservation_rejects_below_twelve_items_available():
    assert can_reserve(20, 9) is False
