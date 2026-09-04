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


def get_shared_signer(key_file: str = "sentry/mandate/demo_keys.json") -> MandateSigner:
    """Returns a shared MandateSigner, loading from disk or generating and saving if missing.
    
    Guarantees that FastMCP, dashboard, tests, and CLI runners share the exact same keypair.
    """
    import json
    from pathlib import Path

    path = Path(key_file)
    if path.exists():
        try:
            with open(path, "r") as f:
                data = json.load(f)
                priv_bytes = bytes.fromhex(data["private_key_hex"])
                return MandateSigner.from_private_bytes(priv_bytes)
        except Exception:
            pass

    # Generate fresh keypair and persist
    signer = MandateSigner()
    path.parent.mkdir(parents=True, exist_ok=True)
    raw_priv = signer._private_key.private_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PrivateFormat.Raw,
        encryption_algorithm=serialization.NoEncryption()
    )
    with open(path, "w") as f:
        json.dump({
            "private_key_hex": raw_priv.hex(),
            "public_key_hex": signer.public_key_hex
        }, f, indent=2)
    return signer
