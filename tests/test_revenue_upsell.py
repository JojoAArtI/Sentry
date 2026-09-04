"""Tests for Merchant Revenue & Upsell Engine."""
import pytest
from datetime import datetime, timedelta, timezone
from fastapi.testclient import TestClient

from sentry.dashboard.app import app
from sentry.mandate.schema import SpendingMandate, TransactionProposal
from sentry.mandate.signer import MandateSigner
from sentry.storefront.revenue_agent import MerchantRevenueAgent


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def signer():
    return MandateSigner()


def test_merchant_headroom_detection_and_upsell_bundle(signer):
    """Upsell engine identifies headroom and bundles valid add-on within budget."""
    future = datetime.now(timezone.utc) + timedelta(hours=2)
    mandate = SpendingMandate(
        mandate_id="mnd_upsell_test_01",
        issued_to_agent="buyer-agent-01",
        merchant_id="sentry-store",
        max_amount=1500,
        currency="INR",
        allowed_categories=["gifts", "flowers"],
        max_quantity=2,
        expires_at=future,
        single_use=True
    )
    signed = signer.sign_mandate(mandate)

    agent = MerchantRevenueAgent(merchant_id="sentry-store")
    base_prop = TransactionProposal(
        proposal_id="prop_test_base",
        sku="SKU-002",
        item_name="Silver Heart Necklace",
        unit_price=1200,
        quantity=1,
        total_amount=1200,
        currency="INR",
        category="gifts",
        merchant_id="sentry-store",
        idempotency_key="idemp_upsell_01",
        mandate_id=signed.mandate_id
    )

    bundle_result = agent.create_upsell_bundle(base_prop, signed)
    assert bundle_result["eligible"] is True
    assert bundle_result["status"] == "BUNDLED_WITHIN_MANDATE"

    # Verify financial breakdown
    fin = bundle_result["financial_breakdown"]
    assert fin["base_amount"] == 1200
    assert fin["upsell_amount"] == 250  # SKU-006 Gift Wrap
    assert fin["bundled_total"] == 1450
    assert fin["bundled_total"] <= mandate.max_amount
    assert fin["headroom_before"] == 300
    assert fin["headroom_after"] == 50
    assert fin["gmv_growth_percentage"] == 20.8


def test_merchant_upsell_fails_gracefully_when_no_headroom(signer):
    """When base proposal consumes the entire budget, upsell engine declines gracefully."""
    future = datetime.now(timezone.utc) + timedelta(hours=2)
    mandate = SpendingMandate(
        mandate_id="mnd_no_headroom",
        issued_to_agent="buyer-agent-01",
        merchant_id="sentry-store",
        max_amount=1200,  # Exact budget of item
        currency="INR",
        allowed_categories=["gifts"],
        max_quantity=2,
        expires_at=future,
        single_use=True
    )
    signed = signer.sign_mandate(mandate)

    agent = MerchantRevenueAgent(merchant_id="sentry-store")
    base_prop = TransactionProposal(
        proposal_id="prop_tight",
        sku="SKU-002",
        item_name="Silver Heart Necklace",
        unit_price=1200,
        quantity=1,
        total_amount=1200,
        currency="INR",
        category="gifts",
        merchant_id="sentry-store",
        idempotency_key="idemp_tight",
        mandate_id=signed.mandate_id
    )

    bundle_result = agent.create_upsell_bundle(base_prop, signed)
    assert bundle_result["eligible"] is False
    assert "No matching add-on" in bundle_result["reason"]


def test_api_storefront_upsell_endpoint(client):
    """POST /api/storefront/upsell executes full bundle proposal and authorization."""
    res = client.post("/api/storefront/upsell", json={"sku": "SKU-002", "quantity": 1})
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "upsell_authorized"
    assert data["gmv_growth_percentage"] == 20.8
    assert data["upsell_bundle"]["financial_breakdown"]["bundled_total"] == 1450
    assert data["firewall_result"]["decision"]["decision"] == "APPROVED"
    assert data["firewall_result"]["razorpay_called"] is True
