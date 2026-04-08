"""Tests for orchestrator.command_verifier — post-execution state verification."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest
from orchestrator.command_verifier import (
    CommandVerifier,
    VerificationResult,
    VERIFICATION_CHECKS,
    _check_alt_set,
    _check_ap_master,
    _check_flaps_set,
    _check_gear_down,
    _check_gear_up,
    _check_heading_bug,
    _check_throttle,
)
from orchestrator.sim_client import (
    AutopilotState,
    EngineData,
    Engines,
    Position,
    SimState,
    SurfaceState,
    TelemetryClient,
)


# ---------------------------------------------------------------------------
# VerificationResult dataclass
# ---------------------------------------------------------------------------


class TestVerificationResult:
    """VerificationResult has all required fields."""

    def test_all_fields_present(self) -> None:
        r = VerificationResult(
            verified=True,
            command="GEAR_DOWN",
            expected="gear_handle=True",
            actual="gear_handle=True",
            message="Gear down confirmed.",
        )
        assert r.verified is True
        assert r.command == "GEAR_DOWN"
        assert r.expected == "gear_handle=True"
        assert r.actual == "gear_handle=True"
        assert r.message == "Gear down confirmed."

    def test_unverified_result(self) -> None:
        r = VerificationResult(
            verified=False,
            command="GEAR_UP",
            expected="gear_handle=False",
            actual="gear_handle=True",
            message="Gear failed to retract.",
        )
        assert r.verified is False
        assert "failed" in r.message.lower()


# ---------------------------------------------------------------------------
# _check_gear_down
# ---------------------------------------------------------------------------


class TestCheckGearDown:
    def test_gear_down_verified(self) -> None:
        before = SimState(surfaces=SurfaceState(gear_handle=False))
        after = SimState(surfaces=SurfaceState(gear_handle=True))
        result = _check_gear_down(before, after, 0)
        assert result.verified is True
        assert result.command == "GEAR_DOWN"
        assert "confirmed" in result.message.lower()

    def test_gear_down_failed(self) -> None:
        before = SimState(surfaces=SurfaceState(gear_handle=False))
        after = SimState(surfaces=SurfaceState(gear_handle=False))
        result = _check_gear_down(before, after, 0)
        assert result.verified is False
        assert "failed" in result.message.lower()


# ---------------------------------------------------------------------------
# _check_gear_up
# ---------------------------------------------------------------------------


class TestCheckGearUp:
    def test_gear_up_verified(self) -> None:
        before = SimState(surfaces=SurfaceState(gear_handle=True))
        after = SimState(surfaces=SurfaceState(gear_handle=False))
        result = _check_gear_up(before, after, 0)
        assert result.verified is True
        assert result.command == "GEAR_UP"

    def test_gear_up_failed(self) -> None:
        before = SimState(surfaces=SurfaceState(gear_handle=True))
        after = SimState(surfaces=SurfaceState(gear_handle=True))
        result = _check_gear_up(before, after, 0)
        assert result.verified is False
        assert "failed" in result.message.lower()


# ---------------------------------------------------------------------------
# _check_flaps_set
# ---------------------------------------------------------------------------


class TestCheckFlapsSet:
    def test_flaps_within_tolerance(self) -> None:
        """Target 50% (8192), actual 48% -- within 5% tolerance."""
        before = SimState(surfaces=SurfaceState(flaps_percent=0))
        after = SimState(surfaces=SurfaceState(flaps_percent=48))
        result = _check_flaps_set(before, after, 8192)
        assert result.verified is True

    def test_flaps_outside_tolerance(self) -> None:
        """Target 50% (8192), actual 30% -- outside 5% tolerance."""
        before = SimState(surfaces=SurfaceState(flaps_percent=0))
        after = SimState(surfaces=SurfaceState(flaps_percent=30))
        result = _check_flaps_set(before, after, 8192)
        assert result.verified is False

    def test_flaps_full_verified(self) -> None:
        """Target 100% (16383), actual 100% -- verified."""
        before = SimState(surfaces=SurfaceState(flaps_percent=0))
        after = SimState(surfaces=SurfaceState(flaps_percent=100))
        result = _check_flaps_set(before, after, 16383)
        assert result.verified is True

    def test_flaps_zero_verified(self) -> None:
        """Target 0% (0), actual 0% -- verified."""
        before = SimState(surfaces=SurfaceState(flaps_percent=50))
        after = SimState(surfaces=SurfaceState(flaps_percent=0))
        result = _check_flaps_set(before, after, 0)
        assert result.verified is True

    def test_flaps_exactly_at_tolerance_boundary(self) -> None:
        """Target 50%, actual 55% -- exactly at 5% boundary."""
        before = SimState(surfaces=SurfaceState(flaps_percent=0))
        after = SimState(surfaces=SurfaceState(flaps_percent=55))
        result = _check_flaps_set(before, after, 8192)
        assert result.verified is True


# ---------------------------------------------------------------------------
# _check_ap_master
# ---------------------------------------------------------------------------


class TestCheckApMaster:
    def test_ap_toggled_on(self) -> None:
        before = SimState(autopilot=AutopilotState(master=False))
        after = SimState(autopilot=AutopilotState(master=True))
        result = _check_ap_master(before, after, 0)
        assert result.verified is True
        assert "ON" in result.message

    def test_ap_toggled_off(self) -> None:
        before = SimState(autopilot=AutopilotState(master=True))
        after = SimState(autopilot=AutopilotState(master=False))
        result = _check_ap_master(before, after, 0)
        assert result.verified is True
        assert "OFF" in result.message

    def test_ap_not_toggled(self) -> None:
        before = SimState(autopilot=AutopilotState(master=True))
        after = SimState(autopilot=AutopilotState(master=True))
        result = _check_ap_master(before, after, 0)
        assert result.verified is False
        assert "did not toggle" in result.message.lower()


# ---------------------------------------------------------------------------
# _check_heading_bug
# ---------------------------------------------------------------------------


class TestCheckHeadingBug:
    def test_heading_within_tolerance(self) -> None:
        before = SimState(autopilot=AutopilotState(heading=0))
        after = SimState(autopilot=AutopilotState(heading=270))
        result = _check_heading_bug(before, after, 270)
        assert result.verified is True

    def test_heading_one_degree_off(self) -> None:
        """1 degree off is within the 1-degree tolerance."""
        before = SimState(autopilot=AutopilotState(heading=0))
        after = SimState(autopilot=AutopilotState(heading=271))
        result = _check_heading_bug(before, after, 270)
        assert result.verified is True

    def test_heading_outside_tolerance(self) -> None:
        before = SimState(autopilot=AutopilotState(heading=0))
        after = SimState(autopilot=AutopilotState(heading=275))
        result = _check_heading_bug(before, after, 270)
        assert result.verified is False

    def test_heading_wrap_around_360(self) -> None:
        """Heading 359 vs target 0 -- within tolerance via wraparound."""
        before = SimState(autopilot=AutopilotState(heading=0))
        after = SimState(autopilot=AutopilotState(heading=359))
        result = _check_heading_bug(before, after, 0)
        # abs(359 - 0) >= 359, so the wraparound check triggers
        assert result.verified is True


# ---------------------------------------------------------------------------
# _check_alt_set
# ---------------------------------------------------------------------------


class TestCheckAltSet:
    def test_altitude_within_tolerance(self) -> None:
        before = SimState(autopilot=AutopilotState(altitude=3000))
        after = SimState(autopilot=AutopilotState(altitude=5000))
        result = _check_alt_set(before, after, 5000)
        assert result.verified is True

    def test_altitude_50ft_off(self) -> None:
        """50 ft off is exactly at the tolerance boundary."""
        before = SimState(autopilot=AutopilotState(altitude=3000))
        after = SimState(autopilot=AutopilotState(altitude=5050))
        result = _check_alt_set(before, after, 5000)
        assert result.verified is True

    def test_altitude_outside_tolerance(self) -> None:
        before = SimState(autopilot=AutopilotState(altitude=3000))
        after = SimState(autopilot=AutopilotState(altitude=5100))
        result = _check_alt_set(before, after, 5000)
        assert result.verified is False


# ---------------------------------------------------------------------------
# CommandVerifier — unknown command
# ---------------------------------------------------------------------------


class TestCommandVerifierUnknownCommand:
    @pytest.mark.asyncio
    async def test_unknown_command_returns_verified_true(self) -> None:
        """Commands without a verification check should be assumed OK."""
        mock_client = MagicMock(spec=TelemetryClient)
        verifier = CommandVerifier(mock_client, timeout=1.0, poll_interval=0.1)
        before_state = SimState()

        result = await verifier.verify_command("SOME_UNKNOWN_CMD", 0, before_state)

        assert result.verified is True
        assert "no verification rule" in result.expected.lower()


# ---------------------------------------------------------------------------
# CommandVerifier — timeout handling
# ---------------------------------------------------------------------------


class TestCommandVerifierTimeout:
    @pytest.mark.asyncio
    async def test_timeout_returns_not_verified(self) -> None:
        """If state doesn't change within timeout, result is not verified."""
        mock_client = MagicMock(spec=TelemetryClient)
        # Return state that never has gear down
        mock_client.get_state = AsyncMock(
            return_value=SimState(surfaces=SurfaceState(gear_handle=False))
        )

        verifier = CommandVerifier(mock_client, timeout=0.3, poll_interval=0.1)
        before_state = SimState(surfaces=SurfaceState(gear_handle=False))

        result = await verifier.verify_command("GEAR_DOWN", 0, before_state)

        assert result.verified is False
        assert "timed out" in result.message.lower()

    @pytest.mark.asyncio
    async def test_timeout_no_telemetry_available(self) -> None:
        """If telemetry connection is lost during verification, not verified."""
        mock_client = MagicMock(spec=TelemetryClient)
        mock_client.get_state = AsyncMock(side_effect=ConnectionError("lost"))

        verifier = CommandVerifier(mock_client, timeout=0.3, poll_interval=0.1)
        before_state = SimState()

        result = await verifier.verify_command("GEAR_DOWN", 0, before_state)

        assert result.verified is False
        assert "no telemetry" in result.message.lower()


