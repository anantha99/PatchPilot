from entitlements.ledger import SeatLedger


def test_seat_ledger_records_deltas_from_previous_seat_count():
    ledger = SeatLedger()

    first = ledger.record("acct_1", 5)
    second = ledger.record("acct_1", 8)

    assert first == {"account_id": "acct_1", "delta": 5, "seats": 5}
    assert second == {"account_id": "acct_1", "delta": 3, "seats": 8}
    assert ledger.current_seats["acct_1"] == 8
