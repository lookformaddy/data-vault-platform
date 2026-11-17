"""Hash-chained audit log.

Every load batch, quarantine decision, PIT build, mart build and retention
run appends one entry. Each entry hashes the previous entry's hash, so
deleting or editing any entry breaks the chain and :meth:`verify` reports
the first broken sequence number. The log is the vault's tamper evidence.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from datavault.hashing import canonical, hash_chain

GENESIS = "0" * 64


@dataclass
class AuditEntry:
    seq: int
    event_type: str
    payload: dict[str, Any]
    prev_hash: str
    entry_hash: str


class AuditLog:
    def __init__(self) -> None:
        self.entries: list[AuditEntry] = []

    def append(self, event_type: str, payload: dict[str, Any]) -> AuditEntry:
        prev = self.entries[-1].entry_hash if self.entries else GENESIS
        entry_hash = hash_chain(prev, canonical({"event": event_type, "payload": payload}))
        entry = AuditEntry(seq=len(self.entries) + 1, event_type=event_type,
                           payload=dict(payload), prev_hash=prev, entry_hash=entry_hash)
        self.entries.append(entry)
        return entry

    def verify(self) -> tuple[bool, int | None]:
        """Return (ok, first_broken_seq or None)."""
        prev = GENESIS
        for entry in self.entries:
            expected = hash_chain(prev, canonical({"event": entry.event_type,
                                                   "payload": entry.payload}))
            if entry.prev_hash != prev or entry.entry_hash != expected:
                return False, entry.seq
            prev = entry.entry_hash
        return True, None

    def to_dicts(self) -> list[dict[str, Any]]:
        return [{"seq": e.seq, "event_type": e.event_type, "payload": e.payload,
                 "prev_hash": e.prev_hash, "entry_hash": e.entry_hash}
                for e in self.entries]