# ---------------------------------------------------------------------------
# CommandVerifier — successful verification
# ---------------------------------------------------------------------------


class TestCommandVerifierSuccess:
    @pytest.mark.asyncio
    async def test_gear_down_verified_after_poll(self) -> None:
        """Verify gear down succeeds when telemetry shows gear handle True."""
        mock_client = MagicMock(spec=TelemetryClient)
        mock_client.get_state = AsyncMock(
            return_value=SimState(surfaces=SurfaceState(gear_handle=True))
        )

        verifier = CommandVerifier(mock_client, timeout=1.0, poll_interval=0.1)
        before_state = SimState(surfaces=SurfaceState(gear_handle=False))

        result = await verifier.verify_command("GEAR_DOWN", 0, before_state)

        assert result.verified is True
        assert result.command == "GEAR_DOWN"

    @pytest.mark.asyncio
    async def test_ap_master_verified_after_toggle(self) -> None:
        mock_client = MagicMock(spec=TelemetryClient)
        mock_client.get_state = AsyncMock(
            return_value=SimState(autopilot=AutopilotState(master=True))
        )

        verifier = CommandVerifier(mock_client, timeout=1.0, poll_interval=0.1)
        before_state = SimState(autopilot=AutopilotState(master=False))

        result = await verifier.verify_command("AP_MASTER", 0, before_state)

        assert result.verified is True

    @pytest.mark.asyncio
    async def test_heading_bug_verified(self) -> None:
        mock_client = MagicMock(spec=TelemetryClient)
        mock_client.get_state = AsyncMock(
            return_value=SimState(autopilot=AutopilotState(heading=270))
        )

        verifier = CommandVerifier(mock_client, timeout=1.0, poll_interval=0.1)
        before_state = SimState(autopilot=AutopilotState(heading=0))

        result = await verifier.verify_command("HEADING_BUG_SET", 270, before_state)

        assert result.verified is True

    @pytest.mark.asyncio
    async def test_altitude_verified(self) -> None:
        mock_client = MagicMock(spec=TelemetryClient)
        mock_client.get_state = AsyncMock(
            return_value=SimState(autopilot=AutopilotState(altitude=10000))
        )

        verifier = CommandVerifier(mock_client, timeout=1.0, poll_interval=0.1)
        before_state = SimState(autopilot=AutopilotState(altitude=5000))

        result = await verifier.verify_command("AP_ALT_VAR_SET_ENGLISH", 10000, before_state)

        assert result.verified is True


