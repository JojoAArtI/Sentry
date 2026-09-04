"""Tests for Single-Use Mandate Replay Prevention."""
import pytest
from sentry.mandate.schema import TransactionProposal
from sentry.policy.rules import PolicyVerdict, PolicyReasonCode


def test_single_use_mandate_replay_is_rejected(
    storefront_service,
    mock_razorpay_executor,
    valid_mandate
):
    """Attempting a second transaction with an already consumed single-use mandate is rejected."""
    proposal_1 = TransactionProposal(
        proposal_id="prop_first_001",
        sku="SKU-001",
        item_name="Birthday Flowers Bouquet",
        unit_price=700,
        quantity=1,
        total_amount=700,
        currency="INR",
        category="flowers",
        merchant_id="sentry-store",
        idempotency_key="idemp_first_111",
        mandate_id=valid_mandate.mandate_id
    )

    # First transaction succeeds
    res1 = storefront_service.propose_purchase(valid_mandate, proposal_1)
    assert res1["decision"]["decision"] == PolicyVerdict.APPROVED.value
    assert res1["razorpay_called"] is True
    assert mock_razorpay_executor.create_order.call_count == 1

    # Second transaction with different proposal/idempotency key using SAME mandate
    proposal_2 = TransactionProposal(
        proposal_id="prop_replay_002",
        sku="SKU-001",
        item_name="Birthday Flowers Bouquet",
        unit_price=700,
        quantity=1,
        total_amount=700,
        currency="INR",
        category="flowers",
        merchant_id="sentry-store",
        idempotency_key="idemp_replay_222",
        mandate_id=valid_mandate.mandate_id
    )

    res2 = storefront_service.propose_purchase(valid_mandate, proposal_2)
    assert res2["decision"]["decision"] == PolicyVerdict.REJECTED.value
    assert res2["decision"]["reason_code"] == PolicyReasonCode.MANDATE_ALREADY_USED.value
    assert res2["razorpay_called"] is False

    # CRITICAL INVARIANT: Razorpay was NOT called for the replay attempt
    assert mock_razorpay_executor.create_order.call_count == 1
