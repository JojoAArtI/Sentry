from datetime import datetime, timezone
import json
from typing import List, Optional
from pydantic import BaseModel, Field, ConfigDict


class SpendingMandate(BaseModel):
    """Cryptographically signed user authorization bounding agent spending.
    
    This represents the explicit, bounded spending authority granted by the user.
    Untrusted model outputs cannot modify these bounds.
    """
    model_config = ConfigDict(extra="forbid")

    mandate_id: str = Field(..., description="Unique mandate identifier, e.g. mnd_demo_001")
    issued_to_agent: str = Field(..., description="Agent ID authorized to propose transactions")
    merchant_id: str = Field(default="sentry-store", description="Merchant where mandate is valid")
    max_amount: int = Field(..., gt=0, description="Maximum total transaction amount in INR")
    currency: str = Field(default="INR", description="Currency code (e.g. INR)")
    allowed_categories: List[str] = Field(default_factory=list, description="Whitelisted product categories")
    max_quantity: int = Field(default=1, gt=0, description="Maximum items per transaction")
    expires_at: datetime = Field(..., description="UTC ISO8601 expiration timestamp")
    single_use: bool = Field(default=True, description="Whether mandate is invalidated after one transaction")
    autonomous_threshold: Optional[int] = Field(
        default=None,
        description="Amount above which human approval is required even if <= max_amount"
    )
    signature: Optional[str] = Field(default=None, description="Hex-encoded Ed25519 signature over canonical JSON")

    def canonical_bytes(self) -> bytes:
        """Returns deterministic, canonical byte representation of mandate fields (excluding signature).
        
        Fields are alphabetically sorted and formatted without whitespace for cryptographic signing.
        """
        data = {
            "allowed_categories": sorted(self.allowed_categories),
            "autonomous_threshold": self.autonomous_threshold,
            "currency": self.currency,
            "expires_at": self.expires_at.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "issued_to_agent": self.issued_to_agent,
            "mandate_id": self.mandate_id,
            "max_amount": self.max_amount,
            "max_quantity": self.max_quantity,
            "merchant_id": self.merchant_id,
            "single_use": self.single_use,
        }
        return json.dumps(data, sort_keys=True, separators=(",", ":")).encode("utf-8")


class MandateSignature(BaseModel):
    """Signature payload containing the public key and Ed25519 signature."""
    public_key_hex: str
    signature_hex: str


class TransactionProposal(BaseModel):
    """Untrusted transaction proposed by an AI agent.
    
    The AI model proposes this transaction, but it is strictly treated as untrusted input.
    It MUST be authorized by the deterministic policy firewall before payment execution.
    """
    proposal_id: str
    sku: str
    item_name: str
    unit_price: int
    quantity: int
    total_amount: int
    currency: str = "INR"
    category: str
    merchant_id: str = "sentry-store"
    idempotency_key: str
    mandate_id: str
