"""Governed marts layer: a star schema built from the vault, never from source.

Dimensions are PIT-resolved as of the build date (so a mart rebuild for an
earlier date reproduces that date's truth exactly), and the fact is built
by joining the order links through the PIT-resolved customer/product
satellites. Marts carry their own audit block: build date, source PIT
snapshot, and row counts, so a consumer can tell what a mart is and when
it was true.
"""

from __future__ import annotations

from typing import Any

from datavault.store import VaultStore


def build_marts(store: VaultStore, as_of_dts: str) -> dict[str, Any]:
    """Build dim_customer, dim_product and fact_orders as of ``as_of_dts``."""
    dim_customer: list[dict[str, Any]] = []
    for hub_key, hub in sorted(store.hubs["hub_customer"].items()):
        row = store.as_of("sat_customer", hub_key, as_of_dts)
        if row is None:
            continue
        dim_customer.append({"customer_key": hub_key,
                             **hub["business_key"], **row["attributes"],
                             "valid_from": row["effective_dts"],
                             "valid_to": row["end_dts"]})

    dim_product: list[dict[str, Any]] = []
    for hub_key, hub in sorted(store.hubs["hub_product"].items()):
        row = store.as_of("sat_product", hub_key, as_of_dts)
        if row is None:
            continue
        dim_product.append({"product_key": hub_key,
                            **hub["business_key"], **row["attributes"],
                            "valid_from": row["effective_dts"],
                            "valid_to": row["end_dts"]})

    customer_by_order: dict[str, str] = {}
    product_by_order: dict[str, str] = {}
    for link in store.links["link_order_customer"].values():
        customer_by_order[link["hub_keys"]["hub_order"]] = link["hub_keys"]["hub_customer"]
    for link in store.links["link_order_product"].values():
        product_by_order[link["hub_keys"]["hub_order"]] = link["hub_keys"]["hub_product"]

    fact_orders: list[dict[str, Any]] = []
    for hub_key, hub in sorted(store.hubs["hub_order"].items()):
        row = store.as_of("sat_order", hub_key, as_of_dts)
        if row is None:
            continue
        attrs = row["attributes"]
        fact_orders.append({
            "order_key": hub_key, **hub["business_key"],
            "customer_key": customer_by_order.get(hub_key),
            "product_key": product_by_order.get(hub_key),
            "status": attrs.get("status"), "quantity": attrs.get("quantity"),
            "total_amount": attrs.get("total_amount"),
            "currency": attrs.get("currency"), "channel": attrs.get("channel"),
            "order_dts": row["effective_dts"],
        })

    marts = {
        "as_of_dts": as_of_dts,
        "dim_customer": dim_customer,
        "dim_product": dim_product,
        "fact_orders": fact_orders,
        "audit": {"build_as_of": as_of_dts,
                  "dim_customer_rows": len(dim_customer),
                  "dim_product_rows": len(dim_product),
                  "fact_orders_rows": len(fact_orders)},
    }
    store.audit.append("marts_built", marts["audit"])
    return marts
