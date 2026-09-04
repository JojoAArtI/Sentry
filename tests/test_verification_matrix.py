"""Verification Matrix as defined by Section 18 of Master Build Prompt:
- At least 10 successful authorized purchase attempts
- At least 10 rejected attempts
- At least 5 replay attempts
- At least 5 expired mandate attempts
- At least 5 category violation attempts
- At least 5 quantity violation attempts
"""
import pytest
from datetime import datetime, timedelta, timezone
from sentry.mandate.schema import SpendingMandate, TransactionProposal
from sentry.mandate.signer import MandateSigner
from sentry.policy.rules import PolicyVerdict, PolicyReasonCode
from sentry.storefront.service import StorefrontService


@pytest.mark.parametrize("attempt_id", range(1, 11))
def test_matrix_authorized_purchases_10_attempts(
    attempt_id,
    storefront_service,
    signer,
    mock_razorpay_executor
):
    """Executes 10 distinct successful authorized purchases."""
    future = datetime.now(timezone.utc) + timedelta(hours=2)
    mandate = SpendingMandate(
        mandate_id=f"mnd_matrix_auth_{attempt_id}",
        issued_to_agent="buyer-agent-01",
        merchant_id="sentry-store",
        max_amount=1500,
        currency="INR",
        allowed_categories=["gifts", "flowers"],
        max_quantity=2,
        expires_at=future,
        single_use=True
    )
    signed_mandate = signer.sign_mandate(mandate)

    proposal = TransactionProposal(
        proposal_id=f"prop_auth_{attempt_id}",
        sku="SKU-001" if attempt_id % 2 == 0 else "SKU-002",
        item_name="Flowers" if attempt_id % 2 == 0 else "Necklace",
        unit_price=700 if attempt_id % 2 == 0 else 1200,
        quantity=1,
        total_amount=700 if attempt_id % 2 == 0 else 1200,
        currency="INR",
        category="flowers" if attempt_id % 2 == 0 else "gifts",
        merchant_id="sentry-store",
        idempotency_key=f"idemp_matrix_auth_{attempt_id}",
        mandate_id=signed_mandate.mandate_id
    )

    res = storefront_service.propose_purchase(signed_mandate, proposal)
    assert res["decision"]["decision"] == PolicyVerdict.APPROVED.value
    assert res["razorpay_called"] is True


@pytest.mark.parametrize("attempt_id", range(1, 11))
def test_matrix_rejected_attempts_10_attempts(
    attempt_id,
    storefront_service,
    signer,
    mock_razorpay_executor
):
    """Executes 10 distinct rejected unauthorized purchases.
    CRITICAL: Razorpay must NOT be called on any attempt.
    """
    initial_calls = mock_razorpay_executor.create_order.call_count
    future = datetime.now(timezone.utc) + timedelta(hours=2)
    mandate = SpendingMandate(
        mandate_id=f"mnd_matrix_rej_{attempt_id}",
        issued_to_agent="buyer-agent-01",
        merchant_id="sentry-store",
        max_amount=1500,
        currency="INR",
        allowed_categories=["gifts"],
        max_quantity=2,
        expires_at=future,
        single_use=True
    )
    signed_mandate = signer.sign_mandate(mandate)

    # Alternate between quantity attack (40 units) and budget violation
    attack_qty = 40 + attempt_id
    proposal = TransactionProposal(
        proposal_id=f"prop_rej_{attempt_id}",
        sku="SKU-002",
        item_name="Silver Heart Necklace",
        unit_price=1200,
        quantity=attack_qty,
        total_amount=1200 * attack_qty,
        currency="INR",
        category="gifts",
        merchant_id="sentry-store",
        idempotency_key=f"idemp_matrix_rej_{attempt_id}",
        mandate_id=signed_mandate.mandate_id
    )

    res = storefront_service.propose_purchase(signed_mandate, proposal)
    assert res["decision"]["decision"] == PolicyVerdict.REJECTED.value
    assert res["razorpay_called"] is False
    assert mock_razorpay_executor.create_order.call_count == initial_calls


@pytest.mark.parametrize("attempt_id", range(1, 6))
def test_matrix_replay_5_attempts(
    attempt_id,
    storefront_service,
    signer,
    mock_razorpay_executor
):
    """Executes 5 replay attempts against already consumed single-use mandates."""
    future = datetime.now(timezone.utc) + timedelta(hours=2)
    mandate = SpendingMandate(
        mandate_id=f"mnd_matrix_replay_{attempt_id}",
        issued_to_agent="buyer-agent-01",
        merchant_id="sentry-store",
        max_amount=1500,
        currency="INR",
        allowed_categories=["gifts"],
        max_quantity=2,
        expires_at=future,
        single_use=True
    )
    signed_mandate = signer.sign_mandate(mandate)

    # Consume first
    p1 = TransactionProposal(
        proposal_id=f"prop_rep_legit_{attempt_id}",
        sku="SKU-002",
        item_name="Silver Necklace",
        unit_price=1200,
        quantity=1,
        total_amount=1200,
        currency="INR",
        category="gifts",
        merchant_id="sentry-store",
        idempotency_key=f"idemp_rep_first_{attempt_id}",
        mandate_id=signed_mandate.mandate_id
    )
    res1 = storefront_service.propose_purchase(signed_mandate, p1)
    assert res1["decision"]["decision"] == PolicyVerdict.APPROVED.value

    calls_after_first = mock_razorpay_executor.create_order.call_count

    # Attempt replay with new idempotency key
    p2 = TransactionProposal(
        proposal_id=f"prop_rep_attack_{attempt_id}",
        sku="SKU-002",
        item_name="Silver Necklace",
        unit_price=1200,
        quantity=1,
        total_amount=1200,
        currency="INR",
        category="gifts",
        merchant_id="sentry-store",
        idempotency_key=f"idemp_rep_second_{attempt_id}",
        mandate_id=signed_mandate.mandate_id
    )
    res2 = storefront_service.propose_purchase(signed_mandate, p2)
    assert res2["decision"]["decision"] == PolicyVerdict.REJECTED.value
    assert res2["decision"]["reason_code"] == PolicyReasonCode.MANDATE_ALREADY_USED.value
    assert res2["razorpay_called"] is False
    assert mock_razorpay_executor.create_order.call_count == calls_after_first


