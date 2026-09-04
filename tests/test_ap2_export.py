"""Tests for AP2 / UAP Protocol Compliance & W3C Verifiable Credential Export."""
import pytest
from datetime import datetime, timezone
from fastapi.testclient import TestClient
from sentry.dashboard.app import app
from sentry.mandate.schema import SpendingMandate
from sentry.mandate.signer import MandateSigner


@pytest.fixture
def client():
    return TestClient(app)


def test_spending_mandate_to_ap2_token():
    """to_ap2_token produces compliant JSON-LD format with Ed25519 proof."""
    signer = MandateSigner()
    mandate = SpendingMandate(
        mandate_id="mnd_ap2_test_01",
        issued_to_agent="buyer-agent-01",
        merchant_id="sentry-store",
        max_amount=1500,
        currency="INR",
        allowed_categories=["gifts", "flowers"],
        max_quantity=2,
        expires_at=datetime(2028, 1, 1, tzinfo=timezone.utc),
        single_use=True,
        autonomous_threshold=2000
    )
    signed = signer.sign_mandate(mandate)
    token = signed.to_ap2_token(public_key_hex=signer.public_key_hex)

    assert "@context" in token
    assert "https://www.w3.org/2018/credentials/v1" in token["@context"]
    assert "VerifiableCredential" in token["type"]
    assert "AgentSpendingMandate" in token["type"]
    assert token["credentialSubject"]["spendingLimit"]["amount"] == 1500
    assert token["credentialSubject"]["spendingLimit"]["currency"] == "INR"
    assert token["proof"]["type"] == "Ed25519Signature2020"
    assert token["proof"]["signatureValue"] == signed.signature


def test_api_mandate_export_ap2(client):
    """GET /api/mandate/export-ap2 returns 200 with valid AP2 JSON-LD."""
    res = client.get("/api/mandate/export-ap2")
    assert res.status_code == 200
    data = res.json()
    assert "@context" in data
    assert "credentialSubject" in data
    assert "proof" in data
    assert data["proof"]["type"] == "Ed25519Signature2020"
