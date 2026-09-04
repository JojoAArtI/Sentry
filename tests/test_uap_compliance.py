"""Tests for NPCI Unified Authorization Protocol (UAP) 1.0-Draft Compliance."""
import pytest
from datetime import datetime, timedelta, timezone
from fastapi.testclient import TestClient

from sentry.dashboard.app import app
from sentry.mandate.schema import SpendingMandate
from sentry.mandate.signer import MandateSigner
from sentry.mandate.uap import to_uap_credential, verify_uap_credential


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def signer():
    return MandateSigner()


def test_uap_credential_serialization_and_verification(signer):
    """Mandate serializes into standard NPCI UAP 1.0 credential with Ed25519 proof."""
    future = datetime.now(timezone.utc) + timedelta(hours=4)
    mandate = SpendingMandate(
        mandate_id="mnd_uap_test_99",
        issued_to_agent="buyer-agent-01",
        merchant_id="sentry-store",
        max_amount=1500,
        currency="INR",
        allowed_categories=["gifts", "flowers"],
        max_quantity=2,
        expires_at=future,
        single_use=True,
        autonomous_threshold=2000
    )
    signed = signer.sign_mandate(mandate)

    cred = to_uap_credential(signed, public_key_hex=signer.public_key_hex)

    # Validate UAP structural fields
    assert cred["uap_version"] == "1.0-draft"
    assert cred["settlement_network"] == "razorpay"
    assert cred["mandate_urn"] == f"urn:npci:uap:mandate:{signed.mandate_id}"
    assert "https://npci.org.in/uap/v1" in cred["@context"]
    assert "NPCIUnifiedAuthorizationMandate" in cred["type"]

    # Validate budget ceiling
    budget = cred["budget_ceiling"]
    assert budget["max_amount"] == 1500
    assert budget["currency"] == "INR"
    assert budget["single_use"] is True

    # Validate cryptographic proof
    proof = cred["proof"]
    assert proof["type"] == "Ed25519Signature2020"
    assert proof["publicKeyHex"] == signer.public_key_hex
    assert proof["signatureValue"] == signed.signature

    # Verify structural verification helper
    assert verify_uap_credential(cred) is True


def test_api_uap_credential_endpoints(client):
    """GET /api/uap/credential and /api/uap/download return valid NPCI UAP payload."""
    res = client.get("/api/uap/credential")
    assert res.status_code == 200
    data = res.json()
    assert data["uap_version"] == "1.0-draft"
    assert data["settlement_network"] == "razorpay"
    assert verify_uap_credential(data) is True

    down_res = client.get("/api/uap/download")
    assert down_res.status_code == 200
    assert "attachment; filename=" in down_res.headers.get("content-disposition", "")
    assert down_res.json()["uap_version"] == "1.0-draft"