@pytest.mark.parametrize("attempt_id", range(1, 6))
def test_matrix_expired_mandate_5_attempts(
    attempt_id,
    storefront_service,
    signer,
    mock_razorpay_executor
):
    """Executes 5 expired mandate attempts."""
    past = datetime.now(timezone.utc) - timedelta(hours=attempt_id)
    mandate = SpendingMandate(
        mandate_id=f"mnd_matrix_exp_{attempt_id}",
        issued_to_agent="buyer-agent-01",
        merchant_id="sentry-store",
        max_amount=1500,
        currency="INR",
        allowed_categories=["gifts"],
        max_quantity=2,
        expires_at=past,
        single_use=True
    )
    signed_mandate = signer.sign_mandate(mandate)

    proposal = TransactionProposal(
        proposal_id=f"prop_exp_{attempt_id}",
        sku="SKU-002",
        item_name="Silver Necklace",
        unit_price=1200,
        quantity=1,
        total_amount=1200,
        currency="INR",
        category="gifts",
        merchant_id="sentry-store",
        idempotency_key=f"idemp_matrix_exp_{attempt_id}",
        mandate_id=signed_mandate.mandate_id
    )

    initial_calls = mock_razorpay_executor.create_order.call_count
    res = storefront_service.propose_purchase(signed_mandate, proposal)
    assert res["decision"]["decision"] == PolicyVerdict.REJECTED.value
    assert res["decision"]["reason_code"] == PolicyReasonCode.MANDATE_EXPIRED.value
    assert res["razorpay_called"] is False
    assert mock_razorpay_executor.create_order.call_count == initial_calls


@pytest.mark.parametrize("attempt_id", range(1, 6))
def test_matrix_category_violation_5_attempts(
    attempt_id,
    storefront_service,
    signer,
    mock_razorpay_executor
):
    """Executes 5 category violation attempts."""
    future = datetime.now(timezone.utc) + timedelta(hours=2)
    mandate = SpendingMandate(
        mandate_id=f"mnd_matrix_cat_{attempt_id}",
        issued_to_agent="buyer-agent-01",
        merchant_id="sentry-store",
        max_amount=10000,
        currency="INR",
        allowed_categories=["flowers"],  # Only flowers allowed
        max_quantity=5,
        expires_at=future,
        single_use=True
    )
    signed_mandate = signer.sign_mandate(mandate)

    # Propose electronics
    proposal = TransactionProposal(
        proposal_id=f"prop_cat_{attempt_id}",
        sku="SKU-004",
        item_name="Premium Headphones",
        unit_price=4800,
        quantity=1,
        total_amount=4800,
        currency="INR",
        category="electronics",
        merchant_id="sentry-store",
        idempotency_key=f"idemp_matrix_cat_{attempt_id}",
        mandate_id=signed_mandate.mandate_id
    )

    initial_calls = mock_razorpay_executor.create_order.call_count
    res = storefront_service.propose_purchase(signed_mandate, proposal)
    assert res["decision"]["decision"] == PolicyVerdict.REJECTED.value
    assert res["decision"]["reason_code"] == PolicyReasonCode.CATEGORY_DISALLOWED.value
    assert res["razorpay_called"] is False
    assert mock_razorpay_executor.create_order.call_count == initial_calls


@pytest.mark.parametrize("attempt_id", range(1, 6))
def test_matrix_quantity_violation_5_attempts(
    attempt_id,
    storefront_service,
    signer,
    mock_razorpay_executor
):
    """Executes 5 quantity violation attempts."""
    future = datetime.now(timezone.utc) + timedelta(hours=2)
    mandate = SpendingMandate(
        mandate_id=f"mnd_matrix_qty_{attempt_id}",
        issued_to_agent="buyer-agent-01",
        merchant_id="sentry-store",
        max_amount=50000,
        currency="INR",
        allowed_categories=["gifts", "flowers"],
        max_quantity=2,  # Max quantity is 2
        expires_at=future,
        single_use=True
    )
    signed_mandate = signer.sign_mandate(mandate)

    qty = 3 + attempt_id  # 4, 5, 6, 7, 8
    proposal = TransactionProposal(
        proposal_id=f"prop_qty_{attempt_id}",
        sku="SKU-001",
        item_name="Birthday Flowers",
        unit_price=700,
        quantity=qty,
        total_amount=700 * qty,
        currency="INR",
        category="flowers",
        merchant_id="sentry-store",
        idempotency_key=f"idemp_matrix_qty_{attempt_id}",
        mandate_id=signed_mandate.mandate_id
    )

    initial_calls = mock_razorpay_executor.create_order.call_count
    res = storefront_service.propose_purchase(signed_mandate, proposal)
    assert res["decision"]["decision"] == PolicyVerdict.REJECTED.value
    assert res["decision"]["reason_code"] == PolicyReasonCode.QUANTITY_EXCEEDS_LIMIT.value
    assert res["razorpay_called"] is False
    assert mock_razorpay_executor.create_order.call_count == initial_calls
