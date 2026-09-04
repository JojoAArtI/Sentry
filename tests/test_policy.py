"""Tests for Sentry Deterministic Policy Engine."""
import pytest
from datetime import datetime, timezone
from sentry.mandate.schema import TransactionProposal
from sentry.policy.rules import PolicyVerdict, PolicyReasonCode
from sentry.storefront.catalog import get_catalog_product


def test_valid_proposal_approved(policy_engine, valid_mandate):
    """Proposal within all limits is approved with razorpay_call_allowed=True."""
    proposal = TransactionProposal(
        proposal_id="prop_001",
        sku="SKU-002",
        item_name="Silver Heart Necklace",
        unit_price=1200,
        quantity=1,
        total_amount=1200,
        currency="INR",
        category="gifts",
        merchant_id="sentry-store",
        idempotency_key="idemp_001",
        mandate_id=valid_mandate.mandate_id
    )
    catalog_item = get_catalog_product("SKU-002")
    decision = policy_engine.evaluate(valid_mandate, proposal, catalog_item)

    assert decision.decision == PolicyVerdict.APPROVED
    assert decision.reason_code == PolicyReasonCode.WITHIN_MANDATE
    assert decision.razorpay_call_allowed is True


def test_invalid_signature_rejected(policy_engine, valid_mandate):
    """Tampered signature must be rejected."""
    valid_mandate.signature = "a" * 128
    proposal = TransactionProposal(
        proposal_id="prop_002",
        sku="SKU-001",
        item_name="Birthday Flowers",
        unit_price=700,
        quantity=1,
        total_amount=700,
        currency="INR",
        category="flowers",
        merchant_id="sentry-store",
        idempotency_key="idemp_002",
        mandate_id=valid_mandate.mandate_id
    )
    decision = policy_engine.evaluate(valid_mandate, proposal)
    assert decision.decision == PolicyVerdict.REJECTED
    assert decision.reason_code == PolicyReasonCode.INVALID_SIGNATURE
    assert decision.razorpay_call_allowed is False


def test_expired_mandate_rejected(policy_engine, expired_mandate):
    """Proposal against an expired mandate must be rejected."""
    proposal = TransactionProposal(
        proposal_id="prop_003",
        sku="SKU-001",
        item_name="Birthday Flowers",
        unit_price=700,
        quantity=1,
        total_amount=700,
        currency="INR",
        category="flowers",
        merchant_id="sentry-store",
        idempotency_key="idemp_003",
        mandate_id=expired_mandate.mandate_id
    )
    decision = policy_engine.evaluate(expired_mandate, proposal)
    assert decision.decision == PolicyVerdict.REJECTED
    assert decision.reason_code == PolicyReasonCode.MANDATE_EXPIRED
    assert decision.razorpay_call_allowed is False


def test_amount_exceeds_limit_rejected(policy_engine, valid_mandate):
    """Proposal exceeding max_amount (e.g. ₹48,000 > ₹1,500) must be rejected."""
    proposal = TransactionProposal(
        proposal_id="prop_004",
        sku="SKU-002",
        item_name="Silver Heart Necklace",
        unit_price=1200,
        quantity=40,
        total_amount=48000,
        currency="INR",
        category="gifts",
        merchant_id="sentry-store",
        idempotency_key="idemp_004",
        mandate_id=valid_mandate.mandate_id
    )
    decision = policy_engine.evaluate(valid_mandate, proposal)
    assert decision.decision == PolicyVerdict.REJECTED
    # Quantity will also trigger or amount will trigger
    assert decision.reason_code in (
        PolicyReasonCode.AMOUNT_EXCEEDS_LIMIT,
        PolicyReasonCode.QUANTITY_EXCEEDS_LIMIT
    )
    assert decision.razorpay_call_allowed is False


def test_disallowed_category_rejected(policy_engine, valid_mandate):
    """Proposal with category outside allowed_categories must be rejected."""
    proposal = TransactionProposal(
        proposal_id="prop_005",
        sku="SKU-004",
        item_name="Premium Wireless Noise-Cancelling Headphones",
        unit_price=4800,
        quantity=1,
        total_amount=4800,
        currency="INR",
        category="electronics",  # Not in ["gifts", "flowers"]
        merchant_id="sentry-store",
        idempotency_key="idemp_005",
        mandate_id=valid_mandate.mandate_id
    )
    catalog_item = get_catalog_product("SKU-004")
    decision = policy_engine.evaluate(valid_mandate, proposal, catalog_item)
    assert decision.decision == PolicyVerdict.REJECTED
    assert decision.reason_code == PolicyReasonCode.CATEGORY_DISALLOWED
    assert decision.razorpay_call_allowed is False


