from calendar_rules import can_book
from calendar_rules.constants import MAX_BOOKING_DAYS, WEEKEND_DAYS


def test_booking_policy_constants():
    assert MAX_BOOKING_DAYS == 30
    assert WEEKEND_DAYS == {5, 6}


def test_booking_window_is_inclusive_at_thirty_days():
    assert can_book(30, 2) is True


def test_sunday_is_a_weekend():
    assert can_book(5, 6) is False
