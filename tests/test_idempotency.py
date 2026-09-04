"""Tests for Idempotency guarantees in Sentry."""
import pytest
from sentry.mandate.schema import TransactionProposal
from sentry.policy.rules import PolicyVerdict, PolicyReasonCode


def test_duplicate_idempotency_key_does_not_duplicate_razorpay_order(
    storefront_service,
    mock_razorpay_executor,
    valid_mandate
):
    """Submitting duplicate proposal with the same idempotency key returns existing order without re-calling Razorpay."""
    proposal_1 = TransactionProposal(
        proposal_id="prop_idem_001",
        sku="SKU-001",
        item_name="Birthday Flowers Bouquet",
        unit_price=700,
        quantity=1,
        total_amount=700,
        currency="INR",
        category="flowers",
        merchant_id="sentry-store",
        idempotency_key="idemp_unique_key_999",
        mandate_id=valid_mandate.mandate_id
    )

    # First call: approved and executes order
    res1 = storefront_service.propose_purchase(valid_mandate, proposal_1)
    assert res1["decision"]["decision"] == PolicyVerdict.APPROVED.value
    assert res1["razorpay_called"] is True
    assert mock_razorpay_executor.create_order.call_count == 1
    first_order_id = res1["order"]["id"]

    # Second call with SAME idempotency key
    res2 = storefront_service.propose_purchase(valid_mandate, proposal_1)
    assert res2["decision"]["decision"] == PolicyVerdict.APPROVED.value
    assert res2["decision"]["reason_code"] == PolicyReasonCode.IDEMPOTENT_REPLAY.value
    assert res2["razorpay_called"] is False
    assert res2.get("idempotent_replay") is True
    # CRITICAL: Mock Razorpay create_order must NOT have been called again!
    assert mock_razorpay_executor.create_order.call_count == 1
    assert res2["order"]["id"] == first_order_id
