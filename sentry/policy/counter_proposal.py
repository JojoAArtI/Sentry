"""Graceful Failure & Counter-Proposal Recovery Engine for Sentry.

Addresses Razorpay's explicit hackathon criterion: 'one failure handled gracefully'.
When an adversarial injection or agent calculation error results in a firewall rejection,
this engine deterministically computes the maximum viable proposal within mandate bounds,
enabling autonomous agent recovery without human intervention or budget breach.
"""
from typing import Dict, Any, Optional
from sentry.mandate.schema import SpendingMandate, TransactionProposal
from sentry.policy.rules import PolicyVerdict, PolicyReasonCode
from sentry.storefront.catalog import CATALOG, get_catalog_product


class GracefulRecoveryEngine:
    """Computes bounded, explainable counter-proposals on transaction rejection."""

    def __init__(self):
        pass

    def generate_counter_proposal(
        self,
        failed_proposal: TransactionProposal,
        mandate: SpendingMandate,
        verdict: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Analyzes failure reason and returns an actionable, bounded counter-proposal."""
        reason_code = verdict.get("reason_code", "")
        reason_msg = verdict.get("reason", "Transaction rejected by Sentry policy firewall")
        
        # Look up authoritative product info
        product = CATALOG.get(failed_proposal.sku)
        unit_price = product.price if product else failed_proposal.unit_price

        # Default recovery recommendation
        max_allowed_by_budget = mandate.max_amount // unit_price if unit_price > 0 else 0
        suggested_quantity = min(mandate.max_quantity, max_allowed_by_budget)
        suggested_total = suggested_quantity * unit_price

        # Determine if auto-recoverable
        if suggested_quantity <= 0 or product is None or product.category not in mandate.allowed_categories:
            return {
                "recoverable": False,
                "remediation_status": "UNRECOVERABLE_ERROR",
                "failure_reason": reason_msg,
                "reason_code": reason_code,
                "action": "HALT_AGENT_EXECUTION",
                "message": f"Cannot remediate: product {failed_proposal.sku} violates mandate category or minimum budget."
            }

        # Valid counter-proposal exists
        recovered_proposal = TransactionProposal(
            proposal_id=f"prop_recover_{failed_proposal.proposal_id}",
            mandate_id=mandate.mandate_id,
            sku=failed_proposal.sku,
            item_name=product.name,
            quantity=suggested_quantity,
            unit_price=unit_price,
            total_amount=suggested_total,
            currency=mandate.currency,
            merchant_id=mandate.merchant_id,
            category=product.category,
            idempotency_key=f"recover_{failed_proposal.idempotency_key}"
        )

        return {
            "recoverable": True,
            "remediation_status": "COUNTER_PROPOSAL_OFFERED",
            "action": "AUTO_RECOVERABLE_WITHIN_MANDATE",
            "failure_context": {
                "original_quantity": failed_proposal.quantity,
                "original_total": failed_proposal.total_amount,
                "reason_code": reason_code,
                "failure_reason": reason_msg,
            },
            "remediation": {
                "suggested_quantity": suggested_quantity,
                "suggested_total": suggested_total,
                "unit_price": unit_price,
                "mandate_max_amount": mandate.max_amount,
                "mandate_max_quantity": mandate.max_quantity,
                "rationale": (
                    f"Reduced quantity from {failed_proposal.quantity} to {suggested_quantity} unit(s). "
                    f"Total adjusted from ₹{failed_proposal.total_amount:,} INR to ₹{suggested_total:,} INR, "
                    f"fitting comfortably within your ₹{mandate.max_amount:,} INR spending limit."
                )
            },
            "counter_proposal": recovered_proposal.model_dump()
        }
