def normalize_event(payload: dict) -> dict:
    return {
        "event_id": payload["id"],
        "account_id": payload["account_id"],
        "status": payload["status"],
        "plan": payload["plan"],
        "seats": payload["seats"],
    }
