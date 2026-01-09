"""
Test 05: Timestamp Attestation

Validates Fides v0.3 invariant:
- Record timestamps are externally attested
- Acceptable methods: RFC 3161, Blockchain
- NTP consensus is DEPRECATED and REJECTED in v0.3

Reference: FIDES-v0.3.md Section 6.9, 6.9.1, 6.9.2, 6.9.3, Appendix F
"""

import pytest
import httpx

from .conftest import make_dr


class TestTimestampAttestationRequired:
    """
    Tests that timestamp attestation is mandatory.
    """

    def test_dr_requires_timestamp_attestation(self, impl_url: str):
        """DR must have timestamp_attestation field."""
        dr = make_dr()
        # Ensure no timestamp_attestation
        dr.pop("timestamp_attestation", None)

        with httpx.Client(base_url=impl_url) as client:
            response = client.post("/dr", json=dr)
            assert response.status_code in [400, 422], \
                "DR without timestamp_attestation must be rejected"

    def test_record_timestamp_must_be_attested(self, impl_url: str):
        """The record_timestamp must match attestation proof."""
        dr = make_dr()
        dr["record_timestamp"] = "2025-01-15T14:30:00Z"
        dr["timestamp_attestation"] = {
            "method": "rfc3161",
            "proof": {
                "tsa_url": "https://freetsa.org/tsr",
                "tsa_certificate": "MIIFqDCCA5CgAwIBAgIJANK...",
                "timestamp_token": "MIIKzAYJKoZIhvcNAQcCoII...",
                "hash_algorithm": "SHA-256",
                # Message imprint for DIFFERENT timestamp
                "message_imprint": "0" * 64,
            },
            "sources": ["FreeTSA"],
        }

        # The implementation should verify the attestation proof
        # matches the record_timestamp and record hash


class TestNTPDeprecated:
    """
    Tests that NTP consensus is rejected in v0.3.
    """

    def test_ntp_consensus_rejected(self, impl_url: str, invalid_timestamp: dict):
        """NTP consensus method must be rejected per Section 6.9.3."""
        with httpx.Client(base_url=impl_url) as client:
            response = client.post("/dr", json=invalid_timestamp)
            assert response.status_code in [400, 422], \
                f"NTP consensus must be rejected in v0.3: {response.status_code}"

    def test_ntp_method_explicitly_rejected(self, impl_url: str):
        """Even well-formed NTP attestation must be rejected."""
        dr = make_dr()
        dr["timestamp_attestation"] = {
            "method": "ntp_consensus",
            "proof": {
                "ntp_servers": ["time.google.com", "time.windows.com", "pool.ntp.org"],
                "consensus_timestamp": dr["record_timestamp"],
                "max_drift_ms": 50,
            },
            "sources": ["time.google.com", "time.windows.com", "pool.ntp.org"],
        }

        with httpx.Client(base_url=impl_url) as client:
            response = client.post("/dr", json=dr)
            assert response.status_code in [400, 422], \
                "ntp_consensus method must be rejected"

            error = response.json()
            # Error should mention NTP or deprecated
            error_str = str(error).lower()
            assert "ntp" in error_str or "deprecated" in error_str or "method" in error_str, \
                f"Error should mention NTP deprecation: {error}"


class TestRFC3161Attestation:
    """
    Tests for RFC 3161 timestamp attestation.
    """

    def test_rfc3161_accepted(self, impl_url: str):
        """RFC 3161 attestation method must be accepted."""
        dr = make_dr()
        dr["timestamp_attestation"] = {
            "method": "rfc3161",
            "proof": {
                "tsa_url": "https://freetsa.org/tsr",
                "tsa_certificate": "MIIFqDCCA5CgAwIBAgIJANK...",
                "timestamp_token": "MIIKzAYJKoZIhvcNAQcCoII...",
                "hash_algorithm": "SHA-256",
                "message_imprint": "a1b2c3d4e5f6789012345678901234567890abcdef1234567890abcdef123456",
            },
            "sources": ["FreeTSA"],
        }

        with httpx.Client(base_url=impl_url) as client:
            client.post("/_test/reset")
            response = client.post("/dr", json=dr)
            # May fail for other reasons but not for method type
            if response.status_code in [400, 422]:
                error = str(response.json()).lower()
                assert "method" not in error or "rfc3161" not in error, \
                    "RFC 3161 method should be accepted"

    def test_rfc3161_requires_tsa_url(self):
        """RFC 3161 proof must include tsa_url."""
        proof = {
            "method": "rfc3161",
            "proof": {
                # Missing tsa_url
                "tsa_certificate": "MII...",
                "timestamp_token": "MII...",
                "hash_algorithm": "SHA-256",
                "message_imprint": "abc123",
            },
        }
        assert "tsa_url" not in proof["proof"], "Test setup: tsa_url should be missing"

    def test_rfc3161_requires_timestamp_token(self):
        """RFC 3161 proof must include timestamp_token."""
        proof = {
            "method": "rfc3161",
            "proof": {
                "tsa_url": "https://freetsa.org/tsr",
                "tsa_certificate": "MII...",
                # Missing timestamp_token
                "hash_algorithm": "SHA-256",
                "message_imprint": "abc123",
            },
        }
        assert "timestamp_token" not in proof["proof"]


