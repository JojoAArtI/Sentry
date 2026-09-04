"""Razorpay Payment Executor.

Executes orders in Razorpay Test Mode ONLY when explicitly permitted by Sentry Policy Engine.
CRITICAL INVARIANT: Never called for rejected or unauthorized transactions.
"""
import os
import time
import uuid
from typing import Optional, Dict, Any
from dotenv import load_dotenv

load_dotenv()


class SecurityViolationError(Exception):
    """Raised when an attempt is made to call Razorpay without policy authorization."""
    pass


class RazorpayExecutor:
    """Razorpay Test Mode Order Executor with call tracking and safety gates."""

    def __init__(self, key_id: Optional[str] = None, key_secret: Optional[str] = None):
        self.key_id = key_id or os.getenv("RAZORPAY_KEY_ID", "")
        self.key_secret = key_secret or os.getenv("RAZORPAY_KEY_SECRET", "")
        self.call_count = 0
        self._client = None

        if self.key_id and self.key_secret:
            try:
                import razorpay
                self._client = razorpay.Client(auth=(self.key_id, self.key_secret))
            except Exception:
                self._client = None

    def create_order(
        self,
        amount_inr: int,
        receipt: str,
        notes: Optional[Dict[str, Any]] = None,
        is_authorized: bool = False
    ) -> Dict[str, Any]:
        """Creates a Razorpay Test Mode Order.
        
        CRITICAL GUARD:
        is_authorized MUST be True (set by PolicyEngine). If False, raises SecurityViolationError.
        """
        if not is_authorized:
            raise SecurityViolationError(
                "CRITICAL SECURITY VIOLATION: Attempted to call Razorpay without policy authorization!"
            )

        self.call_count += 1
        amount_paise = amount_inr * 100

        # If live Razorpay credentials are provided in .env, call Razorpay API
        if self._client:
            try:
                order_payload = {
                    "amount": amount_paise,
                    "currency": "INR",
                    "receipt": receipt,
                    "notes": notes or {}
                }
                return self._client.order.create(order_payload)
            except Exception as e:
                # If network or credentials fail, return error with context
                return {
                    "error": str(e),
                    "id": f"order_rzp_error_{uuid.uuid4().hex[:8]}",
                    "status": "failed",
                    "amount": amount_paise,
                    "currency": "INR",
                    "receipt": receipt,
                }

        # Otherwise, in Test/Simulated mode (offline hackathon reproducible mode):
        test_order_id = f"order_test_{uuid.uuid4().hex[:14]}"
        return {
            "id": test_order_id,
            "entity": "order",
            "amount": amount_paise,
            "amount_paid": 0,
            "amount_due": amount_paise,
            "currency": "INR",
            "receipt": receipt,
            "offer_id": None,
            "status": "created",
            "attempts": 0,
            "notes": notes or {},
            "created_at": int(time.time()),
            "mode": "test"
        }

    def verify_payment_signature(
        self,
        order_id: str,
        payment_id: str,
        signature: str
    ) -> bool:
        """Verifies Razorpay payment signature using HMAC-SHA256.
        
        Formula:
          HMAC-SHA256(order_id + '|' + payment_id, secret) == signature
        """
        import hmac
        import hashlib

        secret = self.key_secret or "test_secret_sentry_2026"
        msg = f"{order_id}|{payment_id}".encode("utf-8")
        expected = hmac.new(secret.encode("utf-8"), msg, hashlib.sha256).hexdigest()
        return hmac.compare_digest(expected, signature)

    def generate_test_signature(self, order_id: str, payment_id: str) -> str:
        """Generates valid HMAC-SHA256 signature for test/simulation checkouts."""
        import hmac
        import hashlib

        secret = self.key_secret or "test_secret_sentry_2026"
        msg = f"{order_id}|{payment_id}".encode("utf-8")
        return hmac.new(secret.encode("utf-8"), msg, hashlib.sha256).hexdigest()
