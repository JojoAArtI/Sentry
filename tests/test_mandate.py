"""Tests for Mandate cryptographic signing, verification, and canonical serialization."""
from datetime import datetime, timezone
import pytest
from sentry.mandate.schema import SpendingMandate
from sentry.mandate.signer import MandateSigner
from sentry.mandate.verifier import MandateVerifier


def test_mandate_signing_and_verification(signer, valid_mandate):
    """Verifies that a signed mandate is successfully verified by MandateVerifier."""
    assert valid_mandate.signature is not None
    is_valid = MandateVerifier.verify(valid_mandate, signer.public_key_hex)
    assert is_valid is True


def test_tampered_amount_fails_verification(signer, valid_mandate):
    """Verifies that tampering with any mandate field invalidates the Ed25519 signature."""
    # Malicious actor tampers with spending limit
    valid_mandate.max_amount = 50000
    is_valid = MandateVerifier.verify(valid_mandate, signer.public_key_hex)
    assert is_valid is False


def test_tampered_category_fails_verification(signer, valid_mandate):
    """Verifies that tampering with allowed categories invalidates the signature."""
    valid_mandate.allowed_categories = ["gifts", "flowers", "electronics"]
    is_valid = MandateVerifier.verify(valid_mandate, signer.public_key_hex)
    assert is_valid is False


def test_wrong_public_key_fails_verification(valid_mandate):
    """Verifies that verifying with a different keypair's public key fails."""
    different_signer = MandateSigner()
    is_valid = MandateVerifier.verify(valid_mandate, different_signer.public_key_hex)
    assert is_valid is False


def test_missing_signature_fails_verification(signer, valid_mandate):
    """Verifies that a mandate with no signature fails verification."""
    valid_mandate.signature = None
    is_valid = MandateVerifier.verify(valid_mandate, signer.public_key_hex)
    assert is_valid is False


def test_corrupt_signature_hex_fails_verification(signer, valid_mandate):
    """Verifies that malformed or corrupted signature hex does not crash and returns False."""
    valid_mandate.signature = "deadbeef" * 8
    is_valid = MandateVerifier.verify(valid_mandate, signer.public_key_hex)
    assert is_valid is False
