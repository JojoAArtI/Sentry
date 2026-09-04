"""Deterministic Policy Engine.

Evaluates untrusted transaction proposals against signed spending mandates.
Strict rule: NO LLM is permitted in this authorization loop.
"""
from datetime import datetime, timezone
from typing import Optional, Protocol

from sentry.mandate.schema import SpendingMandate, TransactionProposal
from sentry.mandate.verifier import MandateVerifier
from sentry.policy.rules import PolicyDecision, PolicyVerdict, PolicyReasonCode


class MandateStateStore(Protocol):
    """Protocol for checking mandate consumption and idempotency."""
    def is_mandate_used(self, mandate_id: str) -> bool: ...
    def get_idempotent_order(self, idempotency_key: str) -> Optional[dict]: ...


class PolicyEngine:
    """Deterministic authorization engine for Sentry."""

    def __init__(self, public_key_hex: str, state_store: Optional[MandateStateStore] = None):
        self.public_key_hex = public_key_hex
        self.state_store = state_store

    def evaluate(
        self,
        mandate: SpendingMandate,
        proposal: TransactionProposal,
        catalog_item: Optional[dict] = None,
        now: Optional[datetime] = None
    ) -> PolicyDecision:
        """Evaluates a proposed transaction against the signed mandate.
        
        Evaluation sequence:
        1. Cryptographic Signature
        2. Expiration
        3. Single-Use Replay
        4. Idempotency Check
        5. Merchant Alignment
        6. Currency Alignment
        7. Catalog / Price Integrity
        8. Category Whitelist
        9. Quantity Limits
        10. Spending Maximum
        11. Autonomous Spending Threshold (Human-in-the-Loop)
        """
        if now is None:
            now = datetime.now(timezone.utc)
        elif now.tzinfo is None:
            now = now.replace(tzinfo=timezone.utc)

        # 1. Cryptographic Signature
        if not MandateVerifier.verify(mandate, self.public_key_hex):
            return PolicyDecision(
                decision=PolicyVerdict.REJECTED,
                reason_code=PolicyReasonCode.INVALID_SIGNATURE,
                reason="Mandate cryptographic signature is invalid or tampered.",
                razorpay_call_allowed=False,
                details={"mandate_id": mandate.mandate_id}
            )

        # 2. Expiration Check
        exp = mandate.expires_at
        if exp.tzinfo is None:
            exp = exp.replace(tzinfo=timezone.utc)
        if now > exp:
            return PolicyDecision(
                decision=PolicyVerdict.REJECTED,
                reason_code=PolicyReasonCode.MANDATE_EXPIRED,
                reason=f"Mandate expired at {exp.isoformat()} (current time {now.isoformat()}).",
                razorpay_call_allowed=False,
                details={"expires_at": exp.isoformat(), "current_time": now.isoformat()}
            )

        # 3. Single-Use Replay Check
        if mandate.single_use and self.state_store and self.state_store.is_mandate_used(mandate.mandate_id):
            return PolicyDecision(
                decision=PolicyVerdict.REJECTED,
                reason_code=PolicyReasonCode.MANDATE_ALREADY_USED,
                reason=f"Single-use mandate {mandate.mandate_id} has already been consumed.",
                razorpay_call_allowed=False,
                details={"mandate_id": mandate.mandate_id}
            )

        # 4. Idempotency Check
        if self.state_store:
            existing = self.state_store.get_idempotent_order(proposal.idempotency_key)
            if existing:
                return PolicyDecision(
                    decision=PolicyVerdict.APPROVED,
                    reason_code=PolicyReasonCode.IDEMPOTENT_REPLAY,
                    reason=f"Request already processed for idempotency key {proposal.idempotency_key}.",
                    razorpay_call_allowed=False,  # Already created, must not duplicate Razorpay API call!
                    details={"existing_order": existing}
                )

        # 5. Merchant Alignment
        if proposal.merchant_id != mandate.merchant_id:
            return PolicyDecision(
                decision=PolicyVerdict.REJECTED,
                reason_code=PolicyReasonCode.MERCHANT_MISMATCH,
                reason=f"Target merchant '{proposal.merchant_id}' does not match authorized merchant '{mandate.merchant_id}'.",
                razorpay_call_allowed=False,
                details={"target_merchant": proposal.merchant_id, "authorized_merchant": mandate.merchant_id}
            )

        # 6. Currency Alignment
        if proposal.currency.upper() != mandate.currency.upper():
            return PolicyDecision(
                decision=PolicyVerdict.REJECTED,
                reason_code=PolicyReasonCode.CURRENCY_MISMATCH,
                reason=f"Proposal currency '{proposal.currency}' does not match mandate currency '{mandate.currency}'.",
                razorpay_call_allowed=False,
                details={"proposal_currency": proposal.currency, "mandate_currency": mandate.currency}
            )

        # 7. Catalog & Price Integrity
        if catalog_item is not None:
            server_unit_price = catalog_item.get("price")
            server_category = catalog_item.get("category")
            if server_unit_price is not None and proposal.unit_price != server_unit_price:
                return PolicyDecision(
                    decision=PolicyVerdict.REJECTED,
                    reason_code=PolicyReasonCode.PRICE_TAMPERING_DETECTED,
                    reason=f"Proposed unit price ₹{proposal.unit_price} does not match authoritative catalog price ₹{server_unit_price}.",
                    razorpay_call_allowed=False,
                    details={"proposed_price": proposal.unit_price, "catalog_price": server_unit_price}
                )
            if server_category is not None and proposal.category != server_category:
                # Override with authoritative catalog category for evaluation
                proposal.category = server_category

        # Recalculate true total to prevent arithmetic spoofing
        calculated_total = proposal.unit_price * proposal.quantity
        if proposal.total_amount != calculated_total:
            proposal.total_amount = calculated_total

        # 8. Category Whitelist
        if mandate.allowed_categories and proposal.category not in mandate.allowed_categories:
            return PolicyDecision(
                decision=PolicyVerdict.REJECTED,
                reason_code=PolicyReasonCode.CATEGORY_DISALLOWED,
                reason=f"Category '{proposal.category}' is not permitted by mandate. Allowed: {mandate.allowed_categories}",
                razorpay_call_allowed=False,
                details={"category": proposal.category, "allowed": mandate.allowed_categories}
            )

        # 9. Quantity Limits
        if proposal.quantity > mandate.max_quantity:
            return PolicyDecision(
                decision=PolicyVerdict.REJECTED,
                reason_code=PolicyReasonCode.QUANTITY_EXCEEDS_LIMIT,
                reason=f"Requested quantity {proposal.quantity} exceeds mandate maximum {mandate.max_quantity}.",
                razorpay_call_allowed=False,
                details={"requested_quantity": proposal.quantity, "max_quantity": mandate.max_quantity}
            )

        # 10. Spending Maximum
        if proposal.total_amount > mandate.max_amount:
            return PolicyDecision(
                decision=PolicyVerdict.REJECTED,
                reason_code=PolicyReasonCode.AMOUNT_EXCEEDS_LIMIT,
                reason=f"Requested total ₹{proposal.total_amount:,} exceeds mandate maximum ₹{mandate.max_amount:,}.",
                razorpay_call_allowed=False,
                details={"requested_amount": proposal.total_amount, "max_amount": mandate.max_amount}
            )

        # 11. Autonomous Spending Threshold (Human Approval Gating - P1)
        if (
            mandate.autonomous_threshold is not None
            and proposal.total_amount > mandate.autonomous_threshold
        ):
            return PolicyDecision(
                decision=PolicyVerdict.REQUIRES_HUMAN_APPROVAL,
                reason_code=PolicyReasonCode.HUMAN_APPROVAL_THRESHOLD_EXCEEDED,
                reason=f"Total ₹{proposal.total_amount:,} exceeds autonomous threshold ₹{mandate.autonomous_threshold:,}. Requires human sign-off.",
                razorpay_call_allowed=False,
                details={
                    "total_amount": proposal.total_amount,
                    "autonomous_threshold": mandate.autonomous_threshold
                }
            )

        # All deterministic checks passed!
        return PolicyDecision(
            decision=PolicyVerdict.APPROVED,
            reason_code=PolicyReasonCode.WITHIN_MANDATE,
            reason="Transaction satisfies all signed mandate constraints.",
            razorpay_call_allowed=True,
            details={
                "mandate_id": mandate.mandate_id,
                "amount": proposal.total_amount,
                "quantity": proposal.quantity,
                "category": proposal.category
            }
        )
