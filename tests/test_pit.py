from datavault.demo_data import SNAPSHOT_DATES
from datavault.pit import as_of_view, build_bridge, build_pit


def test_pit_returns_correct_as_of_state(loaded):
    store = loaded
    jan = as_of_view(store, "hub_customer", {"customer_id": "CUST-1001"},
                     "sat_customer", "2026-01-31T00:00:00Z")
    mar = as_of_view(store, "hub_customer", {"customer_id": "CUST-1001"},
                     "sat_customer", "2026-03-31T00:00:00Z")
    assert jan["city"] == "Springfield" and jan["loyalty_tier"] == "gold"
    assert mar["city"] == "Riverton" and mar["loyalty_tier"] == "platinum"


def test_pit_before_first_version_returns_none(loaded):
    store = loaded
    assert as_of_view(store, "hub_customer", {"customer_id": "CUST-1001"},
                      "sat_customer", "2026-01-01T00:00:00Z") is None


def test_late_arriving_row_visible_at_its_effective_date(loaded):
    # Edsger's city change is effective Feb 10 but was only loaded Mar 5;
    # a Feb 28 PIT read must still see Lakeside.
    feb = as_of_view(loaded, "hub_customer", {"customer_id": "CUST-1007"},
                     "sat_customer", "2026-02-28T00:00:00Z")
    jan = as_of_view(loaded, "hub_customer", {"customer_id": "CUST-1007"},
                     "sat_customer", "2026-01-31T00:00:00Z")
    assert feb["city"] == "Lakeside" and feb["loyalty_tier"] == "silver"
    assert jan["city"] == "Springfield"


def test_price_history_via_pit(loaded):
    jan = as_of_view(loaded, "hub_product", {"product_sku": "SKU-2001"},
                     "sat_product", "2026-01-31T00:00:00Z")
    mar = as_of_view(loaded, "hub_product", {"product_sku": "SKU-2001"},
                     "sat_product", "2026-03-31T00:00:00Z")
    assert jan["price"] == 89.99
    assert mar["price"] == 99.99


def test_build_pit_covers_all_snapshots(loaded):
    rows = build_pit(loaded, "sat_customer", SNAPSHOT_DATES)
    # 12 customers x 3 snapshots, all have a v1 row by Jan 5.
    assert len(rows) == 36
    jan_rows = [r for r in rows if r["snapshot_dts"].startswith("2026-01-31")]
    assert len(jan_rows) == 12
    # The Mar snapshot for Ada must point at the v2 hash-diff.
    mar_ada = [r for r in rows if r["snapshot_dts"].startswith("2026-03-31")]
    assert len(mar_ada) == 12
    assert all(r["hash_diff"] for r in rows)


def test_build_pit_skips_snapshots_before_first_version(loader, seed):
    loader.load_full("customer", seed["customer"], "b1", "2026-01-05T09:00:00Z")
    rows = build_pit(loader.store, "sat_customer", ["2026-01-01T00:00:00Z"])
    assert rows == []


def test_bridge_resolves_links_as_of_snapshot(loaded):
    rows = build_bridge(loaded, "link_order_customer", SNAPSHOT_DATES)
    # 20 links x 3 snapshots.
    assert len(rows) == 60
    first = rows[0]
    assert set(first["hub_keys"]) == {"hub_order", "hub_customer"}
    # Every customer resolves at every snapshot (v1 rows exist from Jan 5).
    assert all(r["satellite_hash_diffs"]["hub_customer"] is not None for r in rows)
    # At least the January-placed orders resolve on the order side too.
    assert any(r["satellite_hash_diffs"]["hub_order"] is not None for r in rows)


def test_order_status_history_via_pit(loaded):
    placed = as_of_view(loaded, "hub_order", {"order_id": "ORD-3001"},
                        "sat_order", "2026-01-06T00:00:00Z")
    later = as_of_view(loaded, "hub_order", {"order_id": "ORD-3001"},
                       "sat_order", "2026-03-31T00:00:00Z")
    assert placed["status"] == "placed"
    assert later["status"] in {"delivered", "shipped"}
