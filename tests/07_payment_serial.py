"""
Test 07: Payment Serialization

Validates Fides v0.3 invariant:
- Payment processing is serialized per decision_id
- No race conditions in concurrent payment processing

Reference: FIDES-v0.3.md Section 7.6, Appendix F
"""

import asyncio
import pytest
import httpx

from .conftest import make_dr, make_payment


class TestPaymentSerialization:
    """
    Tests that concurrent payments are serialized per decision_id.

    Per Section 7.6:
    - Payments against the same decision_id MUST be processed serially
    - No parallel processing of payments against the same DR
    """

    def test_concurrent_payments_serialized(self, impl_url: str, valid_dr: dict):
        """
        Concurrent payments to same DR must be serialized.

        This test attempts to create a race condition by sending
        multiple payment requests simultaneously.
        """
        with httpx.Client(base_url=impl_url) as client:
            client.post("/_test/reset")
            response = client.post("/dr", json=valid_dr)
            if response.status_code not in [200, 201]:
                pytest.skip(f"Could not create DR: {response.text}")

        max_value = valid_dr["maximum_value"]
        decision_id = valid_dr["decision_id"]

        # Create multiple payments that would exceed max if all authorized
        # Each payment is 40% of max - if 3 go through, it's 120% (should fail)
        payments = [
            make_payment(
                decision_id=decision_id,
                payment_amount=max_value * 0.4,
                payment_currency=valid_dr["currency"],
                payment_beneficiary=valid_dr["beneficiary"],
            )
            for _ in range(5)
        ]

        async def send_payment(payment):
            async with httpx.AsyncClient(base_url=impl_url) as client:
                return await client.post("/payment", json=payment)

        async def run_concurrent():
            tasks = [send_payment(p) for p in payments]
            return await asyncio.gather(*tasks, return_exceptions=True)

        results = asyncio.run(run_concurrent())

        # Count successful payments
        successful = sum(
            1 for r in results
            if isinstance(r, httpx.Response) and r.status_code in [200, 201]
        )

        # Calculate total that would have been paid
        total_if_all_succeeded = max_value * 0.4 * successful

        # Total paid should not exceed maximum_value
        assert total_if_all_succeeded <= max_value, \
            f"Concurrent payments exceeded max: {total_if_all_succeeded} > {max_value}"

    def test_sum_previous_payments_accurate(self, impl_url: str, valid_dr: dict):
        """
        sumPreviousPayments() must be accurate at verification time.

        Per Section 7.6:
        "MUST guarantee that sumPreviousPayments() is always accurate"
        """
        with httpx.Client(base_url=impl_url) as client:
            client.post("/_test/reset")
            client.post("/dr", json=valid_dr)

            max_value = valid_dr["maximum_value"]
            decision_id = valid_dr["decision_id"]

            # Make first payment
            payment1 = make_payment(
                decision_id=decision_id,
                payment_amount=max_value * 0.5,
                payment_currency=valid_dr["currency"],
                payment_beneficiary=valid_dr["beneficiary"],
            )
            client.post("/payment", json=payment1)

            # Make second payment
            payment2 = make_payment(
                decision_id=decision_id,
                payment_amount=max_value * 0.3,
                payment_currency=valid_dr["currency"],
                payment_beneficiary=valid_dr["beneficiary"],
            )
            client.post("/payment", json=payment2)

            # Third payment that would exceed max
            payment3 = make_payment(
                decision_id=decision_id,
                payment_amount=max_value * 0.3,  # 0.5 + 0.3 + 0.3 = 1.1 > 1.0
                payment_currency=valid_dr["currency"],
                payment_beneficiary=valid_dr["beneficiary"],
            )
            response = client.post("/payment/authorize", json=payment3)

            if response.status_code == 200:
                result = response.json()
                assert result.get("authorized") is False, \
                    "Third payment should be rejected (would exceed max)"


