"""Deterministic hashing for Data Vault 2.0 keys and change detection.

Business keys are never stored in the clear as join keys: every hub key and
link key is a SHA-256 hash of the (salted) business key, so the same source
key always maps to the same hash in every environment, and raw keys never
leak into downstream PIT/bridge/mart tables. Hash-diffs are SHA-256 over a
canonical JSON rendering of a satellite's descriptive attributes, so a
changed attribute — and only a changed attribute — produces a new row.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any, Mapping, Sequence

DEFAULT_SALT = "data-vault-platform-v1"


def canonical(value: Any) -> str:
    """Canonical JSON: sorted keys, tight separators, stable across runs."""
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


def hash_business_key(parts: Sequence[Any], salt: str = DEFAULT_SALT) -> str:
    """SHA-256 hub/link key from one or more business-key parts.

    Parts are joined with a delimiter that cannot appear in the canonical
    form, and the salt is prepended so keys are namespaced per deployment.
    An empty part list is a programmer error, not a hashable key.
    """
    if not parts:
        raise ValueError("hash_business_key requires at least one business-key part")
    joined = "|".join(canonical(p) for p in parts)
    return hashlib.sha256(f"{salt}||{joined}".encode("utf-8")).hexdigest()


def hash_diff(attributes: Mapping[str, Any], salt: str = DEFAULT_SALT) -> str:
    """SHA-256 change-detection hash over a satellite's descriptive attrs."""
    return hashlib.sha256(f"{salt}||diff||{canonical(dict(attributes))}".encode("utf-8")).hexdigest()


def checksum_rows(rows: Sequence[Mapping[str, Any]]) -> str:
    """Order-independent checksum of a set of rows (reconciliation)."""
    digests = sorted(canonical(dict(r)) for r in rows)
    return hashlib.sha256("\n".join(digests).encode("utf-8")).hexdigest()


def hash_chain(prev_hash: str, payload: str) -> str:
    """One link of the hash-chained audit log."""
    return hashlib.sha256(f"{prev_hash}|{payload}".encode("utf-8")).hexdigest()
