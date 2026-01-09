# Fides Compliance Test Suite

Official compliance test suite for validating Fides Protocol v0.3 implementations.

## Overview

This test suite validates that an implementation correctly enforces all invariants defined in the Fides Protocol specification (Appendix F). Passing all tests is **mandatory** for claiming Fides v0.3 compatibility.

## Requirements

- Python 3.10+
- pytest
- cryptography
- pynacl (for Ed25519)

Install dependencies:

```bash
pip install -r requirements.txt
```

## Running Tests

### Against a Local Implementation

```bash
# Set the implementation URL or module path
export FIDES_IMPL_URL="http://localhost:8000"

# Run all tests
python runner.py

# Or use pytest directly
pytest tests/ -v
```

### Test Categories

| Test File | Invariant | Description |
|-----------|-----------|-------------|
| `01_append_only.py` | Immutability | No UPDATE/DELETE operations possible |
| `02_canonical_json.py` | Serialization | Canonical JSON format for hashing |
| `03_hash_chain.py` | Chain Integrity | Hash chain links all records |
| `04_signatures.py` | Cryptographic Signatures | All signatures verifiable |
| `05_timestamps.py` | Timestamp Attestation | External timestamp proofs valid |
| `06_payment_auth.py` | Payment Authorization | No payment without valid DR |
| `07_payment_serial.py` | Payment Serialization | Concurrent payments serialized |
| `08_sdr_expiration.py` | SDR Enforcement | SDR expiration enforced |
| `09_revocation.py` | Revocation Authority | Revocation rules enforced |
| `10_registration_delay.py` | Registration Delay | 72h maximum delay enforced |
| `11_anchor_interval.py` | Anchor Interval | 24h maximum interval enforced |

## Implementation Interface

Your implementation must expose these endpoints/functions:

### Decision Records

```
POST /dr - Create Decision Record
GET /dr/{decision_id} - Get Decision Record
GET /dr - List all Decision Records
```

### Payments

```
POST /payment/authorize - Check payment authorization
POST /payment - Execute payment
GET /payment - List all payments
```

### Chain

```
GET /chain/hash - Get current chain state hash
GET /chain/height - Get chain height
GET /anchor - Get external anchors
```

### For Testing (optional but recommended)

```
POST /_test/reset - Reset to clean state
POST /_test/inject - Inject test data
GET /_test/raw - Get raw database state
```

## Fixtures

The `fixtures/` directory contains:

- `valid_dr.json` - Valid Decision Record example
- `valid_sdr.json` - Valid Special Decision Record
- `valid_rr.json` - Valid Revocation Record
- `valid_payment.json` - Valid payment
- `invalid_missing_fields.json` - DR missing required fields
- `invalid_signature.json` - DR with invalid signature
- `invalid_timestamp.json` - DR with invalid timestamp attestation
- `invalid_hash_chain.json` - DR with wrong previous_record_hash
- `invalid_sdr_expired.json` - Expired SDR
- `invalid_beneficiary.json` - Payment with wrong beneficiary

## Writing Custom Tests

```python
from fides_test_base import FidesTestBase, valid_dr, invalid_dr

class TestCustom(FidesTestBase):
    def test_my_invariant(self):
        # Create a valid DR
        dr = valid_dr()
        response = self.create_dr(dr)
        assert response.status == 201

        # Try an invalid operation
        with pytest.raises(FidesInvariantViolation):
            self.update_dr(dr["decision_id"], {"maximum_value": 999})
```

## Compliance Certification

After passing all tests:

1. Generate compliance report: `python runner.py --report`
2. Submit report to fidesprotocol/compliance-registry
3. Receive compliance badge for your implementation

## License

AGPLv3 - See [LICENSE](LICENSE)

## References

- [Fides Protocol Specification v0.3](https://github.com/fidesprotocol/spec)
- [Appendix F: Invariants](https://github.com/fidesprotocol/spec/blob/main/FIDES-v0.3.md#appendix-f-invariants-compliance-checklist)
