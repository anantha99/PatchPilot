from billing import invoice_total
from billing.tax import tax_for


def test_tax_policy_uses_current_rate():
    assert tax_for(100.0) == 8.3


def test_invoice_uses_current_tax_rate_on_subtotal():
    assert invoice_total([10.015, 10.015]) == 21.69


def test_invoice_rounds_subtotal_once():
    assert invoice_total([0.05, 0.05, 0.05]) == 0.16