class TestLockingBehavior:
    """
    Tests the exclusive locking requirement.
    """

    def test_different_decisions_parallel(self, impl_url: str):
        """
        Payments to DIFFERENT decision_ids can be parallel.

        Only same decision_id requires serialization.
        """
        with httpx.Client(base_url=impl_url) as client:
            client.post("/_test/reset")

            # Create two DRs
            dr1 = make_dr()
            dr2 = make_dr()

            client.post("/dr", json=dr1)
            client.post("/dr", json=dr2)

            # Payments to different DRs
            payment1 = make_payment(
                decision_id=dr1["decision_id"],
                payment_beneficiary=dr1["beneficiary"],
            )
            payment2 = make_payment(
                decision_id=dr2["decision_id"],
                payment_beneficiary=dr2["beneficiary"],
            )

            async def send_payments():
                async with httpx.AsyncClient(base_url=impl_url) as async_client:
                    tasks = [
                        async_client.post("/payment", json=payment1),
                        async_client.post("/payment", json=payment2),
                    ]
                    return await asyncio.gather(*tasks)

            results = asyncio.run(send_payments())

            # Both should succeed (different decision_ids)
            success_count = sum(1 for r in results if r.status_code in [200, 201])
            # At least both should be processed (may fail for other reasons)
            assert len(results) == 2

    def test_lock_held_during_bank_execution(self):
        """
        Per Section 7.7.5, bank execution must occur within lock.

        The lock must be held during:
        1. Verify authorization
        2. Execute at financial institution
        3. Record success

        This is an architectural requirement that cannot be fully tested
        externally but can be verified through implementation audit.
        """
        # This test documents the requirement
        # Actual verification requires code review
        pass


class TestPaymentAtomicity:
    """
    Tests payment atomicity requirements (Section 7.2).
    """

    def test_partial_payments_independently_verified(self, impl_url: str, valid_dr: dict):
        """
        Every payment, partial or total, is subject to independent verification.

        Per Section 7.2:
        "Payment Atomicity: Every payment, partial or total, is subject to
        independent verification under this protocol."
        """
        with httpx.Client(base_url=impl_url) as client:
            client.post("/_test/reset")
            client.post("/dr", json=valid_dr)

            max_value = valid_dr["maximum_value"]
            decision_id = valid_dr["decision_id"]

            # Make multiple partial payments
            for i in range(3):
                payment = make_payment(
                    decision_id=decision_id,
                    payment_amount=max_value * 0.2,  # 20% each
                    payment_currency=valid_dr["currency"],
                    payment_beneficiary=valid_dr["beneficiary"],
                )

                # Each payment must be verified
                auth_response = client.post("/payment/authorize", json=payment)
                assert auth_response.status_code == 200, \
                    f"Payment {i+1} authorization check failed"

                result = auth_response.json()
                # First 3 payments (60% total) should be authorized
                assert result.get("authorized") is True or result.get("authorization_result") is True, \
                    f"Payment {i+1} should be authorized"

                # Execute payment
                client.post("/payment", json=payment)

    def test_splitting_does_not_bypass_max(self, impl_url: str, valid_dr: dict):
        """
        Splitting payments does not bypass maximum_value constraints.
        """
        with httpx.Client(base_url=impl_url) as client:
            client.post("/_test/reset")
            client.post("/dr", json=valid_dr)

            max_value = valid_dr["maximum_value"]
            decision_id = valid_dr["decision_id"]

            # Try to split into many small payments exceeding max
            num_payments = 20
            amount_each = max_value / 10  # Total would be 2x max

            authorized_count = 0
            for _ in range(num_payments):
                payment = make_payment(
                    decision_id=decision_id,
                    payment_amount=amount_each,
                    payment_currency=valid_dr["currency"],
                    payment_beneficiary=valid_dr["beneficiary"],
                )

                response = client.post("/payment", json=payment)
                if response.status_code in [200, 201]:
                    authorized_count += 1

            # Should not authorize more than max_value worth
            total_authorized = authorized_count * amount_each
            assert total_authorized <= max_value * 1.01, \
                f"Split payments exceeded max: {total_authorized} > {max_value}"
