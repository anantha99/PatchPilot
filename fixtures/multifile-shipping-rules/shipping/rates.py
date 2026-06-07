from .constants import FREE_SHIPPING_THRESHOLD, STANDARD_SHIPPING_RATE


def shipping_cost(subtotal: float) -> float:
    if subtotal > FREE_SHIPPING_THRESHOLD:
        return 0.0
    return STANDARD_SHIPPING_RATE
