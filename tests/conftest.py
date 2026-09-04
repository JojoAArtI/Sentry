"""Pytest fixtures for Sentry test suite."""
import os
import pytest
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

from sentry.mandate.schema import SpendingMandate, TransactionProposal
from sentry.mandate.signer import MandateSigner
from sentry.mandate.verifier import MandateVerifier
from sentry.policy.engine import PolicyEngine
from sentry.audit.logger import AuditLogger
from sentry.razorpay_client.executor import RazorpayExecutor
from sentry.storefront.service import StorefrontService


@pytest.fixture
def test_db_path(tmp_path):
    """Provides a temporary SQLite database path for isolated tests."""
    return str(tmp_path / "test_sentry.db")


@pytest.fixture
def audit_logger(test_db_path):
    """Provides clean audit logger instance."""
    return AuditLogger(db_path=test_db_path)


@pytest.fixture
def signer():
    """Provides an Ed25519 signer."""
    return MandateSigner()


@pytest.fixture
def public_key_hex(signer):
    """Provides the public key hex corresponding to the test signer."""
    return signer.public_key_hex


@pytest.fixture
def valid_mandate(signer):
    """Creates and cryptographically signs a valid mandate."""
    future = datetime.now(timezone.utc) + timedelta(hours=2)
    mandate = SpendingMandate(
        mandate_id="mnd_test_001",
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
    return signer.sign_mandate(mandate)


@pytest.fixture
def expired_mandate(signer):
    """Creates and signs an expired mandate."""
    past = datetime.now(timezone.utc) - timedelta(hours=1)
    mandate = SpendingMandate(
        mandate_id="mnd_expired_001",
        issued_to_agent="buyer-agent-01",
        merchant_id="sentry-store",
        max_amount=1500,
        currency="INR",
        allowed_categories=["gifts", "flowers"],
        max_quantity=2,
        expires_at=past,
        single_use=True
    )
    return signer.sign_mandate(mandate)


@pytest.fixture
def policy_engine(public_key_hex, audit_logger):
    """Provides PolicyEngine initialized with test public key and audit logger state store."""
    return PolicyEngine(public_key_hex=public_key_hex, state_store=audit_logger)


@pytest.fixture
def mock_razorpay_executor():
    """Provides a mock RazorpayExecutor with tracked call counts."""
    executor = RazorpayExecutor()
    executor.create_order = MagicMock(return_value={
        "id": "order_mock_12345",
        "entity": "order",
        "amount": 120000,
        "currency": "INR",
        "status": "created"
    })
    return executor


@pytest.fixture
def storefront_service(policy_engine, audit_logger, mock_razorpay_executor):
    """Provides StorefrontService with mock Razorpay executor for invariant assertion."""
    return StorefrontService(
        policy_engine=policy_engine,
        audit_logger=audit_logger,
        razorpay_executor=mock_razorpay_executor
    )
