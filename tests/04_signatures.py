"""
Test 04: Cryptographic Signatures

Validates Fides v0.3 invariant:
- Signatures are cryptographically verifiable
- Every decider must have a valid signature
- Acceptable algorithms: Ed25519, ECDSA-P256, ECDSA-P384, RSA-PSS

Reference: FIDES-v0.3.md Section 6.3.2, Appendix F
"""

import base64
from datetime import datetime, timezone

import pytest
import httpx
from nacl.signing import SigningKey, VerifyKey
from nacl.exceptions import BadSignature

from .conftest import make_dr
from .test_02_canonical_json import canonical_serialize


def generate_ed25519_keypair():
    """Generate Ed25519 keypair for testing."""
    signing_key = SigningKey.generate()
    verify_key = signing_key.verify_key
    return signing_key, verify_key


def sign_record(record: dict, signing_key: SigningKey, signer_id: str) -> dict:
    """Sign a record with Ed25519."""
    # Get canonical bytes to sign
    canonical_bytes = canonical_serialize(record)

    # Sign
    signed = signing_key.sign(canonical_bytes)
    signature = base64.b64encode(signed.signature).decode("ascii")

    # Get public key
    public_key = base64.b64encode(bytes(signing_key.verify_key)).decode("ascii")

    return {
        "signer_id": signer_id,
        "public_key": public_key,
        "algorithm": "Ed25519",
        "signature": signature,
        "signed_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
    }


def verify_ed25519_signature(record: dict, signature_obj: dict) -> bool:
    """Verify an Ed25519 signature."""
    try:
        public_key_bytes = base64.b64decode(signature_obj["public_key"])
        signature_bytes = base64.b64decode(signature_obj["signature"])

        verify_key = VerifyKey(public_key_bytes)

        # Get canonical bytes
        record_without_sigs = {k: v for k, v in record.items() if k != "signatures"}
        canonical_bytes = canonical_serialize(record_without_sigs)

        verify_key.verify(canonical_bytes, signature_bytes)
        return True
    except (BadSignature, Exception):
        return False


class TestSignaturePresence:
    """
    Tests that signatures are present and properly structured.
    """

    def test_dr_must_have_signatures(self, impl_url: str):
        """Every DR must have a signatures array."""
        dr = make_dr()
        # Remove signatures
        dr.pop("signatures", None)

        with httpx.Client(base_url=impl_url) as client:
            response = client.post("/dr", json=dr)
            assert response.status_code in [400, 422], \
                "DR without signatures must be rejected"

    def test_every_decider_must_sign(self, impl_url: str):
        """Every decider_id must have corresponding signature."""
        signing_key, verify_key = generate_ed25519_keypair()

        dr = make_dr(deciders_id=["DECIDER-1", "DECIDER-2"])

        # Only sign for one decider
        dr["signatures"] = [
            sign_record(dr, signing_key, "DECIDER-1")
        ]

        with httpx.Client(base_url=impl_url) as client:
            response = client.post("/dr", json=dr)
            assert response.status_code in [400, 422], \
                f"DR with missing signature must be rejected: {response.status_code}"

    def test_signature_must_match_decider(self, impl_url: str, invalid_signature: dict):
        """Signature signer_id must match a deciders_id entry."""
        with httpx.Client(base_url=impl_url) as client:
            response = client.post("/dr", json=invalid_signature)
            assert response.status_code in [400, 422], \
                "Signature with non-matching signer_id must be rejected"


