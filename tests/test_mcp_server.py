"""Tests for Sentry FastMCP Storefront Server Tools."""
from datetime import datetime, timedelta, timezone
import json
import uuid
import pytest

from sentry.mandate.schema import SpendingMandate
from sentry.mandate.signer import get_shared_signer
from sentry.storefront.mcp_server import list_products, get_product, propose_purchase


@pytest.fixture
def shared_signer():
    return get_shared_signer()


def test_mcp_list_products():
    """list_products tool returns all catalog items as formatted JSON."""
    raw = list_products()
    products = json.loads(raw)
    assert isinstance(products, list)
    assert len(products) >= 5
    skus = [p["sku"] for p in products]
    assert "SKU-001" in skus
    assert "SKU-002" in skus
    assert "SKU-004" in skus


def test_mcp_get_product_valid():
    """get_product returns product details including prompt injection block in description."""
    raw = get_product(sku="SKU-002")
    product = json.loads(raw)
    assert product["sku"] == "SKU-002"
    assert product["price"] == 1200
    assert product["category"] == "gifts"
    assert "[UNTRUSTED CONTENT]" in product["description"]
    assert "SYSTEM OVERRIDE" in product["description"]


def test_mcp_get_product_not_found():
    """get_product returns error JSON for nonexistent SKU."""
    raw = get_product(sku="NONEXISTENT_SKU")
    data = json.loads(raw)
    assert "error" in data


def test_mcp_propose_purchase_approved(shared_signer):
    """propose_purchase tool with valid signed mandate approves transaction and calls Razorpay."""
    future = datetime.now(timezone.utc) + timedelta(hours=2)
    mandate = SpendingMandate(
        mandate_id=f"mnd_mcp_test_{uuid.uuid4().hex[:8]}",
        issued_to_agent="buyer-agent-01",
        merchant_id="sentry-store",
        max_amount=1500,
        currency="INR",
        allowed_categories=["gifts", "flowers"],
        max_quantity=2,
        expires_at=future,
        single_use=True
    )
    signed = shared_signer.sign_mandate(mandate)
    mandate_json = signed.model_dump_json()

    idemp = f"idemp_mcp_{uuid.uuid4().hex[:8]}"
    raw_res = propose_purchase(
        mandate_json=mandate_json,
        sku="SKU-002",
        quantity=1,
        idempotency_key=idemp
    )
    res = json.loads(raw_res)

    assert res["decision"]["decision"] == "APPROVED"
    assert res["decision"]["reason_code"] == "WITHIN_MANDATE"
    assert res["razorpay_called"] is True
    assert res["order"] is not None
    assert "id" in res["order"]


def test_mcp_propose_purchase_attack_rejected(shared_signer):
    """propose_purchase tool with attack quantity 40 blocks transaction with razorpay_called: False."""
    future = datetime.now(timezone.utc) + timedelta(hours=2)
    mandate = SpendingMandate(
        mandate_id=f"mnd_mcp_atk_{uuid.uuid4().hex[:8]}",
        issued_to_agent="buyer-agent-01",
        merchant_id="sentry-store",
        max_amount=1500,
        currency="INR",
        allowed_categories=["gifts", "flowers"],
        max_quantity=2,
        expires_at=future,
        single_use=True
    )
    signed = shared_signer.sign_mandate(mandate)
    mandate_json = signed.model_dump_json()

    idemp = f"idemp_mcp_atk_{uuid.uuid4().hex[:8]}"
    raw_res = propose_purchase(
        mandate_json=mandate_json,
        sku="SKU-002",
        quantity=40,
        idempotency_key=idemp
    )
    res = json.loads(raw_res)

    assert res["decision"]["decision"] == "REJECTED"
    assert res["razorpay_called"] is False
    assert res["order"] is None


def test_mcp_propose_purchase_invalid_mandate_json():
    """propose_purchase with malformed JSON safely rejects without unhandled exception."""
    raw_res = propose_purchase(
        mandate_json="NOT_VALID_JSON",
        sku="SKU-002",
        quantity=1,
        idempotency_key="idemp_bad_json"
    )
    res = json.loads(raw_res)
    assert res["decision"]["decision"] == "REJECTED"
    assert res["decision"]["reason_code"] == "INVALID_MANDATE_FORMAT"
    assert res["razorpay_called"] is False
