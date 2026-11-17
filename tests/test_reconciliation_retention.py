from datavault.audit import AuditLog
from datavault.reconciliation import reconcile_all, reconcile_entity
from datavault.retention import apply_retention


def test_reconciliation_passes_on_clean_load(loaded, seed):
    reports = reconcile_all(loaded, seed)
    assert len(reports) == 4
    assert all(r.passed for r in reports)
    customers = next(r for r in reports if r.entity == "customer")
    assert customers.source_rows == 15 and customers.vault_rows == 15


def test_reconciliation_detects_missing_hub(loaded, seed):
    # Remove one hub row: counts and checksums must both disagree.
    store = loaded
    key = next(iter(store.hubs["hub_product"]))
    del store.hubs["hub_product"][key]
    report = reconcile_entity(store, "product", seed["product"])
    assert not report.passed
    assert report.discrepancies


def test_reconciliation_detects_tampered_satellite(loaded, seed):
    store = loaded
    hub_key = next(iter(store.hubs["hub_product"]))
    row = store.current_satellite_row("sat_product", hub_key)
    assert row is not None
    row["attributes"] = {**row["attributes"], "price": 0.01}
    report = reconcile_entity(store, "product", seed["product"])
    assert not report.passed
    assert not report.checksums_match


def test_retention_dry_run_changes_nothing(loaded):
    before = len(loaded.satellites["sat_customer"])
    # v1 rows for the 3 changed customers ended Feb 10 / Feb 18.
    report = apply_retention(loaded, "2026-02-28T00:00:00Z", dry_run=True)
    assert report.dry_run is True
    # 3 closed customer v1 rows + 1 product v1 row + 20 superseded "placed" order rows.
    assert report.per_satellite["sat_customer"] == 3
    assert report.satellite_rows_archived == 24
    assert len(loaded.satellites["sat_customer"]) == before
    assert len(loaded.archive) == 0


def test_retention_archives_only_closed_rows(loaded):
    report = apply_retention(loaded, "2026-02-28T00:00:00Z", dry_run=False)
    assert report.satellite_rows_archived == 24
    assert len(loaded.archive) == 24
    # Current (open) rows are never archived: all 12 customers still readable.
    from datavault.pit import as_of_view
    for cid in [f"CUST-100{i}" for i in range(1, 10)] + ["CUST-1010", "CUST-1011", "CUST-1012"]:
        assert as_of_view(loaded, "hub_customer", {"customer_id": cid},
                          "sat_customer", "2026-03-31T00:00:00Z") is not None


def test_retention_with_early_cutoff_archives_nothing(loaded):
    report = apply_retention(loaded, "2026-01-01T00:00:00Z", dry_run=True)
    assert report.satellite_rows_archived == 0


def test_audit_log_verifies_and_detects_tampering():
    log = AuditLog()
    log.append("load_completed", {"entity": "customer", "rows": 12})
    log.append("pit_built", {"rows": 36})
    ok, broken = log.verify()
    assert ok is True and broken is None
    log.entries[0].payload["rows"] = 999  # tamper
    ok, broken = log.verify()
    assert ok is False and broken == 1


def test_audit_log_is_hash_chained():
    log = AuditLog()
    first = log.append("a", {"x": 1})
    second = log.append("b", {"x": 2})
    assert second.prev_hash == first.entry_hash
    assert first.prev_hash == "0" * 64
