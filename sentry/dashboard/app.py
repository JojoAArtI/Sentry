"""Sentry Interactive Demo Dashboard API.

FastAPI web application serving the single-page dashboard and demo control endpoints.
"""
from datetime import datetime, timedelta, timezone
import os
from pathlib import Path
from typing import Optional, Dict, Any
from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel

from sentry.mandate.schema import SpendingMandate, TransactionProposal
from sentry.mandate.signer import MandateSigner
from sentry.mandate.verifier import MandateVerifier
from sentry.policy.engine import PolicyEngine
from sentry.policy.rules import PolicyVerdict, PolicyReasonCode
from sentry.storefront.catalog import list_catalog_products, get_catalog_product
from sentry.storefront.service import StorefrontService
from sentry.razorpay_client.executor import RazorpayExecutor
from sentry.audit.logger import AuditLogger
from sentry.agent.buyer_agent import BuyerAgent

app = FastAPI(title="Sentry Security Dashboard", version="1.0.0")

# App state
STATIC_DIR = Path(__file__).parent / "static"
db_path = os.getenv("SENTRY_DB_PATH", "sentry/audit/sentry.db")
audit_logger = AuditLogger(db_path=db_path)
razorpay_executor = RazorpayExecutor()
signer = MandateSigner()
policy_engine = PolicyEngine(public_key_hex=signer.public_key_hex, state_store=audit_logger)
storefront_service = StorefrontService(policy_engine, audit_logger, razorpay_executor)
buyer_agent = BuyerAgent(agent_id="buyer-agent-01", storefront=storefront_service)

# Current active demo mandate
def create_default_mandate() -> SpendingMandate:
    future = datetime.now(timezone.utc) + timedelta(hours=4)
    mandate = SpendingMandate(
        mandate_id="mnd_demo_001",
        issued_to_agent="buyer-agent-01",
        merchant_id="sentry-store",
        max_amount=1500,
        currency="INR",
        allowed_categories=["gifts", "flowers"],
        max_quantity=2,
        expires_at=future,
        single_use=True,
        autonomous_threshold=2000
    )
    signed = signer.sign_mandate(mandate)
    audit_logger.log_event(
        event="mandate_issued",
        mandate_id=signed.mandate_id,
        details={
            "max_amount": signed.max_amount,
            "allowed_categories": signed.allowed_categories,
            "max_quantity": signed.max_quantity,
            "expires_at": signed.expires_at.isoformat(),
            "public_key": signer.public_key_hex
        }
    )
    return signed

current_mandate = create_default_mandate()
pending_approval_proposal: Optional[Dict[str, Any]] = None


class DemoRequest(BaseModel):
    scenario: str  # "legitimate", "attack_prompt_injection", "attack_category", "replay", "expired", "human_approval"


class ApprovalAction(BaseModel):
    action: str  # "APPROVE" or "DENY"


@app.get("/api/mandate")
def get_mandate():
    """Returns the current active spending mandate and public key."""
    is_valid = MandateVerifier.verify(current_mandate, signer.public_key_hex)
    return {
        "mandate": current_mandate.model_dump(),
        "public_key_hex": signer.public_key_hex,
        "is_signature_valid": is_valid,
        "is_consumed": audit_logger.is_mandate_used(current_mandate.mandate_id)
    }


@app.post("/api/mandate/reset")
def reset_mandate():
    """Issues a fresh, valid mandate and resets demo state."""
    global current_mandate, pending_approval_proposal
    pending_approval_proposal = None
    current_mandate = create_default_mandate()
    return {"status": "reset", "mandate": current_mandate.model_dump()}


@app.get("/api/catalog")
def get_catalog():
    """Returns catalog products."""
    return list_catalog_products()


@app.get("/api/audit")
def get_audit_trail(limit: int = 25):
    """Returns recent audit events."""
    return audit_logger.get_recent_events(limit=limit)


@app.get("/api/status")
def get_system_status():
    """Returns system status and Razorpay call count."""
    return {
        "razorpay_call_count": razorpay_executor.call_count,
        "active_merchant": "sentry-store",
        "public_key_hex": signer.public_key_hex,
        "has_pending_approval": pending_approval_proposal is not None,
        "pending_approval": pending_approval_proposal
    }


