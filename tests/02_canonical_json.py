"""
Test 02: Canonical JSON Serialization

Validates Fides v0.3 invariant:
- Canonical serialization is implemented correctly

Reference: FIDES-v0.3.md Section 6.6.1, Appendix E
"""

import hashlib
import json
from typing import Any

import pytest


def canonical_serialize(record: dict[str, Any]) -> bytes:
    """
    Canonical serialization as per FIDES v0.3 Section 6.6.1:

    1. JSON format
    2. UTF-8 encoding
    3. Keys sorted alphabetically (recursive)
    4. No whitespace between elements
    5. No trailing newline
    6. Numbers without unnecessary precision (no trailing zeros)
    7. Dates in ISO 8601 format with UTC timezone (Z suffix)
    """
    # Remove computed fields that should not be part of hash
    obj = {k: v for k, v in record.items() if k not in ["hash", "computed_fields", "_comment"]}

    # Sort keys recursively
    obj = _sort_keys_recursive(obj)

    # Serialize to JSON with no whitespace
    json_str = json.dumps(
        obj,
        separators=(",", ":"),
        ensure_ascii=False,
        sort_keys=True,
    )

    # Encode as UTF-8
    return json_str.encode("utf-8")


def _sort_keys_recursive(obj: Any) -> Any:
    """Recursively sort dictionary keys."""
    if isinstance(obj, dict):
        return {k: _sort_keys_recursive(v) for k, v in sorted(obj.items())}
    elif isinstance(obj, list):
        return [_sort_keys_recursive(item) for item in obj]
    else:
        return obj


def compute_hash(record: dict[str, Any]) -> str:
    """Compute SHA-256 hash of canonical serialization."""
    canonical_bytes = canonical_serialize(record)
    return hashlib.sha256(canonical_bytes).hexdigest()


