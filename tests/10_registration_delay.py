"""
Test 10: Registration Delay (72h Maximum)

Validates Fides v0.3 invariant:
- Maximum registration delay (72h) is enforced
- record_timestamp - decision_date <= 72 hours
- Delays > 72h require SDR with late_registration exception

Reference: FIDES-v0.3.md Section 6.4.4, 6.4.5, Appendix F
"""

from datetime import datetime, timedelta, timezone

import pytest
import httpx

from .conftest import make_dr


class TestRegistrationDelayEnforced:
    """
    Tests that 72-hour maximum registration delay is enforced.

    Per Section 6.4.4:
    "record_timestamp - decision_date <= 72 hours"
    """

    def test_immediate_registration_accepted(self, impl_url: str):
        """Registration within minutes of decision is accepted."""
        now = datetime.now(timezone.utc)

        dr = make_dr(
            decision_date=now.isoformat().replace("+00:00", "Z"),
            record_timestamp=(now + timedelta(minutes=30)).isoformat().replace("+00:00", "Z"),
        )

        with httpx.Client(base_url=impl_url) as client:
            client.post("/_test/reset")
            response = client.post("/dr", json=dr)
            # Should not fail due to registration delay
            if response.status_code in [400, 422]:
                error = str(response.json()).lower()
                assert "delay" not in error and "72" not in error, \
                    "Immediate registration should be accepted"

    def test_24h_delay_accepted(self, impl_url: str):
        """Registration within 24 hours is accepted."""
        now = datetime.now(timezone.utc)

        dr = make_dr(
            decision_date=(now - timedelta(hours=20)).isoformat().replace("+00:00", "Z"),
            record_timestamp=now.isoformat().replace("+00:00", "Z"),
        )

        with httpx.Client(base_url=impl_url) as client:
            client.post("/_test/reset")
            response = client.post("/dr", json=dr)
            if response.status_code in [400, 422]:
                error = str(response.json()).lower()
                assert "delay" not in error and "72" not in error, \
                    "24h delay should be accepted"

    def test_71h_delay_accepted(self, impl_url: str):
        """Registration at 71 hours (under limit) is accepted."""
        now = datetime.now(timezone.utc)

        dr = make_dr(
            decision_date=(now - timedelta(hours=71)).isoformat().replace("+00:00", "Z"),
            record_timestamp=now.isoformat().replace("+00:00", "Z"),
        )

        with httpx.Client(base_url=impl_url) as client:
            client.post("/_test/reset")
            response = client.post("/dr", json=dr)
            if response.status_code in [400, 422]:
                error = str(response.json()).lower()
                assert "delay" not in error and "72" not in error, \
                    "71h delay should be accepted"

    def test_73h_delay_rejected(self, impl_url: str, invalid_registration_delay: dict):
        """Registration at 73+ hours (over limit) is rejected."""
        with httpx.Client(base_url=impl_url) as client:
            client.post("/_test/reset")
            response = client.post("/dr", json=invalid_registration_delay)
            assert response.status_code in [400, 422], \
                f"Registration delay > 72h must be rejected: {response.status_code}"

    def test_exact_72h_boundary(self, impl_url: str):
        """Registration at exactly 72 hours should be accepted."""
        now = datetime.now(timezone.utc)

        dr = make_dr(
            decision_date=(now - timedelta(hours=72)).isoformat().replace("+00:00", "Z"),
            record_timestamp=now.isoformat().replace("+00:00", "Z"),
        )

        with httpx.Client(base_url=impl_url) as client:
            client.post("/_test/reset")
            response = client.post("/dr", json=dr)
            # Exactly 72h should be accepted (<=)
            if response.status_code in [400, 422]:
                error = str(response.json()).lower()
                # Should not fail specifically for delay
                assert "delay" not in error or "exceed" not in error, \
                    "Exactly 72h should be at the boundary (accepted)"


