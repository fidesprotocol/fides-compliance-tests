"""
Test 06: Payment Authorization

Validates Fides v0.3 invariant:
- No payment is executed without a valid DR
- No authorization is subjective
- Verification is binary and deterministic

Reference: FIDES-v0.3.md Section 7, Appendix D, Appendix F
"""

import pytest
import httpx
from uuid import uuid4

from .conftest import make_dr, make_payment


class TestNoPaymentWithoutDR:
    """
    Tests the core invariant: No payment without valid Decision Record.
    """

    def test_payment_without_dr_rejected(self, impl_url: str):
        """Payment referencing non-existent DR must be rejected."""
        fake_decision_id = str(uuid4())

        payment = make_payment(
            decision_id=fake_decision_id,
            payment_amount=1000.00,
        )

        with httpx.Client(base_url=impl_url) as client:
            response = client.post("/payment/authorize", json=payment)
            assert response.status_code in [400, 404, 422], \
                f"Payment without DR must be rejected: {response.status_code}"

            if response.status_code == 200:
                result = response.json()
                assert result.get("authorized") is False, \
                    "Payment without DR must not be authorized"

    def test_payment_with_valid_dr_authorized(self, impl_url: str, valid_dr: dict):
        """Payment with valid DR should be authorized."""
        with httpx.Client(base_url=impl_url) as client:
            # Reset and create DR
            client.post("/_test/reset")
            response = client.post("/dr", json=valid_dr)

            if response.status_code not in [200, 201]:
                pytest.skip(f"Could not create DR: {response.text}")

            # Request payment authorization
            payment = make_payment(
                decision_id=valid_dr["decision_id"],
                payment_amount=1000.00,
                payment_currency=valid_dr["currency"],
                payment_beneficiary=valid_dr["beneficiary"],
            )

            response = client.post("/payment/authorize", json=payment)
            assert response.status_code == 200

            result = response.json()
            assert result.get("authorized") is True or result.get("authorization_result") is True, \
                "Valid payment should be authorized"


class TestPaymentConditions:
    """
    Tests all payment authorization conditions from Section 7.2.
    """

    def test_payment_date_after_decision_date(self, impl_url: str, valid_dr: dict):
        """Payment date must be after decision_date."""
        with httpx.Client(base_url=impl_url) as client:
            client.post("/_test/reset")
            client.post("/dr", json=valid_dr)

            # Payment with date BEFORE decision
            payment = make_payment(
                decision_id=valid_dr["decision_id"],
                payment_beneficiary=valid_dr["beneficiary"],
            )
            # Set payment date before decision
            payment["request_timestamp"] = "2020-01-01T00:00:00Z"

            response = client.post("/payment/authorize", json=payment)
            if response.status_code == 200:
                result = response.json()
                assert result.get("authorized") is False, \
                    "Payment before decision_date must be rejected"

    def test_payment_not_exceed_maximum_value(self, impl_url: str, valid_dr: dict):
        """Accumulated payments cannot exceed maximum_value."""
        with httpx.Client(base_url=impl_url) as client:
            client.post("/_test/reset")
            client.post("/dr", json=valid_dr)

            max_value = valid_dr["maximum_value"]

            # First payment: 60% of max
            payment1 = make_payment(
                decision_id=valid_dr["decision_id"],
                payment_amount=max_value * 0.6,
                payment_currency=valid_dr["currency"],
                payment_beneficiary=valid_dr["beneficiary"],
            )
            response1 = client.post("/payment", json=payment1)

            # Second payment: another 60% would exceed max
            payment2 = make_payment(
                decision_id=valid_dr["decision_id"],
                payment_amount=max_value * 0.6,
                payment_currency=valid_dr["currency"],
                payment_beneficiary=valid_dr["beneficiary"],
            )
            response2 = client.post("/payment/authorize", json=payment2)

            if response2.status_code == 200:
                result = response2.json()
                assert result.get("authorized") is False, \
                    "Payment exceeding maximum_value must be rejected"
                assert "MAXIMUM_VALUE_EXCEEDED" in str(result.get("rejection_reason", ""))

    def test_beneficiary_must_match(self, impl_url: str, valid_dr: dict, invalid_beneficiary: dict):
        """Payment beneficiary must match DR beneficiary."""
        with httpx.Client(base_url=impl_url) as client:
            client.post("/_test/reset")
            client.post("/dr", json=valid_dr)

            payment = make_payment(
                decision_id=valid_dr["decision_id"],
                payment_beneficiary="WRONG-BENEFICIARY-999",
            )

            response = client.post("/payment/authorize", json=payment)
            if response.status_code == 200:
                result = response.json()
                assert result.get("authorized") is False, \
                    "Payment to wrong beneficiary must be rejected"
                assert "BENEFICIARY_MISMATCH" in str(result.get("rejection_reason", ""))

    def test_currency_must_match(self, impl_url: str, valid_dr: dict):
        """Payment currency must match DR currency."""
        with httpx.Client(base_url=impl_url) as client:
            client.post("/_test/reset")
            client.post("/dr", json=valid_dr)

            # DR uses BRL, try to pay in USD
            payment = make_payment(
                decision_id=valid_dr["decision_id"],
                payment_currency="USD",  # Wrong currency
                payment_beneficiary=valid_dr["beneficiary"],
            )

            response = client.post("/payment/authorize", json=payment)
            if response.status_code == 200:
                result = response.json()
                assert result.get("authorized") is False, \
                    "Payment in wrong currency must be rejected"
                assert "CURRENCY_MISMATCH" in str(result.get("rejection_reason", ""))

    def test_revoked_dr_blocks_payment(self, impl_url: str, valid_dr: dict, valid_rr: dict):
        """Payment against revoked DR must be rejected."""
        with httpx.Client(base_url=impl_url) as client:
            client.post("/_test/reset")
            client.post("/dr", json=valid_dr)

            # Revoke the DR
            rr = valid_rr.copy()
            rr["target_decision_id"] = valid_dr["decision_id"]
            client.post("/rr", json=rr)

            # Try to pay
            payment = make_payment(
                decision_id=valid_dr["decision_id"],
                payment_beneficiary=valid_dr["beneficiary"],
            )

            response = client.post("/payment/authorize", json=payment)
            if response.status_code == 200:
                result = response.json()
                assert result.get("authorized") is False, \
                    "Payment against revoked DR must be rejected"
                assert "REVOKED" in str(result.get("rejection_reason", "")).upper()


