"""Tests for Sentry Dashboard FastAPI endpoints."""
import pytest
from fastapi.testclient import TestClient
from sentry.dashboard.app import app


@pytest.fixture
def client():
    return TestClient(app)


def test_api_mandate(client):
    """GET /api/mandate returns active mandate with verified signature."""
    res = client.get("/api/mandate")
    assert res.status_code == 200
    data = res.json()
    assert "mandate" in data
    assert data["is_signature_valid"] is True
    assert data["mandate"]["merchant_id"] == "sentry-store"


def test_api_catalog(client):
    """GET /api/catalog returns products."""
    res = client.get("/api/catalog")
    assert res.status_code == 200
    products = res.json()
    assert len(products) >= 5
    skus = [p["sku"] for p in products]
    assert "SKU-001" in skus
    assert "SKU-002" in skus


def test_api_demo_run_legitimate(client):
    """POST /api/demo/run with legitimate scenario authorizes purchase."""
    client.post("/api/mandate/reset")
    res = client.post("/api/demo/run", json={"scenario": "legitimate"})
    assert res.status_code == 200
    data = res.json()
    assert data["output"]["result"]["decision"]["decision"] == "APPROVED"
    assert data["output"]["result"]["razorpay_called"] is True


def test_api_demo_run_prompt_injection(client):
    """POST /api/demo/run with attack_prompt_injection blocks purchase and asserts razorpay_called: False."""
    client.post("/api/mandate/reset")
    res = client.post("/api/demo/run", json={"scenario": "attack_prompt_injection"})
    assert res.status_code == 200
    data = res.json()
    assert data["output"]["result"]["decision"]["decision"] == "REJECTED"
    assert data["output"]["result"]["razorpay_called"] is False


def test_api_demo_run_category_attack(client):
    """POST /api/demo/run with attack_category blocks purchase."""
    client.post("/api/mandate/reset")
    res = client.post("/api/demo/run", json={"scenario": "attack_category"})
    assert res.status_code == 200
    data = res.json()
    assert data["output"]["result"]["decision"]["decision"] == "REJECTED"
    assert data["output"]["result"]["razorpay_called"] is False


def test_api_audit_trail(client):
    """GET /api/audit returns recorded events."""
    res = client.get("/api/audit")
    assert res.status_code == 200
    events = res.json()
    assert isinstance(events, list)
    assert len(events) > 0
