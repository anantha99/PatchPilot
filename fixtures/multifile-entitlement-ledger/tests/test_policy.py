from entitlements.policy import can_access_feature


def test_can_access_feature_allows_trialing_paid_accounts():
    assert can_access_feature({"status": "trialing", "plan": "pro", "seats": 1}) is True


def test_can_access_feature_rejects_past_due_accounts():
    assert can_access_feature({"status": "past_due", "plan": "enterprise", "seats": 8}) is False
