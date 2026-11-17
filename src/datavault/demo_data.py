"""Deterministic synthetic retail seed data (no real customers, no real data).

History is seeded deliberately so PIT reads are verifiable:
- 3 customers change city / loyalty tier mid-quarter.
- 2 products change price mid-quarter.
- Orders move placed -> shipped -> delivered on known dates.
- One customer update is late-arriving: effective 2026-02-10, loaded 2026-03-05.
- A handful of corrupt records exercise the quarantine gate.
"""

from __future__ import annotations

CITIES = ["Springfield", "Riverton", "Lakeside", "Fairview", "Brookfield", "Hillcrest"]

CUSTOMERS = [
    ("CUST-1001", "Ada Lovelace", "ada@example.com", "Springfield", "premium", "gold"),
    ("CUST-1002", "Grace Hopper", "grace@example.com", "Riverton", "business", "silver"),
    ("CUST-1003", "Alan Turing", "alan@example.com", "Lakeside", "consumer", "bronze"),
    ("CUST-1004", "Katherine Johnson", "katherine@example.com", "Fairview", "premium", "gold"),
    ("CUST-1005", "Mary Jackson", "mary@example.com", "Brookfield", "consumer", "bronze"),
    ("CUST-1006", "Dorothy Vaughan", "dorothy@example.com", "Hillcrest", "business", "silver"),
    ("CUST-1007", "Edsger Dijkstra", "edsger@example.com", "Springfield", "consumer", "bronze"),
    ("CUST-1008", "Barbara Liskov", "barbara@example.com", "Riverton", "premium", "platinum"),
    ("CUST-1009", "Donald Knuth", "donald@example.com", "Lakeside", "business", "silver"),
    ("CUST-1010", "Frances Allen", "frances@example.com", "Fairview", "consumer", "bronze"),
    ("CUST-1011", "John Backus", "john@example.com", "Brookfield", "business", "silver"),
    ("CUST-1012", "Betty Holberton", "betty@example.com", "Hillcrest", "premium", "gold"),
]

PRODUCTS = [
    ("SKU-2001", "Trailhead Backpack", "outdoor", 89.99),
    ("SKU-2002", "Summit Water Bottle", "outdoor", 24.50),
    ("SKU-2003", "Meadow Yoga Mat", "fitness", 49.00),
    ("SKU-2004", "Harbor Desk Lamp", "home", 59.99),
    ("SKU-2005", "Beacon Headphones", "electronics", 129.00),
    ("SKU-2006", "Atlas Notebook Set", "office", 19.99),
    ("SKU-2007", "Comet Running Shoes", "fitness", 119.95),
    ("SKU-2008", "Lantern Camping Tent", "outdoor", 199.00),
]


def _customer_record(cid, name, email, city, segment, tier, effective, load=None):
    return {"customer_id": cid, "full_name": name, "email": email, "city": city,
            "segment": segment, "loyalty_tier": tier,
            "effective_dts": effective, "load_dts": load or effective}


def seed_customers() -> list[dict]:
    records = [_customer_record(*c, "2026-01-05T09:00:00Z") for c in CUSTOMERS]
    # Mid-quarter moves (v2 rows).
    records.append(_customer_record("CUST-1001", "Ada Lovelace", "ada@example.com",
                                    "Riverton", "premium", "platinum", "2026-02-10T09:00:00Z"))
    records.append(_customer_record("CUST-1004", "Katherine Johnson", "katherine@example.com",
                                    "Hillcrest", "premium", "platinum", "2026-02-18T09:00:00Z"))
    # Late-arriving: effective Feb 10, but only loaded Mar 5.
    records.append(_customer_record("CUST-1007", "Edsger Dijkstra", "edsger@example.com",
                                    "Lakeside", "consumer", "silver",
                                    "2026-02-10T09:00:00Z", "2026-03-05T09:00:00Z"))
    return records