def test_quantity_exceeds_limit_rejected(policy_engine, valid_mandate):
    """Proposal where quantity > max_quantity (e.g. 5 > 2) must be rejected."""
    proposal = TransactionProposal(
        proposal_id="prop_006",
        sku="SKU-001",
        item_name="Birthday Flowers",
        unit_price=700,
        quantity=5,  # Max is 2
        total_amount=3500,
        currency="INR",
        category="flowers",
        merchant_id="sentry-store",
        idempotency_key="idemp_006",
        mandate_id=valid_mandate.mandate_id
    )
    catalog_item = get_catalog_product("SKU-001")
    decision = policy_engine.evaluate(valid_mandate, proposal, catalog_item)
    assert decision.decision == PolicyVerdict.REJECTED
    assert decision.reason_code == PolicyReasonCode.QUANTITY_EXCEEDS_LIMIT
    assert decision.razorpay_call_allowed is False


def test_wrong_merchant_rejected(policy_engine, valid_mandate):
    """Proposal targeting unauthorized merchant must be rejected."""
    proposal = TransactionProposal(
        proposal_id="prop_007",
        sku="SKU-001",
        item_name="Birthday Flowers",
        unit_price=700,
        quantity=1,
        total_amount=700,
        currency="INR",
        category="flowers",
        merchant_id="rogue-merchant-store",  # Authorized: sentry-store
        idempotency_key="idemp_007",
        mandate_id=valid_mandate.mandate_id
    )
    decision = policy_engine.evaluate(valid_mandate, proposal)
    assert decision.decision == PolicyVerdict.REJECTED
    assert decision.reason_code == PolicyReasonCode.MERCHANT_MISMATCH
    assert decision.razorpay_call_allowed is False


def test_wrong_currency_rejected(policy_engine, valid_mandate):
    """Proposal using unauthorized currency (e.g. USD) must be rejected."""
    proposal = TransactionProposal(
        proposal_id="prop_008",
        sku="SKU-001",
        item_name="Birthday Flowers",
        unit_price=700,
        quantity=1,
        total_amount=700,
        currency="USD",  # Authorized: INR
        category="flowers",
        merchant_id="sentry-store",
        idempotency_key="idemp_008",
        mandate_id=valid_mandate.mandate_id
    )
    decision = policy_engine.evaluate(valid_mandate, proposal)
    assert decision.decision == PolicyVerdict.REJECTED
    assert decision.reason_code == PolicyReasonCode.CURRENCY_MISMATCH
    assert decision.razorpay_call_allowed is False


def test_price_tampering_detected(policy_engine, valid_mandate):
    """Untrusted agent sending a lower unit price than catalog must be rejected."""
    proposal = TransactionProposal(
        proposal_id="prop_009",
        sku="SKU-002",
        item_name="Silver Heart Necklace",
        unit_price=10,  # Real price is 1200
        quantity=1,
        total_amount=10,
        currency="INR",
        category="gifts",
        merchant_id="sentry-store",
        idempotency_key="idemp_009",
        mandate_id=valid_mandate.mandate_id
    )
    catalog_item = get_catalog_product("SKU-002")
    decision = policy_engine.evaluate(valid_mandate, proposal, catalog_item)
    assert decision.decision == PolicyVerdict.REJECTED
    assert decision.reason_code == PolicyReasonCode.PRICE_TAMPERING_DETECTED
    assert decision.razorpay_call_allowed is False


def test_autonomous_threshold_requires_human_approval(signer, policy_engine):
    """Transactions exceeding autonomous threshold but <= max_amount require human approval."""
    future = datetime.now(timezone.utc)
    mandate = SpendingMandate(
        mandate_id="mnd_threshold_001",
        issued_to_agent="buyer-agent-01",
        merchant_id="sentry-store",
        max_amount=5000,
        currency="INR",
        allowed_categories=["gifts"],
        max_quantity=2,
        expires_at=datetime(2028, 1, 1, tzinfo=timezone.utc),
        single_use=True,
        autonomous_threshold=1000  # Threshold is 1000
    )
    signed_mandate = signer.sign_mandate(mandate)

    # Price 1200 > autonomous threshold 1000, but < max_amount 5000
    proposal = TransactionProposal(
        proposal_id="prop_010",
        sku="SKU-002",
        item_name="Silver Heart Necklace",
        unit_price=1200,
        quantity=1,
        total_amount=1200,
        currency="INR",
        category="gifts",
        merchant_id="sentry-store",
        idempotency_key="idemp_010",
        mandate_id=signed_mandate.mandate_id
    )
    catalog_item = get_catalog_product("SKU-002")
    decision = policy_engine.evaluate(signed_mandate, proposal, catalog_item)
    assert decision.decision == PolicyVerdict.REQUIRES_HUMAN_APPROVAL
    assert decision.reason_code == PolicyReasonCode.HUMAN_APPROVAL_THRESHOLD_EXCEEDED
    assert decision.razorpay_call_allowed is False
