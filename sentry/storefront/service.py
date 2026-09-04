"""Storefront Service.

Coordinates catalog discovery, deterministic policy enforcement, audit logging,
and Razorpay order execution.
"""
from typing import Dict, Any, Optional
from sentry.mandate.schema import SpendingMandate, TransactionProposal
from sentry.policy.engine import PolicyEngine
from sentry.policy.rules import PolicyVerdict, PolicyReasonCode, PolicyDecision
from sentry.storefront.catalog import CATALOG, get_catalog_product, list_catalog_products
from sentry.razorpay_client.executor import RazorpayExecutor
from sentry.audit.logger import AuditLogger


class StorefrontService:
    """The central trusted service representing the merchant storefront and firewall boundary."""

    def __init__(
        self,
        policy_engine: PolicyEngine,
        audit_logger: AuditLogger,
        razorpay_executor: RazorpayExecutor
    ):
        self.policy_engine = policy_engine
        self.audit_logger = audit_logger
        self.razorpay = razorpay_executor

    def list_products(self) -> list:
        """Returns merchant product catalog."""
        products = list_catalog_products()
        self.audit_logger.log_event(
            event="product_listed",
            details={"product_count": len(products)}
        )
        return products

    def get_product(self, sku: str) -> Optional[dict]:
        """Retrieves details for a specific product."""
        product = get_catalog_product(sku)
        if product:
            self.audit_logger.log_event(
                event="product_selected",
                sku=sku,
                details={"item_name": product["name"], "price": product["price"]}
            )
        return product

    def propose_purchase(
        self,
        mandate: SpendingMandate,
        proposal: TransactionProposal
    ) -> Dict[str, Any]:
        """Evaluates an untrusted agent transaction proposal and conditionally calls Razorpay.
        
        Strict Invariant:
        If policy evaluation does not result in APPROVED, razorpay is NEVER called.
        """
        # 1. Log proposal entry
        self.audit_logger.log_event(
            event="purchase_proposed",
            mandate_id=mandate.mandate_id,
            sku=proposal.sku,
            quantity=proposal.quantity,
            requested_total=proposal.total_amount,
            details={"idempotency_key": proposal.idempotency_key, "category": proposal.category}
        )

        # 2. Check catalog item existence
        catalog_item = get_catalog_product(proposal.sku)
        if not catalog_item:
            decision = PolicyDecision(
                decision=PolicyVerdict.REJECTED,
                reason_code=PolicyReasonCode.PRODUCT_NOT_FOUND,
                reason=f"Product with SKU '{proposal.sku}' not found in catalog.",
                razorpay_call_allowed=False
            )
            self.audit_logger.log_event(
                event="purchase_rejected",
                mandate_id=mandate.mandate_id,
                sku=proposal.sku,
                decision="REJECTED",
                reason=decision.reason,
                razorpay_called=False
            )
            return {
                "decision": decision.model_dump(),
                "order": None,
                "razorpay_called": False
            }

        # 3. Log firewall evaluation start
        self.audit_logger.log_event(
            event="firewall_evaluation",
            mandate_id=mandate.mandate_id,
            sku=proposal.sku,
            quantity=proposal.quantity,
            requested_total=proposal.total_amount
        )

        # 4. Deterministic policy evaluation
        decision = self.policy_engine.evaluate(
            mandate=mandate,
            proposal=proposal,
            catalog_item=catalog_item
        )

        # 5. Handle Idempotent replay
        if decision.decision == PolicyVerdict.APPROVED and decision.reason_code == PolicyReasonCode.IDEMPOTENT_REPLAY:
            cached_order = decision.details.get("existing_order", {})
            self.audit_logger.log_event(
                event="firewall_verdict",
                mandate_id=mandate.mandate_id,
                sku=proposal.sku,
                decision="APPROVED",
                reason="Idempotent replay; returning existing order.",
                razorpay_called=False,
                order_id=cached_order.get("order_id"),
                details=decision.details
            )
            return {
                "decision": decision.model_dump(),
                "order": cached_order.get("razorpay_response"),
                "razorpay_called": False,
                "idempotent_replay": True
            }

        # 6. Handle Rejection (The core security invariant: razorpay_called = False)
        if decision.decision == PolicyVerdict.REJECTED:
            self.audit_logger.log_event(
                event="firewall_verdict",
                mandate_id=mandate.mandate_id,
                sku=proposal.sku,
                quantity=proposal.quantity,
                requested_total=proposal.total_amount,
                decision="REJECTED",
                reason=decision.reason_code.value,
                razorpay_called=False,
                details=decision.details
            )
            self.audit_logger.log_event(
                event="purchase_rejected",
                mandate_id=mandate.mandate_id,
                sku=proposal.sku,
                decision="REJECTED",
                reason=decision.reason,
                razorpay_called=False
            )
            return {
                "decision": decision.model_dump(),
                "order": None,
                "razorpay_called": False
            }

        # 7. Handle Human Approval Gating (P1)
        if decision.decision == PolicyVerdict.REQUIRES_HUMAN_APPROVAL:
            self.audit_logger.log_event(
                event="human_approval_requested",
                mandate_id=mandate.mandate_id,
                sku=proposal.sku,
                quantity=proposal.quantity,
                requested_total=proposal.total_amount,
                decision="REQUIRES_HUMAN_APPROVAL",
                reason=decision.reason,
                razorpay_called=False,
                details=decision.details
            )
            return {
                "decision": decision.model_dump(),
                "order": None,
                "razorpay_called": False,
                "requires_human_approval": True,
                "proposal": proposal.model_dump()
            }

        # 8. Handle Approved: Execute Razorpay Test Order
        order = self.razorpay.create_order(
            amount_inr=proposal.total_amount,
            receipt=proposal.proposal_id,
            notes={
                "mandate_id": mandate.mandate_id,
                "sku": proposal.sku,
                "agent_id": mandate.issued_to_agent,
                "quantity": proposal.quantity
            },
            is_authorized=True  # Strictly gated by policy verdict
        )

        order_id = order.get("id")

        # Record mandate consumption and idempotency
        if mandate.single_use:
            self.audit_logger.mark_mandate_consumed(
                mandate_id=mandate.mandate_id,
                order_id=order_id,
                total_amount=proposal.total_amount
            )

        self.audit_logger.record_executed_order(
            idempotency_key=proposal.idempotency_key,
            mandate_id=mandate.mandate_id,
            order_id=order_id,
            total_amount=proposal.total_amount,
            currency=proposal.currency,
            razorpay_response=order
        )

        # Log order creation
        self.audit_logger.log_event(
            event="firewall_verdict",
            mandate_id=mandate.mandate_id,
            sku=proposal.sku,
            quantity=proposal.quantity,
            requested_total=proposal.total_amount,
            decision="APPROVED",
            reason=decision.reason_code.value,
            razorpay_called=True,
            order_id=order_id,
            details=decision.details
        )
        self.audit_logger.log_event(
            event="razorpay_order_created",
            mandate_id=mandate.mandate_id,
            sku=proposal.sku,
            quantity=proposal.quantity,
            requested_total=proposal.total_amount,
            razorpay_called=True,
            order_id=order_id,
            details={"order": order}
        )

        return {
            "decision": decision.model_dump(),
            "order": order,
            "razorpay_called": True
        }
