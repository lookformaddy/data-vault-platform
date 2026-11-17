from datavault.demo_data import seed_corrupt
from datavault.quality import validate_batch, validate_record


def test_valid_customer_passes():
    record = {"customer_id": "CUST-1", "full_name": "Test Person",
              "email": "test@example.com", "city": "Springfield",
              "segment": "consumer", "loyalty_tier": "bronze",
              "effective_dts": "2026-01-05T09:00:00Z"}
    assert validate_record("customer", record) == []


def test_bad_email_quarantined_with_reason():
    record = {"customer_id": "CUST-1", "full_name": "Test",
              "email": "not-an-email", "city": "Springfield",
              "segment": "consumer", "loyalty_tier": "bronze",
              "effective_dts": "2026-01-05T09:00:00Z"}
    reasons = validate_record("customer", record)
    assert any("email" in r for r in reasons)


def test_negative_price_and_bad_status():
    assert validate_record("product", {"product_sku": "S", "product_name": "P",
                                       "category": "home", "price": -1.0,
                                       "currency": "USD",
                                       "effective_dts": "2026-01-05T09:00:00Z"})
    assert validate_record("order", {"order_id": "O", "customer_id": "C",
                                     "product_sku": "S", "status": "teleported",
                                     "total_amount": 1.0, "currency": "USD",
                                     "channel": "web", "quantity": 1,
                                     "effective_dts": "2026-01-05T09:00:00Z"})


def test_missing_effective_dts_is_a_violation():
    record = {"customer_id": "CUST-1", "full_name": "Test",
              "email": "t@example.com", "city": "X", "segment": "consumer",
              "loyalty_tier": "bronze"}
    assert any("effective_dts" in r for r in validate_record("customer", record))


def test_validate_batch_splits_and_carries_reasons(loader):
    corrupt = seed_corrupt()
    valid, quarantined = validate_batch("customer", [corrupt[0]], "b1",
                                        "2026-03-01T09:00:00Z")
    assert valid == [] and len(quarantined) == 1
    assert quarantined[0].reasons and quarantined[0].batch_id == "b1"


def test_quarantine_rate_gate_fails_batch(loader, seed):
    # 1 corrupt record in a 1-record batch = 100% quarantine rate.
    report = loader.load("customer", [seed_corrupt()[0]], "bad-batch",
                         "2026-03-01T09:00:00Z")
    assert report.failed_gate is True
    assert report.quarantined == 1
    assert len(loader.store.hubs["hub_customer"]) == 0  # nothing loaded


def test_quarantine_does_not_block_small_bad_fraction(loader, seed):
    from datavault.config import Settings
    loader.settings = Settings(max_quarantine_rate=0.10)
    records = seed["customer"] + [seed_corrupt()[0]]  # 1/16 quarantined
    report = loader.load("customer", records, "mixed-batch", "2026-03-01T09:00:00Z")
    assert report.failed_gate is False
    assert report.quarantined == 1
    assert report.hubs_inserted == 12
