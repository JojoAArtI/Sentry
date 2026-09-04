"""CRITICAL INVARIANT TEST: The Security Boundary.

Guarantees that ANY rejected, invalid, or tampered transaction NEVER calls the Razorpay order creation API.
Asserts razorpay.create_order.call_count == 0 across all adversarial scenarios.
"""
import pytest
from unittest.mock import MagicMock
from sentry.mandate.schema import TransactionProposal
from sentry.policy.rules import PolicyVerdict
from sentry.razorpay_client.executor import SecurityViolationError, RazorpayExecutor


def test_rejected_amount_never_calls_razorpay(storefront_service, mock_razorpay_executor, valid_mandate):
    """Adversarial quantity/amount explosion (e.g. 40 units for ₹48,000) MUST NOT call Razorpay."""
    proposal = TransactionProposal(
        proposal_id="prop_boundary_001",
        sku="SKU-002",
        item_name="Silver Heart Necklace",
        unit_price=1200,
        quantity=40,
        total_amount=48000,
        currency="INR",
        category="gifts",
        merchant_id="sentry-store",
        idempotency_key="idemp_boundary_001",
        mandate_id=valid_mandate.mandate_id
    )

    res = storefront_service.propose_purchase(valid_mandate, proposal)
    assert res["decision"]["decision"] == PolicyVerdict.REJECTED.value
    assert res["razorpay_called"] is False

    # THE CORE INVARIANT
    assert mock_razorpay_executor.create_order.call_count == 0


def test_rejected_category_never_calls_razorpay(storefront_service, mock_razorpay_executor, valid_mandate):
    """Category escalation (e.g. electronics) MUST NOT call Razorpay."""
    proposal = TransactionProposal(
        proposal_id="prop_boundary_002",
        sku="SKU-004",
        item_name="Premium Wireless Headphones",
        unit_price=4800,
        quantity=1,
        total_amount=4800,
        currency="INR",
        category="electronics",
        merchant_id="sentry-store",
        idempotency_key="idemp_boundary_002",
        mandate_id=valid_mandate.mandate_id
    )

    res = storefront_service.propose_purchase(valid_mandate, proposal)
    assert res["decision"]["decision"] == PolicyVerdict.REJECTED.value
    assert res["razorpay_called"] is False

    # THE CORE INVARIANT
    assert mock_razorpay_executor.create_order.call_count == 0


def test_expired_mandate_never_calls_razorpay(storefront_service, mock_razorpay_executor, expired_mandate):
    """Expired mandate MUST NOT call Razorpay."""
    proposal = TransactionProposal(
        proposal_id="prop_boundary_003",
        sku="SKU-001",
        item_name="Birthday Flowers",
        unit_price=700,
        quantity=1,
        total_amount=700,
        currency="INR",
        category="flowers",
        merchant_id="sentry-store",
        idempotency_key="idemp_boundary_003",
        mandate_id=expired_mandate.mandate_id
    )

    res = storefront_service.propose_purchase(expired_mandate, proposal)
    assert res["decision"]["decision"] == PolicyVerdict.REJECTED.value
    assert res["razorpay_called"] is False

    # THE CORE INVARIANT
    assert mock_razorpay_executor.create_order.call_count == 0


def test_tampered_signature_never_calls_razorpay(storefront_service, mock_razorpay_executor, valid_mandate):
    """Forged or tampered mandate signature MUST NOT call Razorpay."""
    valid_mandate.signature = "bad_signature_" * 8
    proposal = TransactionProposal(
        proposal_id="prop_boundary_004",
        sku="SKU-001",
        item_name="Birthday Flowers",
        unit_price=700,
        quantity=1,
        total_amount=700,
        currency="INR",
        category="flowers",
        merchant_id="sentry-store",
        idempotency_key="idemp_boundary_004",
        mandate_id=valid_mandate.mandate_id
    )

    res = storefront_service.propose_purchase(valid_mandate, proposal)
    assert res["decision"]["decision"] == PolicyVerdict.REJECTED.value
    assert res["razorpay_called"] is False

    # THE CORE INVARIANT
    assert mock_razorpay_executor.create_order.call_count == 0


def test_direct_razorpay_invocation_without_authorization_raises_security_violation():
    """RazorpayExecutor.create_order raises SecurityViolationError if called without is_authorized=True."""
    executor = RazorpayExecutor()
    with pytest.raises(SecurityViolationError) as exc_info:
        executor.create_order(
            amount_inr=1200,
            receipt="prop_bypass_attempt",
            is_authorized=False  # Security gate closed
        )
    assert "CRITICAL SECURITY VIOLATION" in str(exc_info.value)
    assert executor.call_count == 0
