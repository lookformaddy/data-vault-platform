"""Retention / archival policy.

Only *closed* satellite rows (``end_dts`` set) whose end date is on or
before the cutoff are eligible: the currently-effective version of any
business key is never archived, so time-travel to the present always
works. Archival moves rows to ``store.archive`` (a real deployment would
write them to cold storage first); ``dry_run=True`` reports without moving.
"""

from __future__ import annotations

from datavault.models import RetentionReport
from datavault.store import VaultStore, parse_dts


def apply_retention(store: VaultStore, cutoff_dts: str,
                    dry_run: bool = False) -> RetentionReport:
    cutoff = parse_dts(cutoff_dts)
    report = RetentionReport(cutoff_dts=cutoff_dts, dry_run=dry_run)
    for sat_name, rows in list(store.satellites.items()):
        eligible = [r for r in rows
                    if r["end_dts"] is not None and parse_dts(r["end_dts"]) <= cutoff]
        report.per_satellite[sat_name] = len(eligible)
        report.satellite_rows_archived += len(eligible)
        if not dry_run and eligible:
            keep = [r for r in rows if r not in eligible]
            store.satellites[sat_name] = keep
            for hub_key, hub_rows in store._sat_index[sat_name].items():
                store._sat_index[sat_name][hub_key] = [r for r in hub_rows if r not in eligible]
            for row in eligible:
                store.archive.append({"satellite": sat_name, **row})
    store.audit.append("retention_applied", report.to_dict())
    return report
