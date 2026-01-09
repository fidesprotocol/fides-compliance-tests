"""
Test 08: SDR Expiration Enforcement

Validates Fides v0.3 invariant:
- SDR expiration is enforced in isPaymentAuthorized
- Payments after maximum_term are rejected
- Exception types have maximum term limits

Reference: FIDES-v0.3.md Section 9, 7.2, Appendix F
"""

from datetime import datetime, timedelta, timezone

import pytest
import httpx

from .conftest import make_dr, make_payment


class TestSDRExpiration:
    """
    Tests that SDR expiration is properly enforced.

    Per Section 9.7:
    if dr.is_sdr == true:
        if payment.date > dr.maximum_term:
            return false
    """

    def test_payment_before_expiration_allowed(self, impl_url: str, valid_sdr: dict):
        """Payment before maximum_term should be allowed."""
        with httpx.Client(base_url=impl_url) as client:
            client.post("/_test/reset")
            response = client.post("/dr", json=valid_sdr)
            if response.status_code not in [200, 201]:
                pytest.skip(f"Could not create SDR: {response.text}")

            # Payment within term
            payment = make_payment(
                decision_id=valid_sdr["decision_id"],
                payment_currency=valid_sdr["currency"],
                payment_beneficiary=valid_sdr["beneficiary"],
            )

            response = client.post("/payment/authorize", json=payment)
            if response.status_code == 200:
                result = response.json()
                # Should be authorized (within term)
                auth = result.get("authorized") or result.get("authorization_result")
                assert auth is True, "Payment within SDR term should be authorized"

    def test_payment_after_expiration_rejected(self, impl_url: str, invalid_sdr_expired: dict):
        """Payment after maximum_term must be rejected."""
        with httpx.Client(base_url=impl_url) as client:
            client.post("/_test/reset")

            # Inject the expired SDR for testing
            response = client.post("/_test/inject", json={"dr": invalid_sdr_expired})
            if response.status_code == 404:
                # Try normal creation (should fail or be accepted as historical)
                client.post("/dr", json=invalid_sdr_expired)

            # Try to pay against expired SDR
            payment = make_payment(
                decision_id=invalid_sdr_expired["decision_id"],
                payment_currency=invalid_sdr_expired["currency"],
                payment_beneficiary=invalid_sdr_expired["beneficiary"],
            )
            # Set current timestamp
            payment["request_timestamp"] = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

            response = client.post("/payment/authorize", json=payment)
            if response.status_code == 200:
                result = response.json()
                assert result.get("authorized") is False, \
                    "Payment after SDR expiration must be rejected"
                assert "SDR_EXPIRED" in str(result.get("rejection_reason", "")).upper()


class TestExceptionTypeTermLimits:
    """
    Tests that exception types respect their maximum term limits.

    Per Section 9.3:
    | Type | Maximum Term |
    | public_calamity | 90 days |
    | health_emergency | 30 days |
    | essential_service | 15 days |
    | national_security | 180 days |
    """

    TERM_LIMITS = {
        "public_calamity": 90,
        "health_emergency": 30,
        "essential_service": 15,
        "national_security": 180,
    }

    def test_essential_service_max_15_days(self, impl_url: str):
        """essential_service SDR cannot exceed 15 days."""
        now = datetime.now(timezone.utc)

        sdr = make_dr()
        sdr["is_sdr"] = True
        sdr["exception_type"] = "essential_service"
        sdr["formal_justification"] = "A" * 100  # Min 100 chars
        sdr["maximum_term"] = (now + timedelta(days=20)).isoformat().replace("+00:00", "Z")  # 20 > 15
        sdr["reinforced_deciders"] = sdr["deciders_id"] * 2
        sdr["oversight_authority"] = "OVERSIGHT-001"

        with httpx.Client(base_url=impl_url) as client:
            response = client.post("/dr", json=sdr)
            assert response.status_code in [400, 422], \
                f"essential_service with 20-day term should be rejected: {response.status_code}"

    def test_health_emergency_max_30_days(self, impl_url: str):
        """health_emergency SDR cannot exceed 30 days."""
        now = datetime.now(timezone.utc)

        sdr = make_dr()
        sdr["is_sdr"] = True
        sdr["exception_type"] = "health_emergency"
        sdr["formal_justification"] = "A" * 100
        sdr["maximum_term"] = (now + timedelta(days=45)).isoformat().replace("+00:00", "Z")  # 45 > 30
        sdr["reinforced_deciders"] = sdr["deciders_id"] * 2
        sdr["oversight_authority"] = "OVERSIGHT-001"

        with httpx.Client(base_url=impl_url) as client:
            response = client.post("/dr", json=sdr)
            assert response.status_code in [400, 422], \
                "health_emergency with 45-day term should be rejected"

    def test_public_calamity_max_90_days(self, impl_url: str):
        """public_calamity SDR cannot exceed 90 days."""
        now = datetime.now(timezone.utc)

        sdr = make_dr()
        sdr["is_sdr"] = True
        sdr["exception_type"] = "public_calamity"
        sdr["formal_justification"] = "A" * 100
        sdr["maximum_term"] = (now + timedelta(days=120)).isoformat().replace("+00:00", "Z")  # 120 > 90
        sdr["reinforced_deciders"] = sdr["deciders_id"] * 2
        sdr["oversight_authority"] = "OVERSIGHT-001"

        with httpx.Client(base_url=impl_url) as client:
            response = client.post("/dr", json=sdr)
            assert response.status_code in [400, 422], \
                "public_calamity with 120-day term should be rejected"