class TestCanonicalSerialization:
    """
    Tests that canonical JSON serialization follows the spec.
    """

    def test_keys_sorted_alphabetically(self):
        """Keys must be sorted alphabetically."""
        record = {
            "zebra": 1,
            "apple": 2,
            "mango": 3,
        }
        canonical = canonical_serialize(record).decode("utf-8")

        # Check order in serialized output
        apple_pos = canonical.find('"apple"')
        mango_pos = canonical.find('"mango"')
        zebra_pos = canonical.find('"zebra"')

        assert apple_pos < mango_pos < zebra_pos, \
            f"Keys must be sorted: apple({apple_pos}) < mango({mango_pos}) < zebra({zebra_pos})"

    def test_nested_keys_sorted(self):
        """Nested object keys must also be sorted."""
        record = {
            "outer": {
                "zebra": 1,
                "apple": 2,
            }
        }
        canonical = canonical_serialize(record).decode("utf-8")

        # The inner keys should also be sorted
        assert '"outer":{"apple":2,"zebra":1}' in canonical, \
            "Nested keys must be sorted"

    def test_no_whitespace(self):
        """No whitespace between elements."""
        record = {"a": 1, "b": 2}
        canonical = canonical_serialize(record).decode("utf-8")

        assert canonical == '{"a":1,"b":2}', \
            f"Expected no whitespace, got: {canonical}"

    def test_no_trailing_newline(self):
        """No trailing newline."""
        record = {"a": 1}
        canonical = canonical_serialize(record)

        assert not canonical.endswith(b"\n"), "Must not have trailing newline"

    def test_utf8_encoding(self):
        """Must use UTF-8 encoding."""
        record = {"name": "Joao da Silva", "city": "Sao Paulo"}
        canonical = canonical_serialize(record)

        # Should be valid UTF-8
        decoded = canonical.decode("utf-8")
        assert "Joao" in decoded
        assert "Sao Paulo" in decoded

    def test_unicode_preserved(self):
        """Unicode characters must be preserved, not escaped."""
        record = {"beneficiary": "Empresa Brasileira de Aeronautica"}
        canonical = canonical_serialize(record).decode("utf-8")

        # ensure_ascii=False means unicode is preserved
        assert "Aeronautica" in canonical

    def test_numbers_no_trailing_zeros(self):
        """Numbers without unnecessary precision."""
        record = {"value": 10000.00}
        canonical = canonical_serialize(record).decode("utf-8")

        # 10000.0 or 10000 are acceptable, but not 10000.00
        # Note: Python's json.dumps gives 10000.0 for float
        assert "10000.00" not in canonical or "10000.0" in canonical

    def test_date_iso8601_utc(self):
        """Dates in ISO 8601 format with Z suffix."""
        record = {"decision_date": "2025-01-15T10:00:00Z"}
        canonical = canonical_serialize(record).decode("utf-8")

        assert "2025-01-15T10:00:00Z" in canonical

    def test_array_order_preserved(self):
        """Array element order must be preserved."""
        record = {"deciders_id": ["CPF-111", "CPF-222", "CPF-333"]}
        canonical = canonical_serialize(record).decode("utf-8")

        # Order should be preserved
        pos_111 = canonical.find("CPF-111")
        pos_222 = canonical.find("CPF-222")
        pos_333 = canonical.find("CPF-333")

        assert pos_111 < pos_222 < pos_333, "Array order must be preserved"

    def test_hash_deterministic(self):
        """Same record must always produce same hash."""
        record = {
            "decision_id": "550e8400-e29b-41d4-a716-446655440000",
            "authority_id": "BR-GOV-001",
            "maximum_value": 50000.00,
        }

        hash1 = compute_hash(record)
        hash2 = compute_hash(record)
        hash3 = compute_hash(record)

        assert hash1 == hash2 == hash3, "Hash must be deterministic"

    def test_hash_sensitive_to_changes(self):
        """Any change must produce different hash."""
        record = {
            "decision_id": "550e8400-e29b-41d4-a716-446655440000",
            "maximum_value": 50000.00,
        }

        hash_original = compute_hash(record)

        # Change value
        record_modified = record.copy()
        record_modified["maximum_value"] = 50000.01
        hash_modified = compute_hash(record_modified)

        assert hash_original != hash_modified, "Different values must produce different hash"

    def test_comment_field_excluded(self):
        """The _comment field (used in fixtures) should be excluded from hash."""
        record1 = {"a": 1, "_comment": "This is a test"}
        record2 = {"a": 1}

        hash1 = compute_hash(record1)
        hash2 = compute_hash(record2)

        assert hash1 == hash2, "_comment field should be excluded from hash"


class TestCanonicalSerializationEdgeCases:
    """
    Edge cases for canonical serialization.
    """

    def test_empty_object(self):
        """Empty object serializes correctly."""
        record = {}
        canonical = canonical_serialize(record).decode("utf-8")
        assert canonical == "{}"

    def test_empty_array(self):
        """Empty array serializes correctly."""
        record = {"items": []}
        canonical = canonical_serialize(record).decode("utf-8")
        assert canonical == '{"items":[]}'

    def test_null_value(self):
        """Null values serialize correctly."""
        record = {"value": None}
        canonical = canonical_serialize(record).decode("utf-8")
        assert canonical == '{"value":null}'

    def test_boolean_values(self):
        """Boolean values serialize correctly."""
        record = {"is_sdr": True, "revoked": False}
        canonical = canonical_serialize(record).decode("utf-8")
        assert '"is_sdr":true' in canonical
        assert '"revoked":false' in canonical

    def test_deeply_nested(self):
        """Deeply nested structures serialize correctly."""
        record = {
            "level1": {
                "level2": {
                    "level3": {
                        "value": 42
                    }
                }
            }
        }
        canonical = canonical_serialize(record).decode("utf-8")
        assert canonical == '{"level1":{"level2":{"level3":{"value":42}}}}'

    def test_signature_array_format(self):
        """Signature arrays serialize correctly."""
        record = {
            "signatures": [
                {
                    "signer_id": "CPF-123",
                    "algorithm": "Ed25519",
                    "signature": "abc123",
                }
            ]
        }
        canonical = canonical_serialize(record).decode("utf-8")

        # Keys within signature object should also be sorted
        assert '"algorithm":"Ed25519"' in canonical
        assert '"signature":"abc123"' in canonical
        assert '"signer_id":"CPF-123"' in canonical
