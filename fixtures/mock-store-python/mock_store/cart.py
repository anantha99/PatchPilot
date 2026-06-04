from .pricing import apply_discount


def cart_total(prices: list[float], discount_percent: float = 0) -> float:
    subtotal = sum(prices)
    return apply_discount(subtotal, discount_percent)
