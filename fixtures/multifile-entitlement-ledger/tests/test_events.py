from entitlements.events import normalize_event


def test_normalize_event_trims_status_plan_and_coerces_seats():
    payload = {
        "id": "evt_1",
        "account_id": "acct_1",
        "status": " Past-Due ",
        "plan": " Pro ",
        "seats": "5",
    }

    assert normalize_event(payload) == {
        "event_id": "evt_1",
        "account_id": "acct_1",
        "status": "past_due",
        "plan": "pro",
        "seats": 5,
    }
