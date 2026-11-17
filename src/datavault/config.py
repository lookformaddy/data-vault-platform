"""Declarative vault model config and runtime settings.

The vault model is data, not code: hubs, links and satellites are declared
once (see ``DEFAULT_MODEL`` / ``load_model_config``) and every loader, PIT
builder and mart reads the same declaration, so adding a satellite is a
config change, not a code change. Schema evolution is a first-class
operation: ``add_satellite_attribute`` registers a new attribute with a
default for older rows instead of rewriting history.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class Settings:
    """Runtime settings; every value overridable from the environment."""

    hash_salt: str = "data-vault-platform-v1"
    record_source: str = "synthetic-retail"
    retention_days: int = 365
    max_quarantine_rate: float = 0.05
    host: str = "0.0.0.0"
    port: int = 8000

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            hash_salt=os.environ.get("DVP_HASH_SALT", "data-vault-platform-v1"),
            record_source=os.environ.get("DVP_RECORD_SOURCE", "synthetic-retail"),
            retention_days=int(os.environ.get("DVP_RETENTION_DAYS", "365")),
            max_quarantine_rate=float(os.environ.get("DVP_MAX_QUARANTINE_RATE", "0.05")),
            host=os.environ.get("DVP_HOST", "0.0.0.0"),
            port=int(os.environ.get("DVP_PORT", "8000")),
        )


@dataclass
class HubDef:
    name: str
    business_key_fields: list[str]
    source: str = "synthetic-retail"


@dataclass
class SatelliteDef:
    name: str
    hub: str
    attributes: list[str]
    # Attributes added later via schema evolution, with their backfill default.
    evolved_attributes: dict[str, Any] = field(default_factory=dict)

    def all_attributes(self) -> list[str]:
        attrs = list(self.attributes)
        for name in self.evolved_attributes:
            if name not in attrs:
                attrs.append(name)
        return attrs


@dataclass
class LinkDef:
    name: str
    hubs: list[str]  # hub names, in key order
    source: str = "synthetic-retail"


@dataclass
class VaultModel:
    hubs: dict[str, HubDef] = field(default_factory=dict)
    satellites: dict[str, SatelliteDef] = field(default_factory=dict)
    links: dict[str, LinkDef] = field(default_factory=dict)

    def add_satellite_attribute(self, satellite: str, name: str, default: Any) -> None:
        """Schema evolution: register a new satellite attribute.

        History is never rewritten: existing rows keep their hash-diff and
        gain the default only when read back through the model (see
        :func:`datavault.store.VaultStore.satellite_row_view`).
        """
        if satellite not in self.satellites:
            raise KeyError(f"unknown satellite: {satellite}")
        sat = self.satellites[satellite]
        if name in sat.all_attributes():
            raise ValueError(f"attribute {name!r} already exists on {satellite}")
        sat.evolved_attributes[name] = default

    def to_dict(self) -> dict[str, Any]:
        return {
            "hubs": {k: {"business_key_fields": v.business_key_fields, "source": v.source}
                     for k, v in self.hubs.items()},
            "satellites": {k: {"hub": v.hub, "attributes": v.attributes,
                               "evolved_attributes": v.evolved_attributes}
                           for k, v in self.satellites.items()},
            "links": {k: {"hubs": v.hubs, "source": v.source}
                      for k, v in self.links.items()},
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "VaultModel":
        model = cls()
        for name, spec in data.get("hubs", {}).items():
            model.hubs[name] = HubDef(name, list(spec["business_key_fields"]),
                                      spec.get("source", "synthetic-retail"))
        for name, spec in data.get("satellites", {}).items():
            sat = SatelliteDef(name, spec["hub"], list(spec["attributes"]))
            sat.evolved_attributes = dict(spec.get("evolved_attributes", {}))
            model.satellites[name] = sat
        for name, spec in data.get("links", {}).items():
            model.links[name] = LinkDef(name, list(spec["hubs"]),
                                        spec.get("source", "synthetic-retail"))
        return model


def load_default_model() -> VaultModel:
    """Synthetic retail vault: customers, products, orders, shipments."""
    model = VaultModel()
    model.hubs["hub_customer"] = HubDef("hub_customer", ["customer_id"])
    model.hubs["hub_product"] = HubDef("hub_product", ["product_sku"])
    model.hubs["hub_order"] = HubDef("hub_order", ["order_id"])
    model.hubs["hub_shipment"] = HubDef("hub_shipment", ["shipment_id"])

    model.satellites["sat_customer"] = SatelliteDef(
        "sat_customer", "hub_customer",
        ["full_name", "email", "city", "segment", "loyalty_tier"])
    model.satellites["sat_product"] = SatelliteDef(
        "sat_product", "hub_product",
        ["product_name", "category", "price", "currency"])
    model.satellites["sat_order"] = SatelliteDef(
        "sat_order", "hub_order",
        ["status", "total_amount", "currency", "channel", "quantity"])
    model.satellites["sat_shipment"] = SatelliteDef(
        "sat_shipment", "hub_shipment",
        ["carrier", "status", "service_level"])

    model.links["link_order_customer"] = LinkDef(
        "link_order_customer", ["hub_order", "hub_customer"])
    model.links["link_order_product"] = LinkDef(
        "link_order_product", ["hub_order", "hub_product"])
    model.links["link_shipment_order"] = LinkDef(
        "link_shipment_order", ["hub_shipment", "hub_order"])
    return model


def load_model_config(path: str | Path) -> VaultModel:
    """Load a vault model declaration from a JSON file."""
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    return VaultModel.from_dict(data)
