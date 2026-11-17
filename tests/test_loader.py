from datavault.demo_data import seed_all
from datavault.hashing import hash_business_key


def test_full_load_creates_hubs_links_satellites(loader, seed):
    report = loader.load_full("customer", seed["customer"], "b1", "2026-01-05T09:00:00Z")
    assert report.hubs_inserted == 12
    assert report.satellite_rows_inserted == 15  # 12 v1 + 3 v2 rows
    # No row arrives after a later-dated version exists in this seed order;
    # the delayed Edsger load is verified via the PIT read in test_pit.py.
    assert report.late_arriving == 0
    assert report.quarantined == 0


def test_order_load_creates_links(loader, seed):
    loader.load_full("customer", seed["customer"], "b1", "2026-01-05T09:00:00Z")
    loader.load_full("product", seed["product"], "b1", "2026-01-05T09:00:00Z")
    report = loader.load_full("order", seed["order"], "b1", "2026-01-05T09:00:00Z")
    assert report.hubs_inserted == 20
    assert report.links_inserted == 40  # 20 order-customer + 20 order-product
    assert len(loader.store.links["link_order_customer"]) == 20
    assert len(loader.store.links["link_order_product"]) == 20


def test_hash_diff_prevents_duplicate_satellite_rows(loader, seed):
    loader.load_full("customer", seed["customer"], "b1", "2026-01-05T09:00:00Z")
    report = loader.load_full("customer", seed["customer"], "b2", "2026-03-06T09:00:00Z")
    assert report.satellite_rows_inserted == 0
    assert report.skipped_unchanged == 15
    assert len(loader.store.satellites["sat_customer"]) == 15


def test_incremental_replay_is_checksum_noop(loader, seed):
    loader.load_full("customer", seed["customer"], "b1", "2026-01-05T09:00:00Z")
    report = loader.load_incremental("customer", seed["customer"], "b2",
                                     "2026-03-06T09:00:00Z")
    assert report.satellite_rows_inserted == 0
    assert report.skipped_unchanged == 15


def test_incremental_load_picks_up_only_new_records(loader, seed):
    loader.load_full("customer", seed["customer"], "b1", "2026-01-05T09:00:00Z")
    new = [{"customer_id": "CUST-1013", "full_name": "New Person",
            "email": "new@example.com", "city": "Springfield",
            "segment": "consumer", "loyalty_tier": "bronze",
            "effective_dts": "2026-03-10T09:00:00Z",
            "load_dts": "2026-03-10T09:00:00Z"}]
    report = loader.load_incremental("customer", new, "b2", "2026-03-10T09:00:00Z")
    assert report.hubs_inserted == 1 and report.satellite_rows_inserted == 1


def test_late_arriving_row_is_inserted_in_timeline_order(loader):
    records = [
        {"customer_id": "CUST-1", "full_name": "A", "email": "a@example.com",
         "city": "Springfield", "segment": "consumer", "loyalty_tier": "bronze",
         "effective_dts": "2026-01-05T09:00:00Z", "load_dts": "2026-01-05T09:00:00Z"},
        {"customer_id": "CUST-1", "full_name": "A", "email": "a@example.com",
         "city": "Riverton", "segment": "consumer", "loyalty_tier": "silver",
         "effective_dts": "2026-03-01T09:00:00Z", "load_dts": "2026-03-01T09:00:00Z"},
        # Late-arriving February correction, loaded in March.
        {"customer_id": "CUST-1", "full_name": "A", "email": "a@example.com",
         "city": "Lakeside", "segment": "consumer", "loyalty_tier": "silver",
         "effective_dts": "2026-02-10T09:00:00Z", "load_dts": "2026-03-05T09:00:00Z"},
    ]
    report = loader.load_full("customer", records, "b1", "2026-03-05T09:00:00Z")
    assert report.late_arriving == 1
    hub_key = loader.store.hub_key("hub_customer", {"customer_id": "CUST-1"})
    rows = loader.store.satellite_rows("sat_customer", hub_key)
    assert [r["attributes"]["city"] for r in rows] == ["Springfield", "Lakeside", "Riverton"]
    assert rows[0]["end_dts"] == "2026-02-10T09:00:00Z"
    assert rows[1]["end_dts"] == "2026-03-01T09:00:00Z"
    assert rows[2]["end_dts"] is None


def test_same_effective_date_correction_replaces_in_place(loader):
    base = {"customer_id": "CUST-1", "full_name": "A", "email": "a@example.com",
            "city": "Springfield", "segment": "consumer", "loyalty_tier": "bronze",
            "effective_dts": "2026-01-05T09:00:00Z", "load_dts": "2026-01-05T09:00:00Z"}
    loader.load_full("customer", [base], "b1", "2026-01-05T09:00:00Z")
    corrected = {**base, "city": "Riverton", "load_dts": "2026-01-06T09:00:00Z"}
    report = loader.load_full("customer", [corrected], "b2", "2026-01-06T09:00:00Z")
    assert report.satellite_rows_corrected == 1
    assert len(loader.store.satellites["sat_customer"]) == 1


def test_audit_columns_present_on_every_row(loaded):
    store = loaded
    hub = next(iter(store.hubs["hub_customer"].values()))
    assert {"load_dts", "load_source", "record_source", "load_batch_id"} <= set(hub)
    row = store.satellites["sat_customer"][0]
    assert {"load_dts", "load_source", "record_source", "load_batch_id"} <= set(row)
    assert row["hash_diff"]
    assert row["effective_dts"] and row["end_dts"] is not None or row["end_dts"] is None


def test_unknown_entity_rejected(loader):
    import pytest
    with pytest.raises(ValueError):
        loader.load_full("widget", [], "b1", "2026-01-05T09:00:00Z")


def test_schema_evolution_backfills_default_on_read(loaded, model):
    model.add_satellite_attribute("sat_customer", "preferred_contact", "email")
    hub_key = loaded.hub_key("hub_customer", {"customer_id": "CUST-1001"})
    row = loaded.as_of("sat_customer", hub_key, "2026-03-31T00:00:00Z")
    assert row["attributes"]["preferred_contact"] == "email"
    # History is not rewritten: stored rows keep their original hash-diff.
    assert len(loaded.satellites["sat_customer"]) == 15


def test_duplicate_attribute_evolution_rejected(model):
    import pytest
    with pytest.raises(ValueError):
        model.add_satellite_attribute("sat_customer", "city", "Springfield")
