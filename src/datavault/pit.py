"""Point-in-time (PIT) and bridge tables.

A PIT table pre-computes, for each hub key and each snapshot date, which
satellite row was in force — so an as-of join becomes a single equality
join instead of a correlated range scan over history. A bridge table does
the same for a link: at each snapshot it resolves the link's hub keys
through their PIT rows, giving a ready-to-join fact grain.
"""

from __future__ import annotations

from typing import Any

from datavault.store import VaultStore


def build_pit(store: VaultStore, satellite: str,
              snapshot_dates: list[str]) -> list[dict[str, Any]]:
    """One PIT row per (hub key, snapshot) where a satellite row was in force."""
    rows: list[dict[str, Any]] = []
    for hub_key in sorted(store._sat_index[satellite]):
        for snapshot in snapshot_dates:
            current = store.as_of(satellite, hub_key, snapshot)
            if current is None:
                continue
            rows.append({
                "hub_key": hub_key, "satellite": satellite,
                "snapshot_dts": snapshot,
                "hash_diff": current["hash_diff"],
                "effective_dts": current["effective_dts"],
                "end_dts": current["end_dts"],
                "load_dts": current["load_dts"],
            })
    store.audit.append("pit_built", {"satellite": satellite,
                                     "snapshots": len(snapshot_dates), "rows": len(rows)})
    return rows


def build_bridge(store: VaultStore, link_name: str,
                 snapshot_dates: list[str]) -> list[dict[str, Any]]:
    """One bridge row per (link, snapshot): link keys + PIT-resolved sats.

    For each hub on the link, the satellite that describes it (if any) is
    resolved as-of the snapshot; hubs without a satellite resolve to None.
    """
    sat_by_hub = {sat.hub: name for name, sat in store.model.satellites.items()}
    rows: list[dict[str, Any]] = []
    for link_key, link in sorted(store.links[link_name].items()):
        for snapshot in snapshot_dates:
            resolved: dict[str, Any] = {}
            for hub_name, hub_key in link["hub_keys"].items():
                sat_name = sat_by_hub.get(hub_name)
                resolved[hub_name] = None
                if sat_name:
                    current = store.as_of(sat_name, hub_key, snapshot)
                    resolved[hub_name] = current["hash_diff"] if current else None
            rows.append({"link_key": link_key, "link": link_name,
                         "snapshot_dts": snapshot, "hub_keys": dict(link["hub_keys"]),
                         "satellite_hash_diffs": resolved})
    store.audit.append("bridge_built", {"link": link_name,
                                        "snapshots": len(snapshot_dates), "rows": len(rows)})
    return rows


def as_of_view(store: VaultStore, hub_name: str, business_key: dict[str, Any],
               satellite: str, as_of_dts: str) -> dict[str, Any] | None:
    """Convenience: as-of satellite attributes for a business key."""
    hub_key = store.hub_key(hub_name, business_key)
    row = store.as_of(satellite, hub_key, as_of_dts)
    return row["attributes"] if row else None