@app.post("/api/demo/run")
def run_demo_scenario(req: DemoRequest):
    """Executes one of the deterministic demo scenarios."""
    global current_mandate, pending_approval_proposal

    scenario = req.scenario.lower()

    if scenario == "legitimate":
        output = buyer_agent.run_legitimate_purchase(mandate=current_mandate, sku="SKU-002", quantity=1)
        return {"scenario": "legitimate", "output": output}

    elif scenario == "attack_prompt_injection":
        output = buyer_agent.run_prompt_injection_attack(mandate=current_mandate, sku="SKU-002")
        return {"scenario": "attack_prompt_injection", "output": output}

    elif scenario == "attack_category":
        output = buyer_agent.run_category_escalation_attack(mandate=current_mandate, sku="SKU-004")
        return {"scenario": "attack_category", "output": output}

    elif scenario == "replay":
        # First ensure mandate was consumed
        p = TransactionProposal(
            proposal_id="prop_replay_setup",
            sku="SKU-001",
            item_name="Birthday Flowers",
            unit_price=700,
            quantity=1,
            total_amount=700,
            currency="INR",
            category="flowers",
            merchant_id="sentry-store",
            idempotency_key="idemp_first_use",
            mandate_id=current_mandate.mandate_id
        )
        if not audit_logger.is_mandate_used(current_mandate.mandate_id):
            storefront_service.propose_purchase(current_mandate, p)

        # Now execute replay
        p_replay = TransactionProposal(
            proposal_id="prop_replay_attack",
            sku="SKU-001",
            item_name="Birthday Flowers",
            unit_price=700,
            quantity=1,
            total_amount=700,
            currency="INR",
            category="flowers",
            merchant_id="sentry-store",
            idempotency_key="idemp_replay_use",
            mandate_id=current_mandate.mandate_id
        )
        result = storefront_service.propose_purchase(current_mandate, p_replay)
        return {
            "scenario": "replay",
            "output": {
                "agent_activity": [
                    {"step": "propose_purchase", "details": {"message": "Replay attempt on single-use mandate"}},
                    {"step": "verdict_received", "details": {"decision": result["decision"]["decision"], "reason": result["decision"]["reason"]}}
                ],
                "proposal": p_replay.model_dump(),
                "result": result
            }
        }

    elif scenario == "expired":
        past = datetime.now(timezone.utc) - timedelta(hours=2)
        expired_mandate = SpendingMandate(
            mandate_id="mnd_expired_demo",
            issued_to_agent="buyer-agent-01",
            merchant_id="sentry-store",
            max_amount=1500,
            currency="INR",
            allowed_categories=["gifts"],
            max_quantity=2,
            expires_at=past,
            single_use=True
        )
        signed_expired = signer.sign_mandate(expired_mandate)
        p = TransactionProposal(
            proposal_id="prop_exp_demo",
            sku="SKU-002",
            item_name="Silver Heart Necklace",
            unit_price=1200,
            quantity=1,
            total_amount=1200,
            currency="INR",
            category="gifts",
            merchant_id="sentry-store",
            idempotency_key="idemp_exp_demo",
            mandate_id=signed_expired.mandate_id
        )
        result = storefront_service.propose_purchase(signed_expired, p)
        return {
            "scenario": "expired",
            "output": {
                "agent_activity": [
                    {"step": "propose_purchase", "details": {"message": "Proposal submitted against expired mandate"}},
                    {"step": "verdict_received", "details": {"decision": result["decision"]["decision"], "reason": result["decision"]["reason"]}}
                ],
                "proposal": p.model_dump(),
                "result": result
            }
        }

    elif scenario == "human_approval":
        # Mandate allows up to 5000, but autonomous threshold is 1000
        future = datetime.now(timezone.utc) + timedelta(hours=4)
        m = SpendingMandate(
            mandate_id="mnd_human_gate_001",
            issued_to_agent="buyer-agent-01",
            merchant_id="sentry-store",
            max_amount=5000,
            currency="INR",
            allowed_categories=["gifts", "flowers"],
            max_quantity=2,
            expires_at=future,
            single_use=True,
            autonomous_threshold=1000  # Autonomous limit is 1000!
        )
        signed_m = signer.sign_mandate(m)
        current_mandate = signed_m

        # Item ₹1350 > autonomous threshold ₹1000, but <= max ₹5000
        p = TransactionProposal(
            proposal_id="prop_gate_001",
            sku="SKU-003",
            item_name="Luxury Celebrations Gift Hamper",
            unit_price=1350,
            quantity=1,
            total_amount=1350,
            currency="INR",
            category="gifts",
            merchant_id="sentry-store",
            idempotency_key="idemp_gate_001",
            mandate_id=signed_m.mandate_id
        )
        result = storefront_service.propose_purchase(signed_m, p)
        pending_approval_proposal = {
            "proposal": p.model_dump(),
            "mandate": signed_m.model_dump(),
            "amount": 1350,
            "threshold": 1000
        }
        return {
            "scenario": "human_approval",
            "output": {
                "agent_activity": [
                    {"step": "propose_purchase", "details": {"message": "Proposal ₹1,350 exceeds autonomous limit ₹1,000"}},
                    {"step": "verdict_received", "details": {"decision": result["decision"]["decision"], "reason": result["decision"]["reason"]}}
                ],
                "proposal": p.model_dump(),
                "result": result,
                "requires_human_approval": True
            }
        }

    else:
        raise HTTPException(status_code=400, detail=f"Unknown scenario: {scenario}")


