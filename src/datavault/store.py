"""In-memory vault store: hubs, links, satellites, staging, quarantine.

Every row carries the Data Vault 2.0 audit columns (``load_dts``,
``load_source``, ``record_source``, ``load_batch_id``). Satellite rows are
end-dated: the open row has ``end_dts`` ``None``; inserting a new version
closes the previous one. Late-arriving rows (``effective_dts`` earlier than
the current open row) are inserted in timeline order and the neighbours'
``end_dts`` values are repaired, so point-in-time reads stay correct
without rewriting history — the row is new, its neighbours only gain an
``end_dts`` they should always have had.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from datavault.audit import AuditLog
from datavault.config import VaultModel
from datavault.hashing import hash_business_key, hash_diff
from datavault.models import QuarantineRecord


def parse_dts(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


class VaultStore:
    def __init__(self, model: VaultModel, salt: str) -> None:
        self.model = model
        self.salt = salt
        # hub name -> hub_key -> row
        self.hubs: dict[str, dict[str, dict[str, Any]]] = {n: {} for n in model.hubs}
        # link name -> link_key -> row
        self.links: dict[str, dict[str, dict[str, Any]]] = {n: {} for n in model.links}
        # satellite name -> rows sorted by (effective_dts, load_dts)
        self.satellites: dict[str, list[dict[str, Any]]] = {n: [] for n in model.satellites}
        self.staging: list[dict[str, Any]] = []
        self.quarantine: list[QuarantineRecord] = []
        self.archive: list[dict[str, Any]] = []
        self.audit = AuditLog()
        # entity -> set of source-record checksums already loaded (incremental)
        self.processed_checksums: dict[str, set[str]] = {}
        # satellite name -> hub_key -> ordered rows (cache rebuilt on insert)
        self._sat_index: dict[str, dict[str, list[dict[str, Any]]]] = {
            n: {} for n in model.satellites}

    # -- hubs -----------------------------------------------------------
    def hub_key(self, hub_name: str, record: dict[str, Any]) -> str:
        hub = self.model.hubs[hub_name]
        parts = [record[f] for f in hub.business_key_fields]
        return hash_business_key(parts, self.salt)

    def ensure_hub(self, hub_name: str, record: dict[str, Any],
                   load_dts: str, batch_id: str,
                   record_source: str) -> tuple[str, bool]:
        key = self.hub_key(hub_name, record)
        if key in self.hubs[hub_name]:
            return key, False
        hub = self.model.hubs[hub_name]
        self.hubs[hub_name][key] = {
            "hub_key": key,
            "business_key": {f: record[f] for f in hub.business_key_fields},
            "load_dts": load_dts, "load_source": record_source,
            "record_source": record_source, "load_batch_id": batch_id,
        }
        return key, True

    # -- links ----------------------------------------------------------
    def ensure_link(self, link_name: str, hub_keys: dict[str, str],
                    load_dts: str, batch_id: str, record_source: str) -> tuple[str, bool]:
        link = self.model.links[link_name]
        parts = [hub_keys[h] for h in link.hubs]
        key = hash_business_key(parts, self.salt)
        if key in self.links[link_name]:
            return key, False
        self.links[link_name][key] = {
            "link_key": key, "hub_keys": dict(hub_keys),
            "load_dts": load_dts, "load_source": record_source,
            "record_source": record_source, "load_batch_id": batch_id,
        }
        return key, True

    # -- satellites -----------------------------------------------------
    def satellite_rows(self, satellite: str, hub_key: str) -> list[dict[str, Any]]:
        return list(self._sat_index[satellite].get(hub_key, []))

    def current_satellite_row(self, satellite: str,
                              hub_key: str) -> dict[str, Any] | None:
        rows = self.satellite_rows(satellite, hub_key)
        return rows[-1] if rows else None

    def add_satellite_row(self, satellite: str, hub_key: str,
                          attributes: dict[str, Any], effective_dts: str,
                          load_dts: str, batch_id: str,
                          record_source: str) -> str:
        """Insert a satellite version. Returns 'inserted' | 'corrected' | 'duplicate'.

        * duplicate — same effective date and same hash-diff already stored.
        * corrected — same effective date, different hash-diff: the row is a
          correction of what was believed true at that date; replace in place.
        * inserted — new version; neighbours are re-end-dated. A row whose
          effective date precedes the current open row is late-arriving.
        """
        sat = self.model.satellites[satellite]
        attrs = {a: attributes.get(a) for a in sat.all_attributes()}
        digest = hash_diff(attrs, self.salt)
        rows = self._sat_index[satellite].setdefault(hub_key, [])
        for row in rows:
            if row["effective_dts"] == effective_dts:
                if row["hash_diff"] == digest:
                    return "duplicate"
                row.update({"attributes": dict(attrs), "hash_diff": digest,
                            "load_dts": load_dts, "load_batch_id": batch_id,
                            "record_source": record_source})
                return "corrected"
        new_row = {
            "hub_key": hub_key, "attributes": dict(attrs), "hash_diff": digest,
            "effective_dts": effective_dts, "load_dts": load_dts,
            "end_dts": None, "load_source": record_source,
            "record_source": record_source, "load_batch_id": batch_id,
        }
        rows.append(new_row)
        rows.sort(key=lambda r: (parse_dts(r["effective_dts"]), parse_dts(r["load_dts"])))
        for i, row in enumerate(rows):
            row["end_dts"] = rows[i + 1]["effective_dts"] if i + 1 < len(rows) else None
        self.satellites[satellite] = [
            r for rs in self._sat_index[satellite].values() for r in rs]
        return "inserted"

    def satellite_row_view(self, satellite: str, row: dict[str, Any]) -> dict[str, Any]:
        """Row as a reader sees it: evolved attributes backfilled with defaults."""
        sat = self.model.satellites[satellite]
        attrs = dict(row["attributes"])
        for name, default in sat.evolved_attributes.items():
            attrs.setdefault(name, default)
        return {**row, "attributes": attrs}

    # -- point-in-time --------------------------------------------------
    def as_of(self, satellite: str, hub_key: str,
              as_of_dts: str) -> dict[str, Any] | None:
        """Satellite row in force at ``as_of_dts`` (effective <= as_of < end)."""
        moment = parse_dts(as_of_dts)
        for row in self.satellite_rows(satellite, hub_key):
            start = parse_dts(row["effective_dts"])
            end = parse_dts(row["end_dts"]) if row["end_dts"] else None
            if start <= moment and (end is None or moment < end):
                return self.satellite_row_view(satellite, row)
        return None

    # -- summary --------------------------------------------------------
    def summary(self) -> dict[str, Any]:
        return {
            "hubs": {n: len(rows) for n, rows in self.hubs.items()},
            "links": {n: len(rows) for n, rows in self.links.items()},
            "satellites": {n: len(rows) for n, rows in self.satellites.items()},
            "staging_rows": len(self.staging),
            "quarantined_rows": len(self.quarantine),
            "archived_rows": len(self.archive),
            "audit_entries": len(self.audit.entries),
        }
