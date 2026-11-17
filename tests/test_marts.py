from datavault.marts import build_marts


def test_marts_are_star_schema(loaded):
    marts = build_marts(loaded, "2026-03-31T00:00:00Z")
    assert len(marts["dim_customer"]) == 12
    assert len(marts["dim_product"]) == 8
    assert len(marts["fact_orders"]) == 20
    assert marts["audit"]["fact_orders_rows"] == 20


def test_marts_reflect_as_of_date(loaded):
    jan = build_marts(loaded, "2026-01-31T00:00:00Z")
    mar = build_marts(loaded, "2026-03-31T00:00:00Z")
    ada_jan = next(d for d in jan["dim_customer"] if d["customer_id"] == "CUST-1001")
    ada_mar = next(d for d in mar["dim_customer"] if d["customer_id"] == "CUST-1001")
    assert ada_jan["city"] == "Springfield"
    assert ada_mar["city"] == "Riverton"
    # January mart has no delivered orders yet for most orders; March does.
    assert all(f["status"] in {"placed", "shipped", "delivered"}
               for f in mar["fact_orders"])


def test_fact_joins_customer_and_product(loaded):
    marts = build_marts(loaded, "2026-03-31T00:00:00Z")
    fact = marts["fact_orders"][0]
    assert fact["customer_key"] is not None
    assert fact["product_key"] is not None
    assert fact["total_amount"] > 0
    assert fact["quantity"] >= 1
    customer_keys = {d["customer_key"] for d in marts["dim_customer"]}
    product_keys = {d["product_key"] for d in marts["dim_product"]}
    assert all(f["customer_key"] in customer_keys for f in marts["fact_orders"])
    assert all(f["product_key"] in product_keys for f in marts["fact_orders"])


def test_mart_rebuild_is_reproducible(loaded):
    first = build_marts(loaded, "2026-03-31T00:00:00Z")
    second = build_marts(loaded, "2026-03-31T00:00:00Z")
    assert first["fact_orders"] == second["fact_orders"]
    assert first["dim_customer"] == second["dim_customer"]
