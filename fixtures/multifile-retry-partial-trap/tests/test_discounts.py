from shop import discount_multiplier


def test_discount_multiplier_is_fraction_remaining():
    assert discount_multiplier(20) == 0.8
