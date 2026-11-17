"""Vault loaders: full and incremental, with hash-diff change detection.

Pipeline per record: stage -> DQ gate (fail-closed) -> hub upsert -> link
upsert -> satellite insert only when the hash-diff changed. Incremental
loads skip source records whose checksum was already processed, so a
replayed file is a no-op instead of a duplicate. A record whose
``effective_dts`` precedes the current open satellite row is late-arriving:
it is still inserted in timeline order (see the store) and counted, never
rejected — late data is a normal enterprise reality, not an error.
"""

from __future__ import annotations

from typing import Any

from datavault.config import Settings, VaultModel
from datavault.hashing import canonical, checksum_rows
from datavault.models import LoadReport
from datavault.quality import validate_batch
from datavault.store import VaultStore, parse_dts

# entity -> (hub, satellite, link specs). A link spec maps
# link name -> (hub field on this record, hub name) pairs are resolved
# from the record's own fields plus the hub keys already created.
ENTITY_MAP: dict[str, dict[str, Any]] = {
    "customer": {"hub": "hub_customer", "satellite": "sat_customer", "links": []},
    "product": {"hub": "hub_product", "satellite": "sat_product", "links": []},
    "order": {"hub": "hub_order", "satellite": "sat_order", "links": [
        ("link_order_customer", "hub_order", "hub_customer", "customer_id"),
        ("link_order_product", "hub_order", "hub_product", "product_sku"),
    ]},
    "shipment": {"hub": "hub_shipment", "satellite": "sat_shipment", "links": [
        ("link_shipment_order", "hub_shipment", "hub_order", "order_id"),
    ]},
}


class VaultLoader:
    def __init__(self, store: VaultStore, model: VaultModel,
                 settings: Settings | None = None) -> None:
        self.store = store
        self.model = model
        self.settings = settings or Settings()

    def load(self, entity: str, records: list[dict[str, Any]], batch_id: str,
             load_dts: str, incremental: bool = False,
             record_source: str | None = None) -> LoadReport:
        """Load one entity batch. ``incremental=True`` skips already-seen records."""
        if entity not in ENTITY_MAP:
            raise ValueError(f"unknown entity: {entity}")
        source = record_source or self.settings.record_source
        report = LoadReport(entity=entity, batch_id=batch_id, staged=len(records))
        self.store.staging.extend({"entity": entity, **r} for r in records)

        # Source-record checksums are tracked on every load, so an
        # incremental replay of an already-loaded file is a checksum no-op.
        seen = self.store.processed_checksums.setdefault(entity, set())
        todo = records
        if incremental:
            todo = []
            for record in records:
                digest = checksum_rows([record])
                if digest in seen:
                    report.skipped_unchanged += 1
                else:
                    seen.add(digest)
                    todo.append(record)
        else:
            for record in records:
                seen.add(checksum_rows([record]))

        valid, quarantined = validate_batch(entity, todo, batch_id, load_dts)
        report.valid = len(valid)
        report.quarantined = len(quarantined)
        self.store.quarantine.extend(quarantined)
        report.quarantine_rate = (report.quarantined / report.staged) if report.staged else 0.0
        if report.quarantine_rate > self.settings.max_quarantine_rate:
            report.failed_gate = True
            self.store.audit.append("load_gate_failed", report.to_dict())
            return report

        spec = ENTITY_MAP[entity]
        for record in valid:
            hub_key, inserted = self.store.ensure_hub(
                spec["hub"], record, load_dts, batch_id, source)
            report.hubs_inserted += int(inserted)
            sat_name = spec["satellite"]
            sat = self.model.satellites[sat_name]
            attrs = {a: record.get(a) for a in sat.all_attributes()}
            current = self.store.current_satellite_row(sat_name, hub_key)
            effective = record["effective_dts"]
            if current is not None and parse_dts(effective) < parse_dts(current["effective_dts"]):
                report.late_arriving += 1
            outcome = self.store.add_satellite_row(
                sat_name, hub_key, attrs, effective, load_dts, batch_id, source)
            if outcome == "inserted":
                report.satellite_rows_inserted += 1
            elif outcome == "corrected":
                report.satellite_rows_corrected += 1
            else:
                report.skipped_unchanged += 1
            # Links resolve the *other* hub from the record's business key.
            for link_name, own_hub, other_hub, other_field in spec["links"]:
                other_key = self.store.hub_key(other_hub, {other_field: record[other_field]})
                # The other hub must exist; if it does not, create a stub hub
                # row so the relationship is preserved and auditable.
                if other_key not in self.store.hubs[other_hub]:
                    self.store.ensure_hub(other_hub, {other_field: record[other_field]},
                                          load_dts, batch_id, source)
                    report.hubs_inserted += 1
                hub_keys = {own_hub: hub_key, other_hub: other_key}
                _, link_inserted = self.store.ensure_link(
                    link_name, hub_keys, load_dts, batch_id, source)
                report.links_inserted += int(link_inserted)

        self.store.audit.append("load_completed", report.to_dict())
        return report

    def load_full(self, entity: str, records: list[dict[str, Any]],
                  batch_id: str, load_dts: str) -> LoadReport:
        return self.load(entity, records, batch_id, load_dts, incremental=False)

    def load_incremental(self, entity: str, records: list[dict[str, Any]],
                         batch_id: str, load_dts: str) -> LoadReport:
        return self.load(entity, records, batch_id, load_dts, incremental=True)
