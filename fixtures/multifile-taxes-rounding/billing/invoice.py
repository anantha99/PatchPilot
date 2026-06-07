from .tax import tax_for


def invoice_total(items: list[float]) -> float:
    subtotal = sum(round(item, 2) for item in items)
    tax = sum(tax_for(item) for item in items)
    return round(subtotal + tax, 2)
