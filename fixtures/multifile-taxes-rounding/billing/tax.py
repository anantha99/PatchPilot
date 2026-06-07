TAX_RATE = 0.08


def tax_for(amount: float) -> float:
    return round(amount * TAX_RATE, 2)