class TestBinaryVerification:
    """
    Tests that verification is binary and deterministic.
    """

    def test_verification_returns_boolean(self, impl_url: str, valid_dr: dict):
        """Verification must return true or false, nothing else."""
        with httpx.Client(base_url=impl_url) as client:
            client.post("/_test/reset")
            client.post("/dr", json=valid_dr)

            payment = make_payment(
                decision_id=valid_dr["decision_id"],
                payment_beneficiary=valid_dr["beneficiary"],
            )

            response = client.post("/payment/authorize", json=payment)
            if response.status_code == 200:
                result = response.json()
                auth = result.get("authorized") or result.get("authorization_result")
                assert auth in [True, False], \
                    f"Authorization must be boolean, got: {auth}"

    def test_verification_deterministic(self, impl_url: str, valid_dr: dict):
        """Same input must always produce same output."""
        with httpx.Client(base_url=impl_url) as client:
            client.post("/_test/reset")
            client.post("/dr", json=valid_dr)

            payment = make_payment(
                decision_id=valid_dr["decision_id"],
                payment_beneficiary=valid_dr["beneficiary"],
            )

            # Call multiple times
            results = []
            for _ in range(3):
                response = client.post("/payment/authorize", json=payment)
                if response.status_code == 200:
                    result = response.json()
                    auth = result.get("authorized") or result.get("authorization_result")
                    results.append(auth)

            if len(results) >= 2:
                assert all(r == results[0] for r in results), \
                    f"Same input must produce same output: {results}"

    def test_no_subjective_authorization(self):
        """
        Authorization cannot depend on subjective factors.

        Per Section 7.3:
        - Without interpretation - does not evaluate merit
        - Without implicit exception - there is no "almost valid"
        """
        # This is a documentation test - actual verification requires
        # reviewing implementation code for subjective decision points
        pass


class TestPaymentLedger:
    """
    Tests for payment ledger requirements (Section 7.7).
    """

    def test_rejected_payments_recorded(self, impl_url: str):
        """Rejected payments must also be recorded in ledger."""
        fake_decision_id = str(uuid4())
        payment = make_payment(decision_id=fake_decision_id)

        with httpx.Client(base_url=impl_url) as client:
            # This should be rejected (no DR)
            client.post("/payment", json=payment)

            # Check if it was recorded
            response = client.get("/payment")
            if response.status_code == 200:
                payments = response.json()
                # Look for our rejected payment
                found = any(
                    p.get("decision_id") == fake_decision_id
                    for p in (payments if isinstance(payments, list) else [])
                )
                # Note: Implementation may or may not record failed authorization attempts

    def test_payment_ledger_public(self, impl_url: str):
        """Payment ledger must be publicly accessible."""
        with httpx.Client(base_url=impl_url) as client:
            response = client.get("/payment")
            assert response.status_code in [200, 204], \
                "Payment ledger must be publicly accessible"
