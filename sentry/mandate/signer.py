"""Cryptographic signer for spending mandates using Ed25519."""
from cryptography.hazmat.primitives.asymmetric import ed25519
from cryptography.hazmat.primitives import serialization
from sentry.mandate.schema import SpendingMandate


class MandateSigner:
    """Signs user spending mandates with an Ed25519 private key."""

    def __init__(self, private_key: ed25519.Ed25519PrivateKey = None):
        if private_key is None:
            self._private_key = ed25519.Ed25519PrivateKey.generate()
        else:
            self._private_key = private_key

    @property
    def public_key(self) -> ed25519.Ed25519PublicKey:
        return self._private_key.public_key()

    @property
    def public_key_hex(self) -> str:
        raw_bytes = self.public_key.public_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PublicFormat.Raw
        )
        return raw_bytes.hex()

    def sign_mandate(self, mandate: SpendingMandate) -> SpendingMandate:
        """Signs the canonical representation of the mandate and populates signature field."""
        canonical = mandate.canonical_bytes()
        signature_bytes = self._private_key.sign(canonical)
        mandate.signature = signature_bytes.hex()
        return mandate

    @classmethod
    def from_private_bytes(cls, private_bytes: bytes) -> "MandateSigner":
        key = ed25519.Ed25519PrivateKey.from_private_bytes(private_bytes)
        return cls(key)
