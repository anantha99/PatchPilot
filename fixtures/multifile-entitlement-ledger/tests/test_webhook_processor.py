from entitlements import SeatLedger, process_subscription_event


def test_process_subscription_event_normalizes_records_delta_and_is_idempotent():
    accounts = {
        "acct_1": {
            "status": "active",
            "plan": "starter",
            "seats": 2,
        }
    }
    ledger = SeatLedger()
    processed_events: set[str] = set()
    payload = {
        "id": "evt_1",
        "account_id": "acct_1",
        "status": " Trialing ",
        "plan": " Pro ",
        "seats": "5",
    }

    first = process_subscription_event(payload, accounts, ledger, processed_events)
    duplicate = process_subscription_event(payload, accounts, ledger, processed_events)

    assert first["applied"] is True
    assert first["account"] == {"status": "trialing", "plan": "pro", "seats": 5}
    assert first["ledger_entry"] == {"account_id": "acct_1", "delta": 3, "seats": 5}
    assert first["can_access"] is True
    assert duplicate["applied"] is False
    assert duplicate["ledger_entry"] is None
    assert len(ledger.entries) == 1
