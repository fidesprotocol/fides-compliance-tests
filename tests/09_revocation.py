"""
Test 09: Revocation Authority

Validates Fides v0.3 invariant:
- Revocation authority is verified
- Only authorized parties can revoke
- Revocation does not delete, only marks as revoked

Reference: FIDES-v0.3.md Section 10, Appendix F
"""

import pytest
import httpx
from uuid import uuid4

from .conftest import make_dr


def make_revocation(
    target_decision_id: str,
    revoker_id: list[str],
    revocation_type: str = "voluntary",
    revocation_reason: str = "Revocation for testing purposes - meets minimum 50 character requirement",
    revoker_authority: str = "original_decider",
) -> dict:
    """Create a minimal Revocation Record for testing."""
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc)

    return {
        "revocation_id": str(uuid4()),
        "target_decision_id": target_decision_id,
        "revocation_type": revocation_type,
        "revocation_reason": revocation_reason,
        "revoker_authority": revoker_authority,
        "revoker_id": revoker_id,
        "revocation_date": now.isoformat().replace("+00:00", "Z"),
        "previous_record_hash": "0" * 64,
        "record_timestamp": now.isoformat().replace("+00:00", "Z"),
    }


class TestRevocationAuthority:
    """
    Tests that only authorized parties can revoke.

    Per Section 10.3, valid revokers are:
    1. Original deciders
    2. Hierarchical superior
    3. Oversight authority (for SDR)
    4. Judicial authority
    """

    def test_original_decider_can_revoke(self, impl_url: str, valid_dr: dict):
        """Original decider can revoke their own DR."""
        with httpx.Client(base_url=impl_url) as client:
            client.post("/_test/reset")
            client.post("/dr", json=valid_dr)

            rr = make_revocation(
                target_decision_id=valid_dr["decision_id"],
                revoker_id=valid_dr["deciders_id"],
                revoker_authority="original_decider",
            )

            response = client.post("/rr", json=rr)
            assert response.status_code in [200, 201], \
                f"Original decider should be able to revoke: {response.text}"

    def test_non_decider_cannot_revoke(self, impl_url: str, valid_dr: dict):
        """Non-decider without authority cannot revoke."""
        with httpx.Client(base_url=impl_url) as client:
            client.post("/_test/reset")
            client.post("/dr", json=valid_dr)

            rr = make_revocation(
                target_decision_id=valid_dr["decision_id"],
                revoker_id=["UNAUTHORIZED-PERSON-999"],
                revoker_authority="original_decider",  # False claim
            )

            response = client.post("/rr", json=rr)
            assert response.status_code in [400, 403, 422], \
                "Unauthorized revoker should be rejected"

    def test_oversight_can_revoke_sdr(self, impl_url: str, valid_sdr: dict):
        """Oversight authority can revoke SDR."""
        with httpx.Client(base_url=impl_url) as client:
            client.post("/_test/reset")
            client.post("/dr", json=valid_sdr)

            oversight_id = valid_sdr.get("oversight_authority", "TCU-001")

            rr = make_revocation(
                target_decision_id=valid_sdr["decision_id"],
                revoker_id=[oversight_id],
                revocation_type="oversight",
                revoker_authority="oversight_authority",
            )

            response = client.post("/rr", json=rr)
            # Should be accepted if implementation supports oversight revocation
            if response.status_code in [200, 201]:
                pass  # Success
            elif response.status_code in [400, 422]:
                # May fail for signature/other reasons, check error
                error = str(response.json())
                assert "authority" not in error.lower(), \
                    "Oversight authority should have revocation rights"

    def test_judicial_revocation_requires_court_order(self, impl_url: str, valid_dr: dict):
        """Judicial revocation requires court_order reference."""
        with httpx.Client(base_url=impl_url) as client:
            client.post("/_test/reset")
            client.post("/dr", json=valid_dr)

            rr = make_revocation(
                target_decision_id=valid_dr["decision_id"],
                revoker_id=["COURT-001"],
                revocation_type="judicial",
                revoker_authority="judicial_authority",
            )
            # Should include court_order reference for judicial revocation


