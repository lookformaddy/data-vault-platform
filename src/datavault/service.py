"""FastAPI service: thin HTTP layer over the vault engine.

Endpoints are read-mostly and fail-closed: loads go through the same DQ
gate as the CLI, and every mutation is written to the hash-chained audit
log. The store is seeded on demand via ``POST /seed`` so the service
starts empty and explicit.
"""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from datavault.config import Settings, load_default_model
from datavault.demo import run_demo
from datavault.demo_data import SNAPSHOT_DATES, seed_all
from datavault.loader import VaultLoader
from datavault.marts import build_marts
from datavault.pit import as_of_view, build_pit
from datavault.store import VaultStore

settings = Settings.from_env()
model = load_default_model()
store = VaultStore(model, settings.hash_salt)
loader = VaultLoader(store, model, settings)

app = FastAPI(title="Data Vault Platform",
              description="Data Vault 2.0 modelling platform: hubs, links, "
                          "satellites, PIT/bridge tables and governed marts.",
              version="1.0.0")


class LoadRequest(BaseModel):
    entity: str
    records: list[dict[str, Any]]
    batch_id: str = "api-batch"
    load_dts: str = "2026-03-31T00:00:00Z"
    incremental: bool = False


@app.get("/health")
def health() -> dict[str, Any]:
    return {"status": "ok", "audit_entries": len(store.audit.entries)}


@app.get("/vault/summary")
def summary() -> dict[str, Any]:
    return store.summary()


@app.post("/seed")
def seed() -> dict[str, Any]:
    seed_data = seed_all()
    reports = {}
    for entity, records in seed_data.items():
        reports[entity] = loader.load_full(entity, records, "seed-batch",
                                           "2026-01-05T09:00:00Z").to_dict()
    return {"loads": reports, "summary": store.summary()}


@app.post("/load")
def load(req: LoadRequest) -> dict[str, Any]:
    try:
        report = loader.load(req.entity, req.records, req.batch_id,
                             req.load_dts, incremental=req.incremental)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if report.failed_gate:
        raise HTTPException(status_code=422, detail=report.to_dict())
    return report.to_dict()


@app.get("/pit/{satellite}")
def pit(satellite: str, hub_key: str, as_of: str) -> dict[str, Any]:
    if satellite not in store.model.satellites:
        raise HTTPException(status_code=404, detail=f"unknown satellite: {satellite}")
    row = store.as_of(satellite, hub_key, as_of)
    if row is None:
        raise HTTPException(status_code=404, detail="no satellite row in force at that date")
    return row


@app.get("/as-of/{entity}")
def as_of(entity: str, business_key: str, as_of: str) -> dict[str, Any]:
    """As-of attributes for a business key, e.g. entity=customer&business_key=CUST-1001."""
    hub_map = {"customer": ("hub_customer", "sat_customer", "customer_id"),
               "product": ("hub_product", "sat_product", "product_sku"),
               "order": ("hub_order", "sat_order", "order_id"),
               "shipment": ("hub_shipment", "sat_shipment", "shipment_id")}
    if entity not in hub_map:
        raise HTTPException(status_code=404, detail=f"unknown entity: {entity}")
    hub_name, sat_name, key_field = hub_map[entity]
    view = as_of_view(store, hub_name, {key_field: business_key}, sat_name, as_of)
    if view is None:
        raise HTTPException(status_code=404, detail="no row in force at that date")
    return view


@app.get("/marts")
def marts(as_of: str = "2026-03-31T00:00:00Z") -> dict[str, Any]:
    return build_marts(store, as_of)


@app.get("/pit-table/{satellite}")
def pit_table(satellite: str) -> dict[str, Any]:
    if satellite not in store.model.satellites:
        raise HTTPException(status_code=404, detail=f"unknown satellite: {satellite}")
    return {"satellite": satellite, "rows": build_pit(store, satellite, SNAPSHOT_DATES)}


@app.get("/audit/verify")
def audit_verify() -> dict[str, Any]:
    ok, broken = store.audit.verify()
    return {"ok": ok, "first_broken_seq": broken,
            "entries": len(store.audit.entries)}


@app.get("/quarantine")
def quarantine() -> dict[str, Any]:
    return {"rows": [q.to_dict() for q in store.quarantine]}


@app.get("/demo")
def demo() -> dict[str, Any]:
    return run_demo()
