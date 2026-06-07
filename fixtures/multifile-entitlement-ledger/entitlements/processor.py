from .events import normalize_event
from .ledger import SeatLedger
from .policy import can_access_feature


def process_subscription_event(
    payload: dict,
    accounts: dict[str, dict],
    ledger: SeatLedger,
    processed_events: set[str],
) -> dict:
    event = normalize_event(payload)
    account = accounts.setdefault(event["account_id"], {})
    account["status"] = event["status"]
    account["plan"] = event["plan"]
    account["seats"] = event["seats"]
    ledger_entry = ledger.record(event["account_id"], event["seats"])

    if event["event_id"] in processed_events:
        return {
            "applied": False,
            "account": account,
            "ledger_entry": ledger_entry,
            "can_access": can_access_feature(account),
        }

    processed_events.add(event["event_id"])
    return {
        "applied": True,
        "account": account,
        "ledger_entry": ledger_entry,
        "can_access": can_access_feature(account),
    }