def seed_products() -> list[dict]:
    records = [{"product_sku": sku, "product_name": name, "category": cat,
                "price": price, "currency": "USD",
                "effective_dts": "2026-01-05T09:00:00Z",
                "load_dts": "2026-01-05T09:00:00Z"}
               for sku, name, cat, price in PRODUCTS]
    records.append({"product_sku": "SKU-2001", "product_name": "Trailhead Backpack",
                    "category": "outdoor", "price": 99.99, "currency": "USD",
                    "effective_dts": "2026-02-15T09:00:00Z",
                    "load_dts": "2026-02-15T09:00:00Z"})
    records.append({"product_sku": "SKU-2005", "product_name": "Beacon Headphones",
                    "category": "electronics", "price": 109.00, "currency": "USD",
                    "effective_dts": "2026-03-01T09:00:00Z",
                    "load_dts": "2026-03-01T09:00:00Z"})
    return records


def seed_orders() -> list[dict]:
    """20 orders; each order has a placed row and a shipped/delivered row."""
    records: list[dict] = []
    channels = ["web", "mobile", "store"]
    for i in range(20):
        oid = f"ORD-{3001 + i}"
        cust = CUSTOMERS[i % len(CUSTOMERS)][0]
        sku, _, _, price = PRODUCTS[i % len(PRODUCTS)]
        qty = (i % 3) + 1
        placed_day = 5 + (i * 4) % 50  # Jan 5 .. Feb 23
        placed = f"2026-01-{placed_day:02d}T10:00:00Z" if placed_day <= 31 else \
            f"2026-02-{placed_day - 31:02d}T10:00:00Z"
        records.append({"order_id": oid, "customer_id": cust, "product_sku": sku,
                        "status": "placed", "total_amount": round(price * qty, 2),
                        "currency": "USD", "channel": channels[i % 3], "quantity": qty,
                        "effective_dts": placed, "load_dts": placed})
        # Status progression a few days later (same effective-date family).
        ship_day = placed_day + 3
        shipped = f"2026-01-{ship_day:02d}T10:00:00Z" if ship_day <= 31 else \
            f"2026-02-{ship_day - 31:02d}T10:00:00Z" if ship_day <= 59 else \
            f"2026-03-{ship_day - 59:02d}T10:00:00Z"
        final = "delivered" if i % 4 != 3 else "shipped"
        records.append({"order_id": oid, "customer_id": cust, "product_sku": sku,
                        "status": final, "total_amount": round(price * qty, 2),
                        "currency": "USD", "channel": channels[i % 3], "quantity": qty,
                        "effective_dts": shipped, "load_dts": shipped})
    return records


def seed_shipments() -> list[dict]:
    carriers = ["SwiftParcel", "NorthStar Freight", "Harbor Logistics"]
    levels = ["standard", "express", "overnight"]
    records: list[dict] = []
    for i in range(12):
        oid = f"ORD-{3001 + i}"
        records.append({"shipment_id": f"SHP-{4001 + i}", "order_id": oid,
                        "carrier": carriers[i % 3], "status": "delivered",
                        "service_level": levels[i % 3],
                        "effective_dts": f"2026-02-{(i % 27) + 1:02d}T12:00:00Z",
                        "load_dts": f"2026-02-{(i % 27) + 1:02d}T12:00:00Z"})
    return records


def seed_corrupt() -> list[dict]:
    """Records the DQ gate must quarantine (bad email, negative price, bad status)."""
    return [
        {"customer_id": "CUST-9999", "full_name": "Bad Email", "email": "not-an-email",
         "city": "Nowhere", "segment": "consumer", "loyalty_tier": "bronze",
         "effective_dts": "2026-03-01T09:00:00Z", "load_dts": "2026-03-01T09:00:00Z"},
        {"product_sku": "SKU-9999", "product_name": "Bad Price", "category": "home",
         "price": -5.0, "currency": "USD",
         "effective_dts": "2026-03-01T09:00:00Z", "load_dts": "2026-03-01T09:00:00Z"},
        {"order_id": "ORD-9999", "customer_id": "CUST-1001", "product_sku": "SKU-2001",
         "status": "teleported", "total_amount": 10.0, "currency": "USD",
         "channel": "web", "quantity": 1,
         "effective_dts": "2026-03-01T09:00:00Z", "load_dts": "2026-03-01T09:00:00Z"},
    ]


def seed_all() -> dict[str, list[dict]]:
    return {"customer": seed_customers(), "product": seed_products(),
            "order": seed_orders(), "shipment": seed_shipments()}


SNAPSHOT_DATES = ["2026-01-31T00:00:00Z", "2026-02-28T00:00:00Z", "2026-03-31T00:00:00Z"]
