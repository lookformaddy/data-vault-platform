import pytest

fastapi = pytest.importorskip("fastapi")
pytest.importorskip("httpx")

from fastapi.testclient import TestClient

from datavault.service import app


@pytest.fixture()
def client():
    return TestClient(app)


def test_health(client):
    assert client.get("/health").json()["status"] == "ok"


def test_seed_then_summary(client):
    resp = client.post("/seed")
    assert resp.status_code == 200
    summary = client.get("/vault/summary").json()
    assert summary["hubs"]["hub_customer"] == 12
    assert summary["hubs"]["hub_order"] == 20
    assert summary["satellites"]["sat_customer"] == 15


def test_as_of_endpoint(client):
    client.post("/seed")
    resp = client.get("/as-of/customer",
                      params={"business_key": "CUST-1001", "as_of": "2026-01-31T00:00:00Z"})
    assert resp.status_code == 200
    assert resp.json()["city"] == "Springfield"
    resp = client.get("/as-of/customer",
                      params={"business_key": "CUST-1001", "as_of": "2026-03-31T00:00:00Z"})
    assert resp.json()["city"] == "Riverton"


def test_load_endpoint_rejects_bad_entity(client):
    resp = client.post("/load", json={"entity": "widget", "records": []})
    assert resp.status_code == 400


def test_load_endpoint_quarantine_gate(client):
    client.post("/seed")
    resp = client.post("/load", json={
        "entity": "customer",
        "records": [{"customer_id": "CUST-9999", "full_name": "Bad",
                     "email": "not-an-email", "city": "Nowhere",
                     "segment": "consumer", "loyalty_tier": "bronze",
                     "effective_dts": "2026-03-01T09:00:00Z"}],
        "batch_id": "api-bad", "load_dts": "2026-03-01T09:00:00Z"})
    assert resp.status_code == 422


def test_marts_and_audit_endpoints(client):
    client.post("/seed")
    marts = client.get("/marts", params={"as_of": "2026-03-31T00:00:00Z"}).json()
    assert marts["audit"]["fact_orders_rows"] == 20
    verify = client.get("/audit/verify").json()
    assert verify["ok"] is True
    assert verify["entries"] > 0
