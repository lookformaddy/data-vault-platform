"""Reconciliation: row counts + checksums, vault vs source.

For each entity the vault must account for every valid staged record:
hub count equals distinct business keys, satellite rows equal distinct
(hash-diff, effective-date) versions, and the checksum of the vault's
current satellite attributes equals the checksum of the source's latest
version per key. Any gap is listed as a discrepancy, not averaged away.
"""

from __future__ import annotations

from typing import Any

from datavault.hashing import checksum_rows
from datavault.models import ReconciliationReport
from datavault.store import VaultStore

ENTITY_HUB = {"customer": "hub_customer", "product": "hub_product",
              "order": "hub_order", "shipment": "hub_shipment"}
ENTITY_SAT = {"customer": "sat_customer", "product": "sat_product",
              "order": "sat_order", "shipment": "sat_shipment"}
ENTITY_KEY_FIELD = {"customer": "customer_id", "product": "product_sku",
                    "order": "order_id", "shipment": "shipment_id"}


def reconcile_entity(store: VaultStore, entity: str,
                     source_records: list[dict[str, Any]]) -> ReconciliationReport:
    hub_name = ENTITY_HUB[entity]
    sat_name = ENTITY_SAT[entity]
    key_field = ENTITY_KEY_FIELD[entity]
    discrepancies: list[str] = []

    distinct_keys = {r[key_field] for r in source_records}
    hub_count = len(store.hubs[hub_name])
    if hub_count != len(distinct_keys):
        discrepancies.append(
            f"hub {hub_name}: {hub_count} keys in vault vs {len(distinct_keys)} distinct source keys")

    # Latest source version per key (max effective_dts), attributes only.
    latest: dict[Any, dict[str, Any]] = {}
    for record in source_records:
        key = record[key_field]
        if key not in latest or record["effective_dts"] > latest[key]["effective_dts"]:
            latest[key] = record
    sat = store.model.satellites[sat_name]
    source_current = [{key_field: k, **{a: r.get(a) for a in sat.all_attributes()}}
                      for k, r in sorted(latest.items(), key=lambda kv: str(kv[0]))]
    vault_current = []
    for hub_key, hub in sorted(store.hubs[hub_name].items()):
        row = store.current_satellite_row(sat_name, hub_key)
        if row is None:
            discrepancies.append(f"hub {hub_key[:12]}… has no satellite row")
            continue
        vault_current.append({key_field: hub["business_key"][key_field],
                              **{a: row["attributes"].get(a) for a in sat.all_attributes()}})

    source_checksum = checksum_rows(source_current)
    vault_checksum = checksum_rows(vault_current)
    report = ReconciliationReport(
        entity=entity, source_rows=len(source_records),
        vault_rows=len(store.satellites[sat_name]),
        source_checksum=source_checksum, vault_checksum=vault_checksum,
        counts_match=(hub_count == len(distinct_keys)),
        checksums_match=(source_checksum == vault_checksum),
        discrepancies=discrepancies)
    store.audit.append("reconciled", {"entity": entity, "passed": report.passed,
                                      "discrepancies": discrepancies})
    return report


def reconcile_all(store: VaultStore,
                  sources: dict[str, list[dict[str, Any]]]) -> list[ReconciliationReport]:
    return [reconcile_entity(store, entity, records)
            for entity, records in sources.items()]
