"""
Test 03: Hash Chain Integrity

Validates Fides v0.3 invariant:
- Hash chain links all records
- Breaking the chain invalidates all subsequent records

Reference: FIDES-v0.3.md Section 6.6, 6.6.2, Appendix F
"""

import hashlib
import json
from typing import Any

import pytest
import httpx

from .conftest import make_dr


def _sort_keys_recursive(obj: Any) -> Any:
    """Recursively sort dictionary keys."""
    if isinstance(obj, dict):
        return {k: _sort_keys_recursive(v) for k, v in sorted(obj.items())}
    elif isinstance(obj, list):
        return [_sort_keys_recursive(item) for item in obj]
    return obj


def compute_hash(record: dict[str, Any]) -> str:
    """Compute SHA-256 hash of canonical serialization."""
    obj = {k: v for k, v in record.items() if k not in ["hash", "computed_fields", "_comment"]}
    obj = _sort_keys_recursive(obj)
    json_str = json.dumps(obj, separators=(",", ":"), ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(json_str.encode("utf-8")).hexdigest()


class TestHashChainIntegrity:
    """
    Tests that the implementation enforces hash chain integrity.

    Per Section 6.6:
    - Each record contains previous_record_hash = SHA-256(canonical(previous))
    - Breaking the chain invalidates all subsequent records
    """

    def test_first_record_uses_genesis_hash(self, impl_url: str):
        """First record in chain uses all-zeros genesis hash."""
        genesis_hash = "0" * 64

        dr = make_dr(previous_record_hash=genesis_hash)

        with httpx.Client(base_url=impl_url) as client:
            # Reset to clean state if possible
            client.post("/_test/reset")

            response = client.post("/dr", json=dr)
            assert response.status_code in [200, 201], \
                f"First record with genesis hash should succeed: {response.text}"

    def test_second_record_references_first(self, impl_url: str):
        """Second record must reference hash of first record."""
        genesis_hash = "0" * 64

        with httpx.Client(base_url=impl_url) as client:
            # Reset to clean state
            client.post("/_test/reset")

            # Create first DR
            dr1 = make_dr(previous_record_hash=genesis_hash)
            response1 = client.post("/dr", json=dr1)
            assert response1.status_code in [200, 201]

            # Get the stored first DR to compute its hash
            response = client.get(f"/dr/{dr1['decision_id']}")
            stored_dr1 = response.json()

            # Compute hash of first record
            first_hash = compute_hash(stored_dr1)

            # Create second DR referencing first
            dr2 = make_dr(previous_record_hash=first_hash)
            response2 = client.post("/dr", json=dr2)
            assert response2.status_code in [200, 201], \
                f"Second record with correct hash should succeed: {response2.text}"

    def test_wrong_previous_hash_rejected(self, impl_url: str, invalid_hash_chain: dict):
        """Record with incorrect previous_record_hash must be rejected."""
        with httpx.Client(base_url=impl_url) as client:
            response = client.post("/dr", json=invalid_hash_chain)
            assert response.status_code in [400, 409, 422], \
                f"Wrong previous_record_hash must be rejected: {response.status_code}"

    def test_chain_height_tracked(self, impl_url: str):
        """Implementation must track chain height (record count)."""
        with httpx.Client(base_url=impl_url) as client:
            response = client.get("/chain/height")
            if response.status_code == 404:
                pytest.skip("Chain height endpoint not available")

            height = response.json()
            assert isinstance(height.get("height"), int), \
                "Chain height must be an integer"
            assert height["height"] >= 0, \
                "Chain height must be non-negative"

    def test_chain_state_hash_available(self, impl_url: str):
        """Implementation must provide current chain state hash."""
        with httpx.Client(base_url=impl_url) as client:
            response = client.get("/chain/hash")
            if response.status_code == 404:
                pytest.skip("Chain hash endpoint not available")

            data = response.json()
            state_hash = data.get("state_hash") or data.get("hash")
            assert state_hash is not None, "State hash must be provided"
            assert len(state_hash) == 64, "State hash must be 64 hex characters (SHA-256)"

    def test_chain_divergence_detected(self, impl_url: str):
        """Any divergence between chain height and record count indicates tampering."""
        with httpx.Client(base_url=impl_url) as client:
            # Get chain height
            height_response = client.get("/chain/height")
            if height_response.status_code == 404:
                pytest.skip("Chain height endpoint not available")

            height = height_response.json().get("height", 0)

            # Get all DRs and count
            dr_response = client.get("/dr")
            if dr_response.status_code == 200:
                drs = dr_response.json()
                if isinstance(drs, list):
                    dr_count = len(drs)
                    assert dr_count == height, \
                        f"Chain height ({height}) must match DR count ({dr_count})"


class TestChainVerification:
    """
    Tests for independent chain verification capability.
    """

    def test_can_recalculate_hashes_locally(self, impl_url: str):
        """Any third party must be able to recalculate hashes locally."""
        with httpx.Client(base_url=impl_url) as client:
            # Get all DRs
            response = client.get("/dr")
            if response.status_code != 200:
                pytest.skip("Cannot list all DRs")

            drs = response.json()
            if not isinstance(drs, list) or len(drs) < 2:
                pytest.skip("Need at least 2 DRs for chain verification")

            # Sort by some ordering (assume record_timestamp or index)
            # Verify chain integrity
            for i in range(1, len(drs)):
                current_dr = drs[i]
                previous_dr = drs[i - 1]

                expected_hash = compute_hash(previous_dr)
                actual_hash = current_dr.get("previous_record_hash")

                assert actual_hash == expected_hash, \
                    f"Chain break at record {i}: expected {expected_hash}, got {actual_hash}"

    def test_chain_break_invalidates_subsequent(self, impl_url: str):
        """If chain is broken, all subsequent records are invalid."""
        with httpx.Client(base_url=impl_url) as client:
            # This test verifies the BEHAVIOR when a break is detected
            response = client.get("/chain/verify")
            if response.status_code == 404:
                pytest.skip("Chain verification endpoint not available")

            result = response.json()

            if result.get("valid") is False:
                # If chain is broken, there should be info about invalid records
                assert "break_at" in result or "invalid_from" in result, \
                    "Chain break must identify where break occurred"


class TestSingleAuthoritativeChain:
    """
    Tests that there is exactly ONE authoritative chain (Section 6.6.2).
    """

    def test_no_parallel_chains(self, impl_url: str):
        """There must be exactly one authoritative chain."""
        with httpx.Client(base_url=impl_url) as client:
            # Get chain info
            response = client.get("/chain/info")
            if response.status_code == 404:
                # Try alternate endpoint
                response = client.get("/chain/height")
                if response.status_code == 404:
                    pytest.skip("Chain info endpoint not available")

            info = response.json()

            # Should only report one chain
            chain_count = info.get("chain_count", 1)
            assert chain_count == 1, \
                f"Must have exactly one chain, found {chain_count}"

    def test_fork_not_possible(self, impl_url: str):
        """Creating a fork (two records with same previous_hash) must be rejected."""
        genesis_hash = "0" * 64

        with httpx.Client(base_url=impl_url) as client:
            # Reset
            client.post("/_test/reset")

            # Create first DR
            dr1 = make_dr(previous_record_hash=genesis_hash)
            response1 = client.post("/dr", json=dr1)
            assert response1.status_code in [200, 201]

            # Get hash of first record
            stored = client.get(f"/dr/{dr1['decision_id']}").json()
            first_hash = compute_hash(stored)

            # Create second DR
            dr2 = make_dr(previous_record_hash=first_hash)
            response2 = client.post("/dr", json=dr2)
            assert response2.status_code in [200, 201]

            # Attempt to create fork (another DR with same previous_hash as dr2)
            dr3_fork = make_dr(previous_record_hash=first_hash)
            response3 = client.post("/dr", json=dr3_fork)

            # This should be rejected - would create a fork
            assert response3.status_code in [400, 409, 422], \
                f"Fork creation must be rejected: {response3.status_code}"