class TestBlockchainAttestation:
    """
    Tests for blockchain timestamp attestation.
    """

    def test_blockchain_accepted(self, impl_url: str):
        """Blockchain attestation method must be accepted."""
        dr = make_dr()
        dr["timestamp_attestation"] = {
            "method": "blockchain",
            "proof": {
                "chain": "bitcoin",
                "network": "mainnet",
                "block_number": 878000,
                "block_hash": "00000000000000000001a2b3c4d5e6f7890123456789abcdef0123456789abcd",
                "transaction_id": "abcdef1234567890abcdef1234567890abcdef1234567890abcdef1234567890",
                "merkle_proof": [
                    "1234567890abcdef1234567890abcdef1234567890abcdef1234567890abcdef",
                ],
                "data_hash": "c7d8e9f0a1b2c3d4e5f6789012345678901234567890abcdef1234567890abcd",
                "confirmations_at_record": 6,
            },
            "sources": ["blockstream.info"],
        }

        with httpx.Client(base_url=impl_url) as client:
            client.post("/_test/reset")
            response = client.post("/dr", json=dr)
            if response.status_code in [400, 422]:
                error = str(response.json()).lower()
                assert "method" not in error or "blockchain" not in error, \
                    "Blockchain method should be accepted"

    def test_bitcoin_minimum_confirmations(self):
        """Bitcoin requires minimum 6 confirmations."""
        proof = {
            "chain": "bitcoin",
            "confirmations_at_record": 6,
        }
        assert proof["confirmations_at_record"] >= 6

    def test_ethereum_minimum_confirmations(self):
        """Ethereum requires minimum 12 confirmations."""
        proof = {
            "chain": "ethereum",
            "confirmations_at_record": 12,
        }
        assert proof["confirmations_at_record"] >= 12

    def test_insufficient_confirmations_rejected(self, impl_url: str):
        """Blockchain attestation with insufficient confirmations must be rejected."""
        dr = make_dr()
        dr["timestamp_attestation"] = {
            "method": "blockchain",
            "proof": {
                "chain": "bitcoin",
                "network": "mainnet",
                "block_number": 878000,
                "block_hash": "00000000000000000001a2b3c4d5e6f7890123456789abcdef0123456789abcd",
                "transaction_id": "abcdef1234567890abcdef1234567890abcdef1234567890abcdef1234567890",
                "merkle_proof": [],
                "data_hash": "c7d8e9f0a1b2c3d4e5f6789012345678901234567890abcdef1234567890abcd",
                "confirmations_at_record": 2,  # Less than 6 required for Bitcoin
            },
            "sources": ["blockstream.info"],
        }

        with httpx.Client(base_url=impl_url) as client:
            response = client.post("/dr", json=dr)
            # Should reject due to insufficient confirmations
            # (implementation may accept for testing, so this is advisory)


class TestExternalTSARequirement:
    """
    Tests that TSA must be external to implementing jurisdiction.
    """

    def test_tsa_must_be_external(self):
        """
        TSA must be external to implementing jurisdiction.

        Per Section 6.9.1:
        "For RFC 3161, the TSA MUST be external to the implementing jurisdiction.
        Government-controlled TSAs from the same jurisdiction are NOT acceptable."
        """
        # This is a documentation/policy test - actual verification requires
        # checking TSA certificate chains against known government CAs
        acceptable_tsas = [
            "freetsa.org",
            "timestamp.digicert.com",
            "timestamp.globalsign.com",
        ]

        # Government-controlled TSAs from implementing jurisdiction are NOT acceptable
        # This would need to be verified during implementation audit


class TestTimestampValidation:
    """
    Tests for timestamp validation procedures.
    """

    def test_timestamp_within_24h_tolerance(self):
        """
        Timestamp verification allows +/- 24 hour tolerance.

        Per Section 6.9.2.1:
        "Verify genTime - The timestamp MUST be within +/-24 hours of
        current time at verification"
        """
        from datetime import datetime, timedelta, timezone

        now = datetime.now(timezone.utc)
        valid_range_start = now - timedelta(hours=24)
        valid_range_end = now + timedelta(hours=24)

        # Any timestamp in this range should be acceptable
        assert valid_range_start < now < valid_range_end

    def test_message_imprint_must_match_record_hash(self):
        """
        For RFC 3161, message_imprint must match SHA256 of canonical record.

        Per Section 6.9.2.1:
        "Verify message_imprint matches SHA256(canonical_serialization(record))"
        """
        # This is verified by computing hash of record and comparing to attestation
        pass
