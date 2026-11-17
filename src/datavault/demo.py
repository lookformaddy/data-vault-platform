"""End-to-end demo: seed -> full load -> incremental load -> PIT -> marts.

Prints a headline summary and returns it as a dict (used by the CLI, the
FastAPI ``/demo`` endpoint and the test-suite).
"""

from __future__ import annotations

from typing import Any

from datavault.config import Settings, load_default_model
from datavault.demo_data import SNAPSHOT_DATES, seed_all, seed_corrupt
from datavault.loader import VaultLoader
from datavault.marts import build_marts
from datavault.pit import as_of_view, build_bridge, build_pit
from datavault.reconciliation import reconcile_all
from datavault.retention import apply_retention
from datavault.store import VaultStore


def run_demo() -> dict[str, Any]:
    settings = Settings()
    model = load_default_model()
    store = VaultStore(model, settings.hash_salt)
    loader = VaultLoader(store, model, settings)
    seed = seed_all()

    reports = {}
    reports["customers"] = loader.load_full(
        "customer", seed["customer"], "batch-2026-01", "2026-01-05T09:00:00Z").to_dict()
    reports["products"] = loader.load_full(
        "product", seed["product"], "batch-2026-01", "2026-01-05T09:00:00Z").to_dict()
    reports["orders"] = loader.load_full(
        "order", seed["order"], "batch-2026-01", "2026-01-05T09:00:00Z").to_dict()
    reports["shipments"] = loader.load_full(
        "shipment", seed["shipment"], "batch-2026-02", "2026-02-01T09:00:00Z").to_dict()

    # Incremental replay of the same customer file: everything is a no-op.
    replay = loader.load_incremental(
        "customer", seed["customer"], "batch-replay", "2026-03-06T09:00:00Z").to_dict()

    # Corrupt records hit the quarantine gate (3 of 3 quarantined -> gate fails).
    corrupt = seed_corrupt()
    corrupt_report = loader.load("customer", [corrupt[0]], "batch-corrupt",
                                 "2026-03-01T09:00:00Z").to_dict()
    loader.load("product", [corrupt[1]], "batch-corrupt", "2026-03-01T09:00:00Z")
    loader.load("order", [corrupt[2]], "batch-corrupt", "2026-03-01T09:00:00Z")

    # Schema evolution: a new satellite attribute, backfilled on read.
    model.add_satellite_attribute("sat_customer", "preferred_contact", "email")

    # Verifiable PIT reads.
    ada_jan = as_of_view(store, "hub_customer", {"customer_id": "CUST-1001"},
                         "sat_customer", "2026-01-31T00:00:00Z")
    ada_mar = as_of_view(store, "hub_customer", {"customer_id": "CUST-1001"},
                         "sat_customer", "2026-03-31T00:00:00Z")
    edsger_feb = as_of_view(store, "hub_customer", {"customer_id": "CUST-1007"},
                            "sat_customer", "2026-02-28T00:00:00Z")
    backpack_jan = as_of_view(store, "hub_product", {"product_sku": "SKU-2001"},
                              "sat_product", "2026-01-31T00:00:00Z")
    backpack_mar = as_of_view(store, "hub_product", {"product_sku": "SKU-2001"},
                              "sat_product", "2026-03-31T00:00:00Z")

    pit_customer = build_pit(store, "sat_customer", SNAPSHOT_DATES)
    pit_product = build_pit(store, "sat_product", SNAPSHOT_DATES)
    bridge = build_bridge(store, "link_order_customer", SNAPSHOT_DATES)
    marts = build_marts(store, "2026-03-31T00:00:00Z")
    recon = reconcile_all(store, seed)
    retention = apply_retention(store, "2026-03-01T00:00:00Z", dry_run=True)
    audit_ok, broken_seq = store.audit.verify()

    summary: dict[str, Any] = {
        "loads": reports,
        "incremental_replay_skipped": replay["skipped_unchanged"],
        "corrupt_quarantined": corrupt_report["quarantined"],
        "corrupt_gate_failed": corrupt_report["failed_gate"],
        "pit": {
            "ada_jan_city": ada_jan["city"] if ada_jan else None,
            "ada_mar_city": ada_mar["city"] if ada_mar else None,
            "ada_mar_tier": ada_mar["loyalty_tier"] if ada_mar else None,
            "edsger_feb_city_late_arriving": edsger_feb["city"] if edsger_feb else None,
            "backpack_jan_price": backpack_jan["price"] if backpack_jan else None,
            "backpack_mar_price": backpack_mar["price"] if backpack_mar else None,
            "pit_customer_rows": len(pit_customer),
            "pit_product_rows": len(pit_product),
            "bridge_rows": len(bridge),
        },
        "marts": marts["audit"],
        "fact_total_amount": round(sum(f["total_amount"] for f in marts["fact_orders"]), 2),
        "reconciliation": {r.entity: {"passed": r.passed,
                                      "source_rows": r.source_rows,
                                      "vault_rows": r.vault_rows,
                                      "discrepancies": r.discrepancies}
                           for r in recon},
        "retention_dry_run_archivable": retention.satellite_rows_archived,
        "audit_ok": audit_ok,
        "audit_broken_seq": broken_seq,
        "audit_entries": len(store.audit.entries),
        "vault_summary": store.summary(),
        "quarantined_total": len(store.quarantine),
    }
    return summary


def print_demo(summary: dict[str, Any]) -> None:
    loads = summary["loads"]
    print("Data Vault 2.0 — demo")
    print("=" * 60)
    for name, rep in loads.items():
        print(f"{name:10s} staged={rep['staged']:3d} hubs={rep['hubs_inserted']:3d} "
              f"sat_rows={rep['satellite_rows_inserted']:3d} links={rep['links_inserted']:3d} "
              f"quarantined={rep['quarantined']} late={rep['late_arriving']}")
    print(f"incremental replay skipped (no-op): {summary['incremental_replay_skipped']}")
    print(f"corrupt records quarantined: {summary['corrupt_quarantined']} "
          f"(gate failed: {summary['corrupt_gate_failed']})")
    pit = summary["pit"]
    print(f"PIT  Ada Jan city={pit['ada_jan_city']} -> Mar city={pit['ada_mar_city']} "
          f"tier={pit['ada_mar_tier']}")
    print(f"PIT  late-arriving Edsger Feb city={pit['edsger_feb_city_late_arriving']} "
          f"(effective Feb 10, loaded Mar 5)")
    print(f"PIT  backpack price Jan=${pit['backpack_jan_price']} -> Mar=${pit['backpack_mar_price']}")
    print(f"PIT rows: customer={pit['pit_customer_rows']} product={pit['pit_product_rows']} "
          f"bridge={pit['bridge_rows']}")
    print(f"marts: {summary['marts']} fact_total=${summary['fact_total_amount']}")
    for entity, rec in summary["reconciliation"].items():
        print(f"recon {entity:9s} passed={rec['passed']} source={rec['source_rows']} "
              f"vault_sat_rows={rec['vault_rows']}")
    print(f"retention dry-run archivable (cutoff Mar 1): "
          f"{summary['retention_dry_run_archivable']} rows")
    print(f"audit log: {summary['audit_entries']} entries, chain valid={summary['audit_ok']}")
    print(f"quarantined total: {summary['quarantined_total']}")
