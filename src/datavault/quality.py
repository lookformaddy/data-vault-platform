"""Fail-closed data-quality gates.

A record that fails any rule is quarantined with every reason attached —
never silently dropped, never partially loaded. The loader refuses the
batch (``failed_gate``) when the quarantine rate exceeds the configured
threshold, so a bad source feed cannot poison the vault.
"""

from __future__ import annotations

from typing import Any

from datavault.models import QuarantineRecord

ALLOWED_STATUSES = {"placed", "shipped", "delivered", "cancelled", "returned"}
ALLOWED_CHANNELS = {"web", "mobile", "store", "phone"}
ALLOWED_SEGMENTS = {"consumer", "business", "premium"}
ALLOWED_CARRIERS = {"SwiftParcel", "NorthStar Freight", "Harbor Logistics"}
ALLOWED_SERVICE_LEVELS = {"standard", "express", "overnight"}

# entity -> {field: (kind, detail)}; kinds: required, email, positive, nonneg, int>=1, enum
RULES: dict[str, dict[str, tuple[str, Any]]] = {
    "customer": {
        "customer_id": ("required", None), "full_name": ("required", None),
        "email": ("email", None), "city": ("required", None),
        "segment": ("enum", ALLOWED_SEGMENTS),
        "loyalty_tier": ("required", None),
    },
    "product": {
        "product_sku": ("required", None), "product_name": ("required", None),
        "category": ("required", None), "price": ("positive", None),
        "currency": ("required", None),
    },
    "order": {
        "order_id": ("required", None), "customer_id": ("required", None),
        "product_sku": ("required", None), "status": ("enum", ALLOWED_STATUSES),
        "total_amount": ("nonneg", None), "currency": ("required", None),
        "channel": ("enum", ALLOWED_CHANNELS), "quantity": ("int_ge_1", None),
    },
    "shipment": {
        "shipment_id": ("required", None), "order_id": ("required", None),
        "carrier": ("enum", ALLOWED_CARRIERS), "status": ("enum", ALLOWED_STATUSES),
        "service_level": ("enum", ALLOWED_SERVICE_LEVELS),
    },
}


def validate_record(entity: str, record: dict[str, Any]) -> list[str]:
    """Return the list of rule violations for one staged record."""
    reasons: list[str] = []
    for field_name, (kind, detail) in RULES.get(entity, {}).items():
        value = record.get(field_name)
        if kind == "required":
            if value is None or (isinstance(value, str) and not value.strip()):
                reasons.append(f"{field_name} is required")
        elif kind == "email":
            if not isinstance(value, str) or "@" not in value or "." not in value.split("@")[-1]:
                reasons.append(f"{field_name} is not a valid email")
        elif kind == "positive":
            if not isinstance(value, (int, float)) or isinstance(value, bool) or value <= 0:
                reasons.append(f"{field_name} must be > 0")
        elif kind == "nonneg":
            if not isinstance(value, (int, float)) or isinstance(value, bool) or value < 0:
                reasons.append(f"{field_name} must be >= 0")
        elif kind == "int_ge_1":
            if not isinstance(value, int) or isinstance(value, bool) or value < 1:
                reasons.append(f"{field_name} must be an integer >= 1")
        elif kind == "enum":
            if value not in detail:
                reasons.append(f"{field_name} must be one of {sorted(detail)}")
    if "effective_dts" not in record or not record.get("effective_dts"):
        reasons.append("effective_dts is required")
    return reasons


def validate_batch(entity: str, records: list[dict[str, Any]],
                   batch_id: str, load_dts: str) -> tuple[list[dict[str, Any]], list[QuarantineRecord]]:
    """Split a staged batch into (valid, quarantined) records."""
    valid: list[dict[str, Any]] = []
    quarantined: list[QuarantineRecord] = []
    for record in records:
        reasons = validate_record(entity, record)
        if reasons:
            quarantined.append(QuarantineRecord(entity, dict(record), reasons,
                                                batch_id, load_dts))
        else:
            valid.append(record)
    return valid, quarantined
