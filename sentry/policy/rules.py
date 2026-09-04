"""Data models and reason codes for deterministic policy decisions."""
from enum import Enum
from typing import Optional, Dict, Any
from pydantic import BaseModel, Field


class PolicyVerdict(str, Enum):
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    REQUIRES_HUMAN_APPROVAL = "REQUIRES_HUMAN_APPROVAL"


class PolicyReasonCode(str, Enum):
    WITHIN_MANDATE = "WITHIN_MANDATE"
    INVALID_SIGNATURE = "INVALID_SIGNATURE"
    MANDATE_EXPIRED = "MANDATE_EXPIRED"
    MERCHANT_MISMATCH = "MERCHANT_MISMATCH"
    CURRENCY_MISMATCH = "CURRENCY_MISMATCH"
    CATEGORY_DISALLOWED = "CATEGORY_DISALLOWED"
    QUANTITY_EXCEEDS_LIMIT = "QUANTITY_EXCEEDS_LIMIT"
    AMOUNT_EXCEEDS_LIMIT = "AMOUNT_EXCEEDS_LIMIT"
    MANDATE_ALREADY_USED = "MANDATE_ALREADY_USED"
    IDEMPOTENT_REPLAY = "IDEMPOTENT_REPLAY"
    HUMAN_APPROVAL_THRESHOLD_EXCEEDED = "HUMAN_APPROVAL_THRESHOLD_EXCEEDED"
    PRODUCT_NOT_FOUND = "PRODUCT_NOT_FOUND"
    PRICE_TAMPERING_DETECTED = "PRICE_TAMPERING_DETECTED"


class PolicyDecision(BaseModel):
    """Deterministic result of the Sentry Policy Firewall evaluation."""
    decision: PolicyVerdict
    reason_code: PolicyReasonCode
    reason: str
    razorpay_call_allowed: bool = False
    details: Dict[str, Any] = Field(default_factory=dict)