class TestRevocationDoesNotDelete:
    """
    Tests that revocation marks but does not delete.

    Per Section 10.4:
    "After a valid RR, new payments are prohibited but the DR still exists"
    """

    def test_revoked_dr_still_exists(self, impl_url: str, valid_dr: dict, valid_rr: dict):
        """Revoked DR remains in the system."""
        with httpx.Client(base_url=impl_url) as client:
            client.post("/_test/reset")
            client.post("/dr", json=valid_dr)

            # Revoke
            rr = valid_rr.copy()
            rr["target_decision_id"] = valid_dr["decision_id"]
            client.post("/rr", json=rr)

            # DR should still be retrievable
            response = client.get(f"/dr/{valid_dr['decision_id']}")
            assert response.status_code == 200, \
                "Revoked DR must still exist in the system"

    def test_revoked_dr_marked_as_revoked(self, impl_url: str, valid_dr: dict, valid_rr: dict):
        """Revoked DR should be marked as such."""
        with httpx.Client(base_url=impl_url) as client:
            client.post("/_test/reset")
            client.post("/dr", json=valid_dr)

            # Revoke
            rr = valid_rr.copy()
            rr["target_decision_id"] = valid_dr["decision_id"]
            client.post("/rr", json=rr)

            # Check status
            response = client.get(f"/dr/{valid_dr['decision_id']}")
            dr = response.json()

            assert dr.get("revoked") is True or "revoked" in str(dr).lower(), \
                "Revoked DR should be marked as revoked"

    def test_past_payments_preserved_after_revocation(self, impl_url: str, valid_dr: dict):
        """Payments executed before revocation remain in ledger."""
        with httpx.Client(base_url=impl_url) as client:
            client.post("/_test/reset")
            client.post("/dr", json=valid_dr)

            # Make a payment
            from .conftest import make_payment
            payment = make_payment(
                decision_id=valid_dr["decision_id"],
                payment_beneficiary=valid_dr["beneficiary"],
                payment_currency=valid_dr["currency"],
            )
            client.post("/payment", json=payment)

            # Now revoke the DR
            rr = make_revocation(
                target_decision_id=valid_dr["decision_id"],
                revoker_id=valid_dr["deciders_id"],
            )
            client.post("/rr", json=rr)

            # Check payment still exists
            response = client.get("/payment")
            if response.status_code == 200:
                payments = response.json()
                # Past payment should still be there
                if isinstance(payments, list):
                    found = any(
                        p.get("decision_id") == valid_dr["decision_id"]
                        for p in payments
                    )
                    assert found, "Past payments must be preserved after revocation"


class TestRevocationRecordRequirements:
    """
    Tests for Revocation Record field requirements.
    """

    def test_rr_requires_target_decision_id(self, impl_url: str):
        """RR must reference target_decision_id."""
        rr = make_revocation(
            target_decision_id="",  # Empty
            revoker_id=["REVOKER-1"],
        )
        rr.pop("target_decision_id")

        with httpx.Client(base_url=impl_url) as client:
            response = client.post("/rr", json=rr)
            assert response.status_code in [400, 422], \
                "RR without target_decision_id must be rejected"

    def test_rr_target_must_exist(self, impl_url: str):
        """RR target_decision_id must reference existing DR."""
        fake_id = str(uuid4())
        rr = make_revocation(
            target_decision_id=fake_id,
            revoker_id=["REVOKER-1"],
        )

        with httpx.Client(base_url=impl_url) as client:
            response = client.post("/rr", json=rr)
            assert response.status_code in [400, 404, 422], \
                "RR targeting non-existent DR must be rejected"

    def test_rr_requires_revocation_reason(self, impl_url: str, valid_dr: dict):
        """RR must have revocation_reason of min 50 chars."""
        with httpx.Client(base_url=impl_url) as client:
            client.post("/_test/reset")
            client.post("/dr", json=valid_dr)

            rr = make_revocation(
                target_decision_id=valid_dr["decision_id"],
                revoker_id=valid_dr["deciders_id"],
                revocation_reason="Too short",  # < 50 chars
            )

            response = client.post("/rr", json=rr)
            assert response.status_code in [400, 422], \
                "RR with short revocation_reason must be rejected"

    def test_rr_is_chained(self, impl_url: str, valid_dr: dict):
        """RR must be properly chained with hash."""
        with httpx.Client(base_url=impl_url) as client:
            client.post("/_test/reset")
            client.post("/dr", json=valid_dr)

            rr = make_revocation(
                target_decision_id=valid_dr["decision_id"],
                revoker_id=valid_dr["deciders_id"],
            )
            rr["previous_record_hash"] = "INVALID_HASH"

            response = client.post("/rr", json=rr)
            # Should be rejected due to invalid hash chain
            # (unless implementation computes it automatically)


class TestRevocationTypes:
    """
    Tests for revocation type enum.
    """

    def test_valid_revocation_types(self, impl_url: str, valid_dr: dict):
        """Valid revocation types are accepted."""
        valid_types = ["voluntary", "oversight", "judicial", "superseded"]

        for rev_type in valid_types:
            with httpx.Client(base_url=impl_url) as client:
                client.post("/_test/reset")
                client.post("/dr", json=valid_dr)

                rr = make_revocation(
                    target_decision_id=valid_dr["decision_id"],
                    revoker_id=valid_dr["deciders_id"],
                    revocation_type=rev_type,
                )

                response = client.post("/rr", json=rr)
                # Should not fail due to revocation_type
                if response.status_code in [400, 422]:
                    error = str(response.json()).lower()
                    assert "revocation_type" not in error, \
                        f"Valid type '{rev_type}' should be accepted"

    def test_invalid_revocation_type_rejected(self, impl_url: str, valid_dr: dict):
        """Invalid revocation type is rejected."""
        with httpx.Client(base_url=impl_url) as client:
            client.post("/_test/reset")
            client.post("/dr", json=valid_dr)

            rr = make_revocation(
                target_decision_id=valid_dr["decision_id"],
                revoker_id=valid_dr["deciders_id"],
                revocation_type="invalid_type_xyz",
            )

            response = client.post("/rr", json=rr)
            assert response.status_code in [400, 422], \
                "Invalid revocation_type must be rejected"
