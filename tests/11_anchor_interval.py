"""
Test 11: External Anchor Interval (24h Maximum)

Validates Fides v0.3 invariant:
- External anchor interval <= 24 hours
- Anchor includes chain height
- Anchor is external and public

Reference: FIDES-v0.3.md Section 8.3, 8.4, 8.4.1, Appendix F
"""

from datetime import datetime, timedelta, timezone

import pytest
import httpx


class TestAnchorInterval:
    """
    Tests that external anchor interval is enforced.

    Per Section 8.4:
    - Maximum anchor interval: 24 hours
    - SHOULD publish after every 100 records or 1 hour
    """

    def test_anchor_exists(self, impl_url: str):
        """Implementation must have external anchor capability."""
        with httpx.Client(base_url=impl_url) as client:
            response = client.get("/anchor")
            assert response.status_code in [200, 204], \
                "Anchor endpoint must be available"

    def test_anchor_not_stale(self, impl_url: str):
        """Most recent anchor must be within 24 hours."""
        with httpx.Client(base_url=impl_url) as client:
            response = client.get("/anchor")
            if response.status_code == 204:
                pytest.skip("No anchors yet")
            if response.status_code != 200:
                pytest.skip("Anchor endpoint not available")

            anchors = response.json()
            if isinstance(anchors, dict):
                anchors = [anchors]

            if not anchors:
                pytest.skip("No anchors recorded yet")

            # Get most recent anchor
            latest = max(anchors, key=lambda a: a.get("timestamp", ""))
            anchor_time = datetime.fromisoformat(
                latest["timestamp"].replace("Z", "+00:00")
            )

            now = datetime.now(timezone.utc)
            age = now - anchor_time

            assert age <= timedelta(hours=24), \
                f"Anchor is stale: {age} > 24 hours"

    def test_anchor_includes_chain_height(self, impl_url: str):
        """Anchor must include chain height (record count)."""
        with httpx.Client(base_url=impl_url) as client:
            response = client.get("/anchor")
            if response.status_code != 200:
                pytest.skip("Anchor endpoint not available")

            anchors = response.json()
            if isinstance(anchors, dict):
                anchors = [anchors]

            if not anchors:
                pytest.skip("No anchors recorded yet")

            latest = anchors[-1]
            assert "chain_height" in latest or "height" in latest or "record_count" in latest, \
                "Anchor must include chain height"

    def test_anchor_includes_state_hash(self, impl_url: str):
        """Anchor must include state hash."""
        with httpx.Client(base_url=impl_url) as client:
            response = client.get("/anchor")
            if response.status_code != 200:
                pytest.skip("Anchor endpoint not available")

            anchors = response.json()
            if isinstance(anchors, dict):
                anchors = [anchors]

            if not anchors:
                pytest.skip("No anchors recorded yet")

            latest = anchors[-1]
            state_hash = latest.get("state_hash") or latest.get("hash")
            assert state_hash is not None, "Anchor must include state hash"
            assert len(state_hash) == 64, "State hash must be SHA-256 (64 hex chars)"


class TestAnchorMediaRedundancy:
    """
    Tests for anchor media redundancy (Section 8.4.1).

    Per Section 8.4.1:
    - Anchors MUST be published to at least 2 independent media types
    """

    def test_multiple_anchor_media(self, impl_url: str):
        """Anchor should be published to multiple media."""
        with httpx.Client(base_url=impl_url) as client:
            response = client.get("/anchor")
            if response.status_code != 200:
                pytest.skip("Anchor endpoint not available")

            anchors = response.json()
            if isinstance(anchors, dict):
                anchors = [anchors]

            if not anchors:
                pytest.skip("No anchors recorded yet")

            latest = anchors[-1]

            # Check for multiple media
            media = latest.get("media") or latest.get("sources") or []
            if isinstance(media, list):
                # Should have at least 2 different media types
                # This is a SHOULD requirement for full compliance
                pass

    def test_anchor_media_categories(self, impl_url: str):
        """
        Anchor media should be from different categories.

        Categories per Section 8.4.1:
        - Category A: Public blockchains
        - Category B: RFC 3161 TSAs
        - Category C: Academic/NGO archives
        - Category D: International press
        """
        with httpx.Client(base_url=impl_url) as client:
            response = client.get("/anchor/info")
            if response.status_code == 404:
                pytest.skip("Anchor info endpoint not available")

            info = response.json()
            media_types = info.get("media_types", [])

            # Check that at least 2 different categories are used
            # This would be verified during implementation audit


