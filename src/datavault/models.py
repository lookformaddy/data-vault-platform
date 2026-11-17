"""Shared value types: audit columns, load reports, quarantine records."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class LoadReport:
    entity: str
    batch_id: str
    staged: int = 0
    valid: int = 0
    quarantined: int = 0
    skipped_unchanged: int = 0
    hubs_inserted: int = 0
    links_inserted: int = 0
    satellite_rows_inserted: int = 0
    satellite_rows_corrected: int = 0
    late_arriving: int = 0
    quarantine_rate: float = 0.0
    failed_gate: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {k: getattr(self, k) for k in
                ("entity", "batch_id", "staged", "valid", "quarantined",
                 "skipped_unchanged", "hubs_inserted", "links_inserted",
                 "satellite_rows_inserted", "satellite_rows_corrected",
                 "late_arriving", "quarantine_rate", "failed_gate")}


@dataclass
class QuarantineRecord:
    entity: str
    record: dict[str, Any]
    reasons: list[str]
    batch_id: str
    load_dts: str

    def to_dict(self) -> dict[str, Any]:
        return {"entity": self.entity, "record": self.record,
                "reasons": self.reasons, "batch_id": self.batch_id,
                "load_dts": self.load_dts}


@dataclass
class ReconciliationReport:
    entity: str
    source_rows: int
    vault_rows: int
    source_checksum: str
    vault_checksum: str
    counts_match: bool = False
    checksums_match: bool = False
    discrepancies: list[str] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return self.counts_match and self.checksums_match and not self.discrepancies


@dataclass
class RetentionReport:
    cutoff_dts: str
    satellite_rows_archived: int = 0
    dry_run: bool = False
    per_satellite: dict[str, int] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {"cutoff_dts": self.cutoff_dts,
                "satellite_rows_archived": self.satellite_rows_archived,
                "dry_run": self.dry_run, "per_satellite": self.per_satellite}