# ---------------------------------------------------------------------------
# VERIFICATION_CHECKS registry
# ---------------------------------------------------------------------------


class TestVerificationChecksRegistry:
    def test_gear_down_registered(self) -> None:
        assert "GEAR_DOWN" in VERIFICATION_CHECKS

    def test_gear_up_registered(self) -> None:
        assert "GEAR_UP" in VERIFICATION_CHECKS

    def test_flaps_set_registered(self) -> None:
        assert "FLAPS_SET" in VERIFICATION_CHECKS

    def test_ap_master_registered(self) -> None:
        assert "AP_MASTER" in VERIFICATION_CHECKS

    def test_heading_bug_registered(self) -> None:
        assert "HEADING_BUG_SET" in VERIFICATION_CHECKS

    def test_alt_set_registered(self) -> None:
        assert "AP_ALT_VAR_SET_ENGLISH" in VERIFICATION_CHECKS

    def test_throttle_set_registered(self) -> None:
        assert "THROTTLE_SET" in VERIFICATION_CHECKS


# ---------------------------------------------------------------------------
# _check_throttle
# ---------------------------------------------------------------------------


class TestCheckThrottle:
    def test_rpm_increased_for_high_throttle(self) -> None:
        before = SimState(
            engines=Engines(engine_count=1, engines=[EngineData(rpm=1800)])
        )
        after = SimState(
            engines=Engines(engine_count=1, engines=[EngineData(rpm=2400)])
        )
        result = _check_throttle(before, after, 16383)  # full throttle
        assert result.verified is True

    def test_rpm_decreased_for_low_throttle(self) -> None:
        before = SimState(
            engines=Engines(engine_count=1, engines=[EngineData(rpm=2400)])
        )
        after = SimState(
            engines=Engines(engine_count=1, engines=[EngineData(rpm=1200)])
        )
        result = _check_throttle(before, after, 2000)  # low throttle
        assert result.verified is True

    def test_no_active_engines(self) -> None:
        before = SimState(engines=Engines(engine_count=0, engines=[]))
        after = SimState(engines=Engines(engine_count=0, engines=[]))
        result = _check_throttle(before, after, 16383)
        assert result.verified is False
        assert "no active engines" in result.actual

    def test_rpm_wrong_direction(self) -> None:
        """High throttle but RPM decreased significantly."""
        before = SimState(
            engines=Engines(engine_count=1, engines=[EngineData(rpm=2400)])
        )
        after = SimState(
            engines=Engines(engine_count=1, engines=[EngineData(rpm=1200)])
        )
        result = _check_throttle(before, after, 16383)  # full throttle, but RPM dropped
        assert result.verified is False