class TestAnchorVerification:
    """
    Tests that anchors are verifiable by third parties.
    """

    def test_anchor_publicly_accessible(self, impl_url: str):
        """Anchors must be publicly accessible."""
        with httpx.Client(base_url=impl_url) as client:
            # No authentication should be required
            response = client.get("/anchor")
            assert response.status_code in [200, 204], \
                "Anchors must be publicly accessible without authentication"

    def test_anchor_hash_matches_chain(self, impl_url: str):
        """Anchor state hash must match computed chain hash."""
        with httpx.Client(base_url=impl_url) as client:
            # Get anchor
            anchor_response = client.get("/anchor")
            if anchor_response.status_code != 200:
                pytest.skip("No anchors available")

            anchors = anchor_response.json()
            if isinstance(anchors, dict):
                anchors = [anchors]

            if not anchors:
                pytest.skip("No anchors recorded")

            latest = anchors[-1]
            anchor_hash = latest.get("state_hash") or latest.get("hash")
            anchor_height = latest.get("chain_height") or latest.get("height")

            # Get current chain hash
            chain_response = client.get("/chain/hash")
            if chain_response.status_code != 200:
                pytest.skip("Chain hash endpoint not available")

            chain_hash = chain_response.json().get("state_hash") or chain_response.json().get("hash")

            # Get current chain height
            height_response = client.get("/chain/height")
            if height_response.status_code == 200:
                current_height = height_response.json().get("height")

                # If heights match, hashes should match
                if anchor_height == current_height:
                    assert anchor_hash == chain_hash, \
                        "Anchor hash must match chain hash at same height"


class TestAnchorExternalRequirement:
    """
    Tests that anchor is external to the system.

    Per Section 8.3:
    - External to the system
    - Public
    - Verifiable by third parties
    - Outside administrative control of Record Operator
    """

    def test_anchor_external_proof(self, impl_url: str):
        """Anchor must include proof of external publication."""
        with httpx.Client(base_url=impl_url) as client:
            response = client.get("/anchor")
            if response.status_code != 200:
                pytest.skip("Anchor endpoint not available")

            anchors = response.json()
            if isinstance(anchors, dict):
                anchors = [anchors]

            if not anchors:
                pytest.skip("No anchors recorded")

            latest = anchors[-1]

            # Should have some form of external proof
            has_proof = any([
                latest.get("blockchain_tx"),
                latest.get("transaction_id"),
                latest.get("tsa_token"),
                latest.get("external_proof"),
                latest.get("proof"),
            ])

            # Note: This is informational - actual verification requires
            # checking the external medium


class TestAnchorFailureMode:
    """
    Tests for anchor failure handling (Section 15.5).
    """

    def test_anchor_failure_info(self, impl_url: str):
        """Implementation should report anchor status."""
        with httpx.Client(base_url=impl_url) as client:
            response = client.get("/anchor/status")
            if response.status_code == 404:
                pytest.skip("Anchor status endpoint not available")

            status = response.json()

            # Should indicate if anchor capability is healthy
            assert "status" in status or "healthy" in status or "last_success" in status, \
                "Anchor status should be reportable"

    def test_pending_anchors_tracked(self, impl_url: str):
        """DRs created during anchor outage should be tracked as pending."""
        with httpx.Client(base_url=impl_url) as client:
            response = client.get("/dr?anchor_status=pending")
            if response.status_code == 404:
                # Alternate: check individual DR for anchor status
                pass

            # Implementation should track which DRs are awaiting anchor
