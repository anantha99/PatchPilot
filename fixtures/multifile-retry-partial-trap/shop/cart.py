from .discounts import discount_multiplier


def cart_total(items: list[float], discount_percent: float) -> float:
    subtotal = sum(items)
    return round(subtotal - discount_multiplier(discount_percent), 2)