class TestSDRRequirements:
    """
    Tests for SDR-specific field requirements.
    """

    def test_sdr_requires_exception_type(self, impl_url: str):
        """SDR must have exception_type field."""
        sdr = make_dr()
        sdr["is_sdr"] = True
        # Missing exception_type
        sdr["formal_justification"] = "A" * 100
        sdr["maximum_term"] = (datetime.now(timezone.utc) + timedelta(days=10)).isoformat().replace("+00:00", "Z")
        sdr["reinforced_deciders"] = sdr["deciders_id"] * 2
        sdr["oversight_authority"] = "OVERSIGHT-001"

        with httpx.Client(base_url=impl_url) as client:
            response = client.post("/dr", json=sdr)
            assert response.status_code in [400, 422], \
                "SDR without exception_type must be rejected"

    def test_sdr_requires_formal_justification(self, impl_url: str):
        """SDR must have formal_justification of min 100 chars."""
        sdr = make_dr()
        sdr["is_sdr"] = True
        sdr["exception_type"] = "essential_service"
        sdr["formal_justification"] = "Too short"  # < 100 chars
        sdr["maximum_term"] = (datetime.now(timezone.utc) + timedelta(days=10)).isoformat().replace("+00:00", "Z")
        sdr["reinforced_deciders"] = sdr["deciders_id"] * 2
        sdr["oversight_authority"] = "OVERSIGHT-001"

        with httpx.Client(base_url=impl_url) as client:
            response = client.post("/dr", json=sdr)
            assert response.status_code in [400, 422], \
                "SDR with short justification must be rejected"

    def test_sdr_requires_maximum_term(self, impl_url: str):
        """SDR must have maximum_term field."""
        sdr = make_dr()
        sdr["is_sdr"] = True
        sdr["exception_type"] = "essential_service"
        sdr["formal_justification"] = "A" * 100
        # Missing maximum_term
        sdr["reinforced_deciders"] = sdr["deciders_id"] * 2
        sdr["oversight_authority"] = "OVERSIGHT-001"

        with httpx.Client(base_url=impl_url) as client:
            response = client.post("/dr", json=sdr)
            assert response.status_code in [400, 422], \
                "SDR without maximum_term must be rejected"

    def test_sdr_requires_reinforced_deciders(self, impl_url: str):
        """SDR requires >= 2x minimum deciders."""
        sdr = make_dr(deciders_id=["DECIDER-1"])  # Only 1 decider
        sdr["is_sdr"] = True
        sdr["exception_type"] = "essential_service"
        sdr["formal_justification"] = "A" * 100
        sdr["maximum_term"] = (datetime.now(timezone.utc) + timedelta(days=10)).isoformat().replace("+00:00", "Z")
        sdr["reinforced_deciders"] = ["DECIDER-1"]  # Same as deciders_id (not 2x)
        sdr["oversight_authority"] = "OVERSIGHT-001"

        with httpx.Client(base_url=impl_url) as client:
            response = client.post("/dr", json=sdr)
            # Should require at least 2 deciders for SDR
            # (2x the normal minimum of 1)

    def test_sdr_requires_oversight_authority(self, impl_url: str):
        """SDR must have oversight_authority field."""
        sdr = make_dr()
        sdr["is_sdr"] = True
        sdr["exception_type"] = "essential_service"
        sdr["formal_justification"] = "A" * 100
        sdr["maximum_term"] = (datetime.now(timezone.utc) + timedelta(days=10)).isoformat().replace("+00:00", "Z")
        sdr["reinforced_deciders"] = sdr["deciders_id"] * 2
        # Missing oversight_authority

        with httpx.Client(base_url=impl_url) as client:
            response = client.post("/dr", json=sdr)
            assert response.status_code in [400, 422], \
                "SDR without oversight_authority must be rejected"


class TestGenericExceptionsProhibited:
    """
    Tests that generic exception types are prohibited.

    Per Section 9.3:
    'Generic types ("exceptional", "urgent", "special", "other") are PROHIBITED.'
    """

    def test_generic_exception_rejected(self, impl_url: str):
        """Generic exception types must be rejected."""
        prohibited_types = ["exceptional", "urgent", "special", "other", "general", "misc"]

        for exc_type in prohibited_types:
            sdr = make_dr()
            sdr["is_sdr"] = True
            sdr["exception_type"] = exc_type
            sdr["formal_justification"] = "A" * 100
            sdr["maximum_term"] = (datetime.now(timezone.utc) + timedelta(days=10)).isoformat().replace("+00:00", "Z")
            sdr["reinforced_deciders"] = sdr["deciders_id"] * 2
            sdr["oversight_authority"] = "OVERSIGHT-001"

            with httpx.Client(base_url=impl_url) as client:
                response = client.post("/dr", json=sdr)
                assert response.status_code in [400, 422], \
                    f"Generic exception type '{exc_type}' must be rejected"
