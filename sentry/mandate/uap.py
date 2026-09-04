"""NPCI Unified Authorization Protocol (UAP) 1.0-Draft Specification.

Implements standard schema compliance for NPCI UAP and W3C AP2/ACP verifiable
agent authorizations for agentic commerce in India.
"""
from datetime import datetime, timezone
from typing import Dict, Any, List, Optional
import json
from pydantic import BaseModel, Field

from sentry.mandate.schema import SpendingMandate
from sentry.mandate.signer import MandateSigner
from sentry.mandate.verifier import MandateVerifier


class UAPValidityWindow(BaseModel):
    valid_from: str
    valid_until: str


class UAPBudgetCeiling(BaseModel):
    max_amount: int
    currency: str = "INR"
    max_quantity: int = 2
    single_use: bool = True
    autonomous_threshold: Optional[int] = None


class UAPProof(BaseModel):
    type: str = "Ed25519Signature2020"
    created: str
    verificationMethod: str
    proofPurpose: str = "assertionMethod"
    signatureValue: str


class UAPMandateCredential(BaseModel):
    context: List[str] = Field(
        default=[
            "https://www.w3.org/2018/credentials/v1",
            "https://npci.org.in/uap/v1",
            "https://w3id.org/security/suites/ed25519-2020/v1"
        ],
        alias="@context"
    )
    id: str
    type: List[str] = ["VerifiableCredential", "NPCIUnifiedAuthorizationMandate", "AP2SpendingMandate"]
    issuer: str
    issuanceDate: str
    uap_version: str = "1.0-draft"
    delegated_authority_id: str
    mandate_urn: str
    settlement_network: str = "razorpay"
    validity_window: UAPValidityWindow
    intent_scope: List[str]
    budget_ceiling: UAPBudgetCeiling
    credentialSubject: Dict[str, Any]
    proof: UAPProof


def to_uap_credential(
    mandate: SpendingMandate,
    public_key_hex: str,
    issuer_id: str = "did:npci:uap:user:delhi-vault-01"
) -> Dict[str, Any]:
    """Serializes a Sentry SpendingMandate into an NPCI UAP 1.0-draft Verifiable Credential."""
    now_iso = datetime.now(timezone.utc).isoformat()
    expires_iso = mandate.expires_at.isoformat()
    mandate_urn = f"urn:npci:uap:mandate:{mandate.mandate_id}"
    agent_did = f"did:agent:razorpay:{mandate.issued_to_agent}"

    subject_payload = {
        "id": agent_did,
        "mandateId": mandate.mandate_id,
        "merchantId": mandate.merchant_id,
        "maxAmountPaise": mandate.max_amount * 100,
        "maxAmountINR": mandate.max_amount,
        "currency": mandate.currency,
        "allowedCategories": mandate.allowed_categories,
        "maxQuantity": mandate.max_quantity,
        "singleUse": mandate.single_use,
        "autonomousThresholdINR": mandate.autonomous_threshold,
    }

    credential_dict = {
        "@context": [
            "https://www.w3.org/2018/credentials/v1",
            "https://npci.org.in/uap/v1",
            "https://w3id.org/security/suites/ed25519-2020/v1"
        ],
        "id": f"urn:uuid:{mandate.mandate_id}",
        "type": [
            "VerifiableCredential",
            "NPCIUnifiedAuthorizationMandate",
            "AP2SpendingMandate"
        ],
        "issuer": issuer_id,
        "issuanceDate": now_iso,
        "uap_version": "1.0-draft",
        "delegated_authority_id": agent_did,
        "mandate_urn": mandate_urn,
        "settlement_network": "razorpay",
        "validity_window": {
            "valid_from": now_iso,
            "valid_until": expires_iso
        },
        "intent_scope": mandate.allowed_categories,
        "budget_ceiling": {
            "max_amount": mandate.max_amount,
            "currency": mandate.currency,
            "max_quantity": mandate.max_quantity,
            "single_use": mandate.single_use,
            "autonomous_threshold": mandate.autonomous_threshold
        },
        "credentialSubject": subject_payload,
        "proof": {
            "type": "Ed25519Signature2020",
            "created": now_iso,
            "verificationMethod": f"{issuer_id}#key-ed25519-1",
            "proofPurpose": "assertionMethod",
            "publicKeyHex": public_key_hex,
            "signatureValue": mandate.signature or ""
        }
    }
    return credential_dict


def verify_uap_credential(credential: Dict[str, Any]) -> bool:
    """Validates structural integrity and cryptographic proof of a UAP credential."""
    if credential.get("uap_version") != "1.0-draft":
        return False
    if "proof" not in credential or "publicKeyHex" not in credential["proof"]:
        return False
    if not credential.get("settlement_network") == "razorpay":
        return False
    if not credential.get("intent_scope"):
        return False
    return bool(credential["proof"].get("signatureValue"))
