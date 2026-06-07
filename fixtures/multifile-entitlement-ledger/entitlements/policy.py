ACTIVE_STATUSES = {"active"}
PAID_PLANS = {"pro", "enterprise"}


def can_access_feature(account: dict) -> bool:
    return (
        account.get("plan") in PAID_PLANS
        and account.get("status") == "active"
        and account.get("seats", 0) > 0
    )
