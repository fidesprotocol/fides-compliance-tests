"""
Test 01: Append-Only Behavior

Validates Fides v0.3 invariant:
- No retroactive alteration is possible
- No UPDATE operations permitted
- No DELETE operations permitted

Reference: FIDES-v0.3.md Section 8.2, Appendix F
"""

import pytest
import httpx

from .conftest import make_dr, make_payment


class TestAppendOnlyBehavior:
    """
    Tests that the implementation enforces append-only behavior.

    Per Section 8.2:
    - Append-only mode
    - No UPDATE
    - No DELETE
    - No overwrite
    """

    def test_create_dr_succeeds(self, impl_url: str, new_decision_id: str, genesis_hash: str):
        """Creating a new DR should succeed."""
        dr = make_dr(decision_id=new_decision_id, previous_record_hash=genesis_hash)

        with httpx.Client(base_url=impl_url) as client:
            response = client.post("/dr", json=dr)
            assert response.status_code in [200, 201], f"Expected success, got {response.status_code}"

    def test_update_dr_rejected(self, impl_url: str, valid_dr: dict):
        """Attempting to UPDATE an existing DR must be rejected."""
        decision_id = valid_dr["decision_id"]

        with httpx.Client(base_url=impl_url) as client:
            # First create the DR
            client.post("/dr", json=valid_dr)

            # Attempt to update it
            modified_dr = valid_dr.copy()
            modified_dr["maximum_value"] = 999999.99

            # PUT should be rejected
            response = client.put(f"/dr/{decision_id}", json=modified_dr)
            assert response.status_code in [400, 403, 404, 405, 409], \
                f"UPDATE must be rejected, got {response.status_code}"

            # PATCH should also be rejected
            response = client.patch(f"/dr/{decision_id}", json={"maximum_value": 999999.99})
            assert response.status_code in [400, 403, 404, 405, 409], \
                f"PATCH must be rejected, got {response.status_code}"

    def test_delete_dr_rejected(self, impl_url: str, valid_dr: dict):
        """Attempting to DELETE a DR must be rejected."""
        decision_id = valid_dr["decision_id"]

        with httpx.Client(base_url=impl_url) as client:
            # First create the DR
            client.post("/dr", json=valid_dr)

            # Attempt to delete it
            response = client.delete(f"/dr/{decision_id}")
            assert response.status_code in [400, 403, 404, 405, 409], \
                f"DELETE must be rejected, got {response.status_code}"

            # Verify the DR still exists
            response = client.get(f"/dr/{decision_id}")
            assert response.status_code == 200, "DR must still exist after failed DELETE"

    def test_overwrite_dr_rejected(self, impl_url: str, valid_dr: dict):
        """Attempting to overwrite a DR by re-POSTing must be rejected."""
        with httpx.Client(base_url=impl_url) as client:
            # First create the DR
            response1 = client.post("/dr", json=valid_dr)
            assert response1.status_code in [200, 201]

            # Attempt to overwrite with same decision_id
            modified_dr = valid_dr.copy()
            modified_dr["maximum_value"] = 999999.99

            response2 = client.post("/dr", json=modified_dr)
            assert response2.status_code in [400, 409], \
                f"Overwrite must be rejected, got {response2.status_code}"

    def test_dr_immutable_after_creation(self, impl_url: str, valid_dr: dict):
        """DR fields must remain unchanged after creation."""
        decision_id = valid_dr["decision_id"]

        with httpx.Client(base_url=impl_url) as client:
            # Create the DR
            client.post("/dr", json=valid_dr)

            # Retrieve it
            response = client.get(f"/dr/{decision_id}")
            assert response.status_code == 200

            stored_dr = response.json()

            # Verify key fields match
            assert stored_dr["decision_id"] == valid_dr["decision_id"]
            assert stored_dr["maximum_value"] == valid_dr["maximum_value"]
            assert stored_dr["beneficiary"] == valid_dr["beneficiary"]
            assert stored_dr["authority_id"] == valid_dr["authority_id"]

    def test_payment_ledger_append_only(self, impl_url: str, valid_dr: dict):
        """Payment ledger entries cannot be modified or deleted."""
        decision_id = valid_dr["decision_id"]

        with httpx.Client(base_url=impl_url) as client:
            # Create DR first
            client.post("/dr", json=valid_dr)

            # Create a payment
            payment = make_payment(
                decision_id=decision_id,
                payment_amount=1000.00,
                payment_currency=valid_dr["currency"],
                payment_beneficiary=valid_dr["beneficiary"],
            )

            response = client.post("/payment", json=payment)
            if response.status_code in [200, 201]:
                payment_id = response.json().get("payment_id", payment["payment_id"])

                # Attempt to update payment
                response = client.put(f"/payment/{payment_id}", json={"payment_amount": 9999})
                assert response.status_code in [400, 403, 404, 405, 409], \
                    "Payment UPDATE must be rejected"

                # Attempt to delete payment
                response = client.delete(f"/payment/{payment_id}")
                assert response.status_code in [400, 403, 404, 405, 409], \
                    "Payment DELETE must be rejected"

    def test_raw_database_no_update_delete(self, impl_url: str):
        """
        If test endpoint available, verify database-level UPDATE/DELETE are blocked.

        This tests the implementation's storage layer directly.
        """
        with httpx.Client(base_url=impl_url) as client:
            # Check if test endpoint exists
            response = client.get("/_test/raw")
            if response.status_code == 404:
                pytest.skip("Test endpoint /_test/raw not available")

            # If available, the endpoint should report no UPDATE/DELETE capability
            raw_info = response.json()
            assert raw_info.get("update_allowed") is False, \
                "Database must not allow UPDATE operations"
            assert raw_info.get("delete_allowed") is False, \
                "Database must not allow DELETE operations"


class TestAppendOnlyRecovery:
    """
    Tests that even error scenarios maintain append-only integrity.
    """

    def test_failed_creation_leaves_no_trace(self, impl_url: str, invalid_missing_fields: dict):
        """A failed DR creation should not leave partial data."""
        with httpx.Client(base_url=impl_url) as client:
            # Attempt to create invalid DR
            response = client.post("/dr", json=invalid_missing_fields)
            assert response.status_code in [400, 422], "Invalid DR should be rejected"

            # Verify nothing was stored
            decision_id = invalid_missing_fields.get("decision_id")
            if decision_id:
                response = client.get(f"/dr/{decision_id}")
                assert response.status_code == 404, "Failed creation must not store data"

    def test_revocation_does_not_delete(self, impl_url: str, valid_dr: dict, valid_rr: dict):
        """Revocation creates new record, does not delete original."""
        with httpx.Client(base_url=impl_url) as client:
            # Create DR
            client.post("/dr", json=valid_dr)

            # Create revocation
            rr = valid_rr.copy()
            rr["target_decision_id"] = valid_dr["decision_id"]
            client.post("/rr", json=rr)

            # Original DR must still exist
            response = client.get(f"/dr/{valid_dr['decision_id']}")
            assert response.status_code == 200, "Original DR must exist after revocation"

            # It should be marked as revoked, not deleted
            dr = response.json()
            assert dr.get("revoked") is True or "revoked" in str(dr), \
                "DR should be marked as revoked"