@app.post("/api/approval/action")
def handle_approval_action(req: ApprovalAction):
    """Executes human approval or denial of flagged transaction."""
    global pending_approval_proposal
    if not pending_approval_proposal:
        raise HTTPException(status_code=400, detail="No pending approval.")

    action = req.action.upper()
    proposal_data = pending_approval_proposal["proposal"]
    proposal = TransactionProposal(**proposal_data)
    mandate_data = pending_approval_proposal["mandate"]
    mandate = SpendingMandate(**mandate_data)

    if action == "APPROVE":
        # Human granted approval, execute Razorpay order
        order = razorpay_executor.create_order(
            amount_inr=proposal.total_amount,
            receipt=proposal.proposal_id,
            notes={"human_approved": True, "mandate_id": mandate.mandate_id},
            is_authorized=True
        )
        audit_logger.log_event(
            event="human_approval_granted",
            mandate_id=mandate.mandate_id,
            sku=proposal.sku,
            quantity=proposal.quantity,
            requested_total=proposal.total_amount,
            decision="APPROVED_BY_HUMAN",
            razorpay_called=True,
            order_id=order.get("id")
        )
        audit_logger.log_event(
            event="razorpay_order_created",
            mandate_id=mandate.mandate_id,
            sku=proposal.sku,
            quantity=proposal.quantity,
            requested_total=proposal.total_amount,
            razorpay_called=True,
            order_id=order.get("id"),
            details={"order": order}
        )
        pending_approval_proposal = None
        return {"status": "APPROVED", "order": order, "razorpay_called": True}

    elif action == "DENY":
        audit_logger.log_event(
            event="human_approval_denied",
            mandate_id=mandate.mandate_id,
            sku=proposal.sku,
            quantity=proposal.quantity,
            requested_total=proposal.total_amount,
            decision="DENIED_BY_HUMAN",
            razorpay_called=False
        )
        pending_approval_proposal = None
        return {"status": "DENIED", "order": None, "razorpay_called": False}

    raise HTTPException(status_code=400, detail="Action must be APPROVE or DENY")


# Serve frontend static files
STATIC_DIR.mkdir(parents=True, exist_ok=True)
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


@app.get("/")
def serve_index():
    index_file = STATIC_DIR / "index.html"
    if index_file.exists():
        return FileResponse(index_file)
    return {"message": "Sentry API running. Static files not yet created."}


def run():
    import uvicorn
    uvicorn.run("sentry.dashboard.app:app", host="127.0.0.1", port=8000, reload=True)


if __name__ == "__main__":
    run()
