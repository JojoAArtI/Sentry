"""Cryptographic verifier for spending mandates using Ed25519."""
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric import ed25519
from sentry.mandate.schema import SpendingMandate


class MandateVerifier:
    """Verifies Ed25519 signatures on spending mandates."""

    @staticmethod
    def verify(mandate: SpendingMandate, public_key_hex: str) -> bool:
        """Verifies that mandate.signature matches public_key_hex over mandate.canonical_bytes().
        
        Returns True if valid, False otherwise.
        """
        if not mandate.signature:
            return False

        try:
            public_key_bytes = bytes.fromhex(public_key_hex)
            public_key = ed25519.Ed25519PublicKey.from_public_bytes(public_key_bytes)
            
            signature_bytes = bytes.fromhex(mandate.signature)
            canonical = mandate.canonical_bytes()
            
            public_key.verify(signature_bytes, canonical)
            return True
        except (ValueError, InvalidSignature, Exception):
            return False
