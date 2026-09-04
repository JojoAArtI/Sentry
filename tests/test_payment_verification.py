"""Tests for HMAC-SHA256 Razorpay Payment Signature Verification."""
import pytest
from fastapi.testclient import TestClient
from sentry.dashboard.app import app
from sentry.razorpay_client.executor import RazorpayExecutor


@pytest.fixture
def client():
    return TestClient(app)


def test_hmac_sha256_signature_generation_and_verification():
    """Executor correctly verifies HMAC-SHA256 signatures."""
    executor = RazorpayExecutor(key_id="rzp_test_123", key_secret="test_secret_abc")
    order_id = "order_test_9999"
    payment_id = "pay_test_8888"

    sig = executor.generate_test_signature(order_id, payment_id)
    assert executor.verify_payment_signature(order_id, payment_id, sig) is True


def test_tampered_payment_signature_fails():
    """Tampered signature must fail verification."""
    executor = RazorpayExecutor(key_id="rzp_test_123", key_secret="test_secret_abc")
    order_id = "order_test_9999"
    payment_id = "pay_test_8888"

    tampered_sig = "deadbeef" * 8
    assert executor.verify_payment_signature(order_id, payment_id, tampered_sig) is False


def test_api_payment_verify_endpoint_success(client):
    """POST /api/payment/verify successfully verifies and audits valid payment."""
    from sentry.dashboard.app import razorpay_executor

    order_id = "order_test_settle_01"
    payment_id = "pay_test_settle_01"
    sig = razorpay_executor.generate_test_signature(order_id, payment_id)

    res = client.post("/api/payment/verify", json={
        "order_id": order_id,
        "payment_id": payment_id,
        "signature": sig
    })
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "verified"
    assert data["signature_valid"] is True
    assert data["settled"] is True


def test_api_payment_verify_endpoint_failure(client):
    """POST /api/payment/verify rejects forged signature with HTTP 400."""
    res = client.post("/api/payment/verify", json={
        "order_id": "order_test_bad",
        "payment_id": "pay_test_bad",
        "signature": "invalid_forged_signature"
    })
    assert res.status_code == 400
    assert "INVALID_PAYMENT_SIGNATURE" in res.json()["detail"]
