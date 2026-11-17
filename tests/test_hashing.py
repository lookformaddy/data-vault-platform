import pytest

from datavault.hashing import (
    canonical,
    checksum_rows,
    hash_business_key,
    hash_chain,
    hash_diff,
)


def test_business_key_hash_is_deterministic_and_salted():
    a = hash_business_key(["CUST-1001"])
    assert a == hash_business_key(["CUST-1001"])
    assert a != hash_business_key(["CUST-1002"])
    assert a != hash_business_key(["CUST-1001"], salt="other-salt")
    assert len(a) == 64  # SHA-256 hex


def test_business_key_hash_is_order_sensitive_for_links():
    assert hash_business_key(["A", "B"]) != hash_business_key(["B", "A"])


def test_empty_business_key_rejected():
    with pytest.raises(ValueError):
        hash_business_key([])


def test_hash_diff_changes_only_when_attributes_change():
    attrs = {"city": "Springfield", "tier": "gold"}
    assert hash_diff(attrs) == hash_diff(dict(attrs))
    assert hash_diff(attrs) != hash_diff({**attrs, "city": "Riverton"})
    # Key order must not matter.
    assert hash_diff({"a": 1, "b": 2}) == hash_diff({"b": 2, "a": 1})


def test_canonical_is_stable():
    assert canonical({"b": [1, 2], "a": {"x": 1}}) == canonical({"a": {"x": 1}, "b": [1, 2]})


def test_checksum_rows_is_order_independent():
    rows = [{"id": 1, "v": "a"}, {"id": 2, "v": "b"}]
    assert checksum_rows(rows) == checksum_rows(list(reversed(rows)))
    assert checksum_rows(rows) != checksum_rows([{"id": 1, "v": "a"}])


def test_hash_chain_links_entries():
    h1 = hash_chain("0" * 64, "first")
    h2 = hash_chain(h1, "second")
    assert h1 != h2
    assert hash_chain(h1, "second") == h2