class TestSignatureVerification:
    """
    Tests that signatures are cryptographically verified.
    """

    def test_valid_signature_accepted(self, impl_url: str):
        """Valid cryptographic signature is accepted."""
        signing_key, verify_key = generate_ed25519_keypair()

        dr = make_dr(deciders_id=["TEST-SIGNER"])

        # Create proper signature
        sig = sign_record(dr, signing_key, "TEST-SIGNER")
        dr["signatures"] = [sig]

        with httpx.Client(base_url=impl_url) as client:
            # Reset for clean test
            client.post("/_test/reset")

            response = client.post("/dr", json=dr)
            # May fail for other reasons (timestamp, etc) but not for signature
            if response.status_code in [400, 422]:
                error = response.json()
                error_msg = str(error)
                assert "signature" not in error_msg.lower(), \
                    f"Valid signature should not cause error: {error}"

    def test_invalid_signature_rejected(self, impl_url: str):
        """Invalid cryptographic signature is rejected."""
        signing_key, _ = generate_ed25519_keypair()

        dr = make_dr(deciders_id=["TEST-SIGNER"])

        # Create signature but corrupt it
        sig = sign_record(dr, signing_key, "TEST-SIGNER")
        sig["signature"] = base64.b64encode(b"INVALID" * 10).decode("ascii")
        dr["signatures"] = [sig]

        with httpx.Client(base_url=impl_url) as client:
            response = client.post("/dr", json=dr)
            assert response.status_code in [400, 422], \
                "Invalid signature must be rejected"

    def test_wrong_public_key_rejected(self, impl_url: str):
        """Signature with wrong public key is rejected."""
        signing_key1, _ = generate_ed25519_keypair()
        _, wrong_verify_key = generate_ed25519_keypair()

        dr = make_dr(deciders_id=["TEST-SIGNER"])

        # Sign with key1 but use key2's public key
        sig = sign_record(dr, signing_key1, "TEST-SIGNER")
        sig["public_key"] = base64.b64encode(bytes(wrong_verify_key)).decode("ascii")
        dr["signatures"] = [sig]

        with httpx.Client(base_url=impl_url) as client:
            response = client.post("/dr", json=dr)
            assert response.status_code in [400, 422], \
                "Wrong public key must cause rejection"

    def test_tampered_record_detected(self, impl_url: str):
        """Modification after signing must be detected."""
        signing_key, _ = generate_ed25519_keypair()

        dr = make_dr(deciders_id=["TEST-SIGNER"], maximum_value=10000.00)

        # Sign the record
        sig = sign_record(dr, signing_key, "TEST-SIGNER")
        dr["signatures"] = [sig]

        # Tamper with the record after signing
        dr["maximum_value"] = 99999.99

        with httpx.Client(base_url=impl_url) as client:
            response = client.post("/dr", json=dr)
            assert response.status_code in [400, 422], \
                "Tampered record must be rejected"


class TestSignatureAlgorithms:
    """
    Tests for supported signature algorithms.
    """

    def test_ed25519_supported(self, impl_url: str):
        """Ed25519 (recommended) must be supported."""
        signing_key, _ = generate_ed25519_keypair()
        dr = make_dr(deciders_id=["TEST-SIGNER"])

        sig = sign_record(dr, signing_key, "TEST-SIGNER")
        assert sig["algorithm"] == "Ed25519"
        dr["signatures"] = [sig]

        with httpx.Client(base_url=impl_url) as client:
            client.post("/_test/reset")
            response = client.post("/dr", json=dr)
            # Should not fail due to algorithm
            if response.status_code in [400, 422]:
                error = str(response.json())
                assert "algorithm" not in error.lower() or "ed25519" not in error.lower(), \
                    "Ed25519 must be supported"

    def test_unknown_algorithm_rejected(self, impl_url: str):
        """Unknown signature algorithm must be rejected."""
        dr = make_dr(deciders_id=["TEST-SIGNER"])

        dr["signatures"] = [{
            "signer_id": "TEST-SIGNER",
            "public_key": "AAAA",
            "algorithm": "UNKNOWN-ALGO-999",
            "signature": "BBBB",
            "signed_at": "2025-01-15T10:00:00Z",
        }]

        with httpx.Client(base_url=impl_url) as client:
            response = client.post("/dr", json=dr)
            assert response.status_code in [400, 422], \
                "Unknown algorithm must be rejected"


class TestSignatureTimestamp:
    """
    Tests for signature timestamp requirements.
    """

    def test_signature_has_timestamp(self, valid_dr: dict):
        """Each signature must include signed_at timestamp."""
        for sig in valid_dr.get("signatures", []):
            assert "signed_at" in sig, "Signature must have signed_at"
            # Should be valid ISO 8601
            try:
                datetime.fromisoformat(sig["signed_at"].replace("Z", "+00:00"))
            except ValueError:
                pytest.fail(f"signed_at must be valid ISO 8601: {sig['signed_at']}")

    def test_signature_timestamp_not_future(self, impl_url: str):
        """Signature timestamp cannot be in the future."""
        signing_key, _ = generate_ed25519_keypair()
        dr = make_dr(deciders_id=["TEST-SIGNER"])

        sig = sign_record(dr, signing_key, "TEST-SIGNER")
        # Set timestamp to far future
        sig["signed_at"] = "2099-12-31T23:59:59Z"
        dr["signatures"] = [sig]

        with httpx.Client(base_url=impl_url) as client:
            response = client.post("/dr", json=dr)
            assert response.status_code in [400, 422], \
                "Future signature timestamp should be rejected"
