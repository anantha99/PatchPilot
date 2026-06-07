from .policy import MINIMUM_REMAINING_STOCK


def can_reserve(on_hand: int, quantity: int) -> bool:
    return on_hand - quantity > MINIMUM_REMAINING_STOCK
