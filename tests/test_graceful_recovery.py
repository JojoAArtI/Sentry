"""Tests for Graceful Failure and Counter-Proposal Recovery Engine."""
import pytest
from datetime import datetime, timedelta, timezone
from fastapi.testclient import TestClient

from sentry.dashboard.app import app
from sentry.mandate.schema import SpendingMandate, TransactionProposal
from sentry.mandate.signer import MandateSigner
from sentry.policy.counter_proposal import GracefulRecoveryEngine
from sentry.policy.rules import PolicyVerdict, PolicyReasonCode


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def signer():
    return MandateSigner()


def test_graceful_recovery_engine_generates_bounded_counter_proposal(signer):
    """Engine converts 40-unit attack into explainable 1-unit counter-proposal."""
    future = datetime.now(timezone.utc) + timedelta(hours=2)
    mandate = SpendingMandate(
        mandate_id="mnd_recovery_test_01",
        issued_to_agent="buyer-agent-01",
        merchant_id="sentry-store",
        max_amount=1500,
        currency="INR",
        allowed_categories=["gifts"],
        max_quantity=2,
        expires_at=future,
        single_use=True
    )
    signed = signer.sign_mandate(mandate)

    # Attack proposal: 40 units of SKU-002 (₹48,000)
    failed_prop = TransactionProposal(
        proposal_id="prop_attack_test",
        sku="SKU-002",
        item_name="Silver Heart Necklace",
        unit_price=1200,
        quantity=40,
        total_amount=48000,
        currency="INR",
        category="gifts",
        merchant_id="sentry-store",
        idempotency_key="idemp_attack_test",
        mandate_id=signed.mandate_id
    )

    verdict = {
        "decision": PolicyVerdict.REJECTED.value,
        "reason_code": PolicyReasonCode.QUANTITY_EXCEEDS_LIMIT.value,
        "reason": "Requested quantity 40 exceeds mandate maximum 2."
    }

    engine = GracefulRecoveryEngine()
    counter_data = engine.generate_counter_proposal(failed_prop, signed, verdict)

    assert counter_data["recoverable"] is True
    assert counter_data["remediation_status"] == "COUNTER_PROPOSAL_OFFERED"
    assert counter_data["action"] == "AUTO_RECOVERABLE_WITHIN_MANDATE"

    remediation = counter_data["remediation"]
    assert remediation["suggested_quantity"] == 1
    assert remediation["suggested_total"] == 1200
    assert remediation["suggested_total"] <= mandate.max_amount

    counter_p = counter_data["counter_proposal"]
    assert counter_p["quantity"] == 1
    assert counter_p["total_amount"] == 1200


def test_api_counter_proposal_flow_endpoint(client):
    """POST /api/policy/counter-proposal executes complete attack -> rejection -> counter-proposal -> recovery loop."""
    res = client.post("/api/policy/counter-proposal")
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "gracefully_recovered"

    # Attack phase was strictly rejected with 0 Razorpay calls
    attack = data["attack_phase"]
    assert attack["verdict"]["decision"] == "REJECTED"
    assert attack["razorpay_called"] is False

    # Remediation offered valid counter proposal
    remediation = data["remediation_phase"]
    assert remediation["recoverable"] is True
    assert remediation["remediation"]["suggested_quantity"] == 1

    # Recovery phase authorized and created order
    recovery = data["recovery_phase"]
    assert recovery["verdict"]["decision"] == "APPROVED"
    assert recovery["razorpay_called"] is True
    assert recovery["order"]["amount"] == 120000  # 1200 INR in paise