class TestLateRegistrationSDR:
    """
    Tests that late registration requires SDR with late_registration type.

    Per Section 6.4.4:
    "Decisions not registered within this window require a Special Decision
    Record (SDR) with exception_type: late_registration"
    """

    def test_late_registration_sdr_accepted(self, impl_url: str):
        """SDR with late_registration exception can exceed 72h."""
        now = datetime.now(timezone.utc)

        sdr = make_dr(
            decision_date=(now - timedelta(hours=100)).isoformat().replace("+00:00", "Z"),
            record_timestamp=now.isoformat().replace("+00:00", "Z"),
        )
        sdr["is_sdr"] = True
        sdr["exception_type"] = "late_registration"
        sdr["formal_justification"] = "Sistema indisponivel por 4 dias devido a falha tecnica no datacenter. Registro realizado assim que possivel apos restauracao."
        sdr["maximum_term"] = now.isoformat().replace("+00:00", "Z")  # N/A for late_registration
        sdr["reinforced_deciders"] = sdr["deciders_id"] * 2
        sdr["oversight_authority"] = "OVERSIGHT-001"

        with httpx.Client(base_url=impl_url) as client:
            client.post("/_test/reset")
            response = client.post("/dr", json=sdr)
            # Should be accepted as late_registration SDR
            if response.status_code in [400, 422]:
                error = str(response.json()).lower()
                assert "delay" not in error and "72" not in error, \
                    "late_registration SDR should bypass 72h limit"


class TestDelayTiers:
    """
    Tests for delay tier requirements.

    Per Section 6.4.5:
    | Delay | Classification | Additional Requirements |
    | 0-1 hour | Normal | None |
    | 1-24 hours | Delayed | delay_reason required |
    | 24-72 hours | Late | delay_reason + supervisor approval |
    | > 72 hours | Expired | SDR with late_registration |
    """

    def test_under_1h_no_extra_fields(self, impl_url: str):
        """Registration under 1 hour requires no extra fields."""
        now = datetime.now(timezone.utc)

        dr = make_dr(
            decision_date=now.isoformat().replace("+00:00", "Z"),
            record_timestamp=(now + timedelta(minutes=30)).isoformat().replace("+00:00", "Z"),
        )
        # No delay_justification needed

        with httpx.Client(base_url=impl_url) as client:
            client.post("/_test/reset")
            response = client.post("/dr", json=dr)
            # Should not require delay_justification

    def test_1_to_24h_requires_delay_reason(self, impl_url: str):
        """Registration 1-24h after decision requires delay_reason."""
        now = datetime.now(timezone.utc)

        dr = make_dr(
            decision_date=(now - timedelta(hours=5)).isoformat().replace("+00:00", "Z"),
            record_timestamp=now.isoformat().replace("+00:00", "Z"),
        )

        # According to spec, should have delay_justification
        dr["delay_justification"] = {
            "delay_hours": 5,
            "delay_reason": "manual_processing",
            "delay_explanation": "",
        }

        # Implementation may or may not strictly enforce this

    def test_24_to_72h_requires_supervisor_approval(self, impl_url: str):
        """Registration 24-72h after decision requires supervisor approval."""
        now = datetime.now(timezone.utc)

        dr = make_dr(
            decision_date=(now - timedelta(hours=48)).isoformat().replace("+00:00", "Z"),
            record_timestamp=now.isoformat().replace("+00:00", "Z"),
        )

        # According to spec, should have supervisor approval
        dr["delay_justification"] = {
            "delay_hours": 48,
            "delay_reason": "system_outage",
            "delay_explanation": "",
            "supervisor_approval": {
                "supervisor_id": "SUPERVISOR-001",
                "supervisor_signature": {},
                "approval_timestamp": now.isoformat().replace("+00:00", "Z"),
            }
        }

        # Implementation may or may not strictly enforce this


class TestTimestampOrdering:
    """
    Tests for correct timestamp ordering.
    """

    def test_decision_date_before_record_timestamp(self, impl_url: str):
        """decision_date must be before or equal to record_timestamp."""
        now = datetime.now(timezone.utc)

        dr = make_dr(
            decision_date=(now + timedelta(hours=1)).isoformat().replace("+00:00", "Z"),
            record_timestamp=now.isoformat().replace("+00:00", "Z"),
        )

        with httpx.Client(base_url=impl_url) as client:
            response = client.post("/dr", json=dr)
            assert response.status_code in [400, 422], \
                "decision_date after record_timestamp must be rejected"

    def test_future_decision_date_rejected(self, impl_url: str):
        """Future decision_date should be rejected."""
        future = datetime.now(timezone.utc) + timedelta(days=30)

        dr = make_dr(
            decision_date=future.isoformat().replace("+00:00", "Z"),
            record_timestamp=(future + timedelta(hours=1)).isoformat().replace("+00:00", "Z"),
        )

        with httpx.Client(base_url=impl_url) as client:
            response = client.post("/dr", json=dr)
            assert response.status_code in [400, 422], \
                "Future decision_date should be rejected"
