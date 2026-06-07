from ledger import dump_invoice, load_invoice


def test_invoice_round_trips_with_amount_cents():
    invoice = {"id": "inv_1", "amount_cents": 1250}
    assert load_invoice(dump_invoice(invoice)) == invoice


def test_dump_uses_canonical_wire_key():
    assert dump_invoice({"id": "inv_2", "amount_cents": 900}) == {"id": "inv_2", "amount": 900}


def test_load_uses_canonical_wire_key():
    assert load_invoice({"id": "inv_3", "amount": 700}) == {"id": "inv_3", "amount_cents": 700}
