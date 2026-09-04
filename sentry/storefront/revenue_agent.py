"""Merchant Revenue & Upsell Agent for Sentry.

Autonomous merchant-side agent that monitors buyer purchase proposals,
calculates available mandate headroom, and proposes relevant add-ons
to maximize merchant GMV while strictly respecting signed customer spending limits.
"""
from typing import Dict, Any, Optional, List
from sentry.mandate.schema import SpendingMandate, TransactionProposal
from sentry.storefront.catalog import CATALOG, Product, get_catalog_product


class MerchantRevenueAgent:
    """Autonomous Upsell Engine for Merchant Growth."""

    def __init__(self, merchant_id: str = "sentry-store"):
        self.merchant_id = merchant_id

    def find_eligible_add_on(
        self,
        base_proposal: TransactionProposal,
        mandate: SpendingMandate
    ) -> Optional[Product]:
        """Identifies the best add-on product fitting within remaining mandate headroom."""
        headroom = mandate.max_amount - base_proposal.total_amount
        if headroom <= 0:
            return None

        # Filter candidate add-ons matching mandate categories and within headroom
        candidates: List[Product] = []
        for product in CATALOG.values():
            if product.sku == base_proposal.sku:
                continue
            if product.category not in mandate.allowed_categories:
                continue
            if product.price <= headroom and product.stock > 0 and not product.has_injection:
                candidates.append(product)

        if not candidates:
            return None

        # Prefer the highest value add-on that fits within headroom to maximize GMV
        candidates.sort(key=lambda p: p.price, reverse=True)
        return candidates[0]

    def create_upsell_bundle(
        self,
        base_proposal: TransactionProposal,
        mandate: SpendingMandate
    ) -> Dict[str, Any]:
        """Evaluates proposal headroom and generates a bounded upsell bundle."""
        headroom_before = mandate.max_amount - base_proposal.total_amount
        add_on = self.find_eligible_add_on(base_proposal, mandate)

        if not add_on:
            return {
                "eligible": False,
                "reason": "No matching add-on within remaining mandate headroom",
                "headroom_remaining": headroom_before,
                "base_proposal": base_proposal.model_dump(),
            }

        bundled_total = base_proposal.total_amount + add_on.price
        headroom_after = mandate.max_amount - bundled_total
        gmv_growth_pct = round(((bundled_total - base_proposal.total_amount) / base_proposal.total_amount) * 100, 1)

        # Create bundled proposal representation
        bundled_proposal = TransactionProposal(
            mandate_id=mandate.mandate_id,
            sku=base_proposal.sku,
            item_name=f"{base_proposal.item_name} + {add_on.name}",
            quantity=base_proposal.quantity,
            unit_price=base_proposal.unit_price,
            total_amount=bundled_total,
            currency=mandate.currency,
            merchant_id=self.merchant_id,
            category=base_proposal.category,
            idempotency_key=f"upsell_{base_proposal.idempotency_key}"
        )

        return {
            "eligible": True,
            "status": "BUNDLED_WITHIN_MANDATE",
            "original_item": {
                "sku": base_proposal.sku,
                "name": base_proposal.item_name,
                "amount": base_proposal.total_amount,
            },
            "add_on": {
                "sku": add_on.sku,
                "name": add_on.name,
                "price": add_on.price,
                "category": add_on.category,
            },
            "financial_breakdown": {
                "base_amount": base_proposal.total_amount,
                "upsell_amount": add_on.price,
                "bundled_total": bundled_total,
                "mandate_max_limit": mandate.max_amount,
                "headroom_before": headroom_before,
                "headroom_after": headroom_after,
                "gmv_growth_percentage": gmv_growth_pct,
            },
            "bundled_proposal": bundled_proposal.model_dump(),
            "reasoning": (
                f"Mandate ceiling ₹{mandate.max_amount:,} INR leaves ₹{headroom_before:,} INR headroom. "
                f"Added '{add_on.name}' (+₹{add_on.price:,} INR). "
                f"Grows merchant GMV by +{gmv_growth_pct}% while remaining fully within signed user budget."
            )
        }
