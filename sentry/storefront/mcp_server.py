"""Sentry Storefront MCP Server.

Implements the Model Context Protocol (MCP) server exposing an agent-readable storefront.
Exposes:
  - list_products: browse available catalog
  - get_product: inspect product details
  - propose_purchase: submit purchase proposal to Sentry Policy Firewall

SECURITY INVARIANT:
  Does NOT expose any direct 'create_order' or payment-initiating tool to the agent.
"""
import json
import os
from typing import Dict, Any, Optional

try:
    from mcp.server.mcpserver import MCPServer as FastMCP
except ImportError:
    try:
        from mcp.server.fastmcp import FastMCP
    except ImportError:
        class FastMCP:
            def __init__(self, name: str): self.name = name
            def tool(self): return lambda fn: fn
            def run(self): pass

from sentry.mandate.schema import SpendingMandate, TransactionProposal
from sentry.mandate.signer import get_shared_signer
from sentry.policy.engine import PolicyEngine
from sentry.audit.logger import AuditLogger
from sentry.razorpay_client.executor import RazorpayExecutor
from sentry.storefront.service import StorefrontService
from sentry.storefront.catalog import get_catalog_product

# Initialize Sentry backend components
audit_logger = AuditLogger()
razorpay_executor = RazorpayExecutor()

# Active merchant public key for mandate verification (loads shared keypair if env var unset)
_shared_signer = get_shared_signer()
ACTIVE_PUBLIC_KEY = os.getenv("SENTRY_PUBLIC_KEY") or _shared_signer.public_key_hex
policy_engine = PolicyEngine(public_key_hex=ACTIVE_PUBLIC_KEY, state_store=audit_logger)
storefront_service = StorefrontService(policy_engine, audit_logger, razorpay_executor)

# FastMCP Server
mcp = FastMCP("sentry-storefront")


@mcp.tool()
def list_products() -> str:
    """List all available merchant products in the Sentry catalog with prices and categories."""
    products = storefront_service.list_products()
    return json.dumps(products, indent=2)


@mcp.tool()
def get_product(sku: str) -> str:
    """Retrieve detailed product specifications and description for a given SKU."""
    product = storefront_service.get_product(sku)
    if not product:
        return json.dumps({"error": f"Product with SKU '{sku}' not found."}, indent=2)
    return json.dumps(product, indent=2)


@mcp.tool()
def propose_purchase(
    mandate_json: str,
    sku: str,
    quantity: int,
    idempotency_key: str
) -> str:
    """Propose a purchase for evaluation by the Sentry Policy Firewall.
    
    The proposal will be evaluated against the signed user mandate.
    Only if approved will a Razorpay Test Mode order be created.
    
    Parameters:
      - mandate_json: JSON string of the signed user SpendingMandate
      - sku: The SKU of the product to purchase
      - quantity: The number of units to purchase
      - idempotency_key: Client-generated unique key to prevent duplicate orders
    """
    try:
        mandate_dict = json.loads(mandate_json)
        mandate = SpendingMandate(**mandate_dict)
    except Exception as e:
        return json.dumps({
            "decision": {
                "decision": "REJECTED",
                "reason_code": "INVALID_MANDATE_FORMAT",
                "reason": f"Failed to parse mandate JSON: {str(e)}",
                "razorpay_call_allowed": False
            },
            "order": None,
            "razorpay_called": False
        }, indent=2)

    # Resolve product to construct proposal
    product = get_catalog_product(sku)
    unit_price = product["price"] if product else 0
    item_name = product["name"] if product else "Unknown Item"
    category = product["category"] if product else "unknown"

    proposal = TransactionProposal(
        proposal_id=f"prop_{idempotency_key[:12]}",
        sku=sku,
        item_name=item_name,
        unit_price=unit_price,
        quantity=quantity,
        total_amount=unit_price * quantity,
        currency="INR",
        category=category,
        merchant_id=mandate.merchant_id,
        idempotency_key=idempotency_key,
        mandate_id=mandate.mandate_id
    )

    result = storefront_service.propose_purchase(mandate, proposal)
    return json.dumps(result, indent=2)


if __name__ == "__main__":
    mcp.run()
