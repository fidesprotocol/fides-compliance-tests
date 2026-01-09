"""
Pytest configuration and shared fixtures for Fides compliance tests.
"""

import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest

# Base paths
FIXTURES_DIR = Path(__file__).parent.parent / "fixtures"


def load_fixture(name: str) -> dict[str, Any]:
    """Load a JSON fixture file."""
    with open(FIXTURES_DIR / name, "r", encoding="utf-8") as f:
        return json.load(f)


@pytest.fixture
def valid_dr() -> dict[str, Any]:
    """Load valid Decision Record fixture."""
    return load_fixture("valid_dr.json")


@pytest.fixture
def valid_sdr() -> dict[str, Any]:
    """Load valid Special Decision Record fixture."""
    return load_fixture("valid_sdr.json")


@pytest.fixture
def valid_rr() -> dict[str, Any]:
    """Load valid Revocation Record fixture."""
    return load_fixture("valid_rr.json")


@pytest.fixture
def valid_payment() -> dict[str, Any]:
    """Load valid payment fixture."""
    return load_fixture("valid_payment.json")


@pytest.fixture
def invalid_missing_fields() -> dict[str, Any]:
    """Load DR with missing required fields."""
    return load_fixture("invalid_missing_fields.json")


@pytest.fixture
def invalid_signature() -> dict[str, Any]:
    """Load DR with invalid signature."""
    return load_fixture("invalid_signature.json")


@pytest.fixture
def invalid_timestamp() -> dict[str, Any]:
    """Load DR with invalid timestamp attestation."""
    return load_fixture("invalid_timestamp.json")


@pytest.fixture
def invalid_hash_chain() -> dict[str, Any]:
    """Load DR with broken hash chain."""
    return load_fixture("invalid_hash_chain.json")


@pytest.fixture
def invalid_sdr_expired() -> dict[str, Any]:
    """Load expired SDR."""
    return load_fixture("invalid_sdr_expired.json")


@pytest.fixture
def invalid_beneficiary() -> dict[str, Any]:
    """Load payment with wrong beneficiary."""
    return load_fixture("invalid_beneficiary.json")


@pytest.fixture
def invalid_registration_delay() -> dict[str, Any]:
    """Load DR with registration delay > 72h."""
    return load_fixture("invalid_registration_delay.json")


@pytest.fixture
def impl_url() -> str:
    """Get implementation URL from environment."""
    return os.environ.get("FIDES_IMPL_URL", "http://localhost:8000")


@pytest.fixture
def new_decision_id() -> str:
    """Generate a new unique decision ID."""
    return str(uuid4())


@pytest.fixture
def now_utc() -> datetime:
    """Get current UTC timestamp."""
    return datetime.now(timezone.utc)


@pytest.fixture
def genesis_hash() -> str:
    """Genesis block hash (all zeros)."""
    return "0" * 64


def make_dr(
    decision_id: str | None = None,
    authority_id: str = "TEST-AUTH-001",
    deciders_id: list[str] | None = None,
    act_type: str = "contract",
    currency: str = "BRL",
    maximum_value: float = 10000.00,
    beneficiary: str = "TEST-BENEFICIARY-001",
    legal_basis: str = "Test Legal Basis",
    decision_date: str | None = None,
    previous_record_hash: str | None = None,
    record_timestamp: str | None = None,
) -> dict[str, Any]:
    """Create a minimal DR for testing."""
    now = datetime.now(timezone.utc)
    return {
        "decision_id": decision_id or str(uuid4()),
        "authority_id": authority_id,
        "deciders_id": deciders_id or ["TEST-DECIDER-001"],
        "act_type": act_type,
        "currency": currency,
        "maximum_value": maximum_value,
        "beneficiary": beneficiary,
        "legal_basis": legal_basis,
        "decision_date": decision_date or now.isoformat().replace("+00:00", "Z"),
        "previous_record_hash": previous_record_hash or ("0" * 64),
        "record_timestamp": record_timestamp or (now + timedelta(hours=1)).isoformat().replace("+00:00", "Z"),
    }


def make_payment(
    decision_id: str,
    payment_amount: float = 1000.00,
    payment_currency: str = "BRL",
    payment_beneficiary: str = "TEST-BENEFICIARY-001",
) -> dict[str, Any]:
    """Create a minimal payment request for testing."""
    now = datetime.now(timezone.utc)
    return {
        "payment_id": str(uuid4()),
        "decision_id": decision_id,
        "payment_amount": payment_amount,
        "payment_currency": payment_currency,
        "payment_beneficiary": payment_beneficiary,
        "request_timestamp": now.isoformat().replace("+00:00", "Z"),
    }
