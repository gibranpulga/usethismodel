from app.costing import estimate_token_cost


def test_token_cost_classes_and_batch_are_explicit():
    prices = {"INPUT": {"amount": 2, "unit": "per_1m_tokens"},
              "OUTPUT": {"amount": 8, "unit": "per_1m_tokens"},
              "CACHE_READ": {"amount": .5, "unit": "per_1m_tokens"},
              "CACHE_WRITE": {"amount": 3, "unit": "per_1m_tokens"},
              "BATCH_INPUT": {"amount": 1.2, "unit": "per_1m_tokens"}}
    usage = {"input": 1_000_000, "output": 1_000_000,
             "cache_read": 100_000, "cache_write": 50_000}
    result = estimate_token_cost(prices, usage, batch=True)
    assert result["cost"] == 9.4
    assert result["batch_classes_used"] == ["BATCH_INPUT"]


def test_missing_class_and_native_units_are_not_invented():
    assert estimate_token_cost({"INPUT": {"amount": 1, "unit": "per_1m_tokens"}},
                               {"input": 0, "output": 1})["missing"] == ["OUTPUT"]
    assert estimate_token_cost({"INPUT": {"amount": 1, "unit": "per_image"}},
                               {"input": 1})["cost"] is None


def test_subscription_allowance_is_outside_payg_estimate():
    # Plans are not inputs to the PAYG calculator.
    assert estimate_token_cost({"INPUT": {"amount": 1, "unit": "per_1m_tokens"}},
                               {"input": 1})["cost"] == 0.000001
