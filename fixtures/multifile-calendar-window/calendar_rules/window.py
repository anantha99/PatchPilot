from .constants import MAX_BOOKING_DAYS, WEEKEND_DAYS


def can_book(days_from_now: int, weekday: int) -> bool:
    if weekday in WEEKEND_DAYS:
        return False
    return 0 <= days_from_now < MAX_BOOKING_DAYS
