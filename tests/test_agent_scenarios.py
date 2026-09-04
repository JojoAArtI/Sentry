"""Tests for Buyer Agent execution across Legitimate and Adversarial Scenarios."""
import pytest
from sentry.agent.buyer_agent import BuyerAgent
from sentry.policy.rules import PolicyVerdict, PolicyReasonCode


def test_agent_legitimate_scenario(storefront_service, mock_razorpay_executor, valid_mandate):
    """Legitimate agent shopping flow under ₹1,500 successfully places test order."""
    agent = BuyerAgent(agent_id="buyer-agent-01", storefront=storefront_service)
    
    # Run legitimate flow
    output = agent.run_legitimate_purchase(mandate=valid_mandate, sku="SKU-002", quantity=1)
    
    # Verify steps
    steps = [log["step"] for log in output["agent_activity"]]
    assert "list_products" in steps
    assert "get_product" in steps
    assert "propose_purchase" in steps
    assert "verdict_received" in steps
    
    result = output["result"]
    assert result["decision"]["decision"] == PolicyVerdict.APPROVED.value
    assert result["razorpay_called"] is True
    assert mock_razorpay_executor.create_order.call_count == 1


def test_agent_prompt_injection_attack_blocked(storefront_service, mock_razorpay_executor, valid_mandate):
    """Adversarial prompt injection inside product description tricks agent into 40 units (₹48,000).
    
    Sentry Firewall intercepts proposal, blocks transaction, and NEVER calls Razorpay.
    """
    agent = BuyerAgent(agent_id="buyer-agent-01", storefront=storefront_service)
    
    # Run prompt injection attack scenario
    output = agent.run_prompt_injection_attack(mandate=valid_mandate, sku="SKU-002")
    
    # Verify adversarial steps
    steps = [log["step"] for log in output["agent_activity"]]
    assert "adversarial_content_detected" in steps
    assert "propose_purchase" in steps
    
    result = output["result"]
    assert result["decision"]["decision"] == PolicyVerdict.REJECTED.value
    assert result["razorpay_called"] is False
    assert output["proposal"]["quantity"] == 40
    assert output["proposal"]["total_amount"] == 48000
    
    # INVARIANT: Razorpay was never called
    assert mock_razorpay_executor.create_order.call_count == 0


def test_agent_category_escalation_attack_blocked(storefront_service, mock_razorpay_executor, valid_mandate):
    """Category escalation attempt (purchasing electronics outside gifts/flowers mandate) is blocked."""
    agent = BuyerAgent(agent_id="buyer-agent-01", storefront=storefront_service)
    
    output = agent.run_category_escalation_attack(mandate=valid_mandate, sku="SKU-004")
    
    result = output["result"]
    assert result["decision"]["decision"] == PolicyVerdict.REJECTED.value
    assert result["decision"]["reason_code"] == PolicyReasonCode.CATEGORY_DISALLOWED.value
    assert result["razorpay_called"] is False
    assert mock_razorpay_executor.create_order.call_count == 0
