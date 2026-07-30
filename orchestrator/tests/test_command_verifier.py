"""Tests for orchestrator.command_verifier -- post-execution state verification."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from orchestrator.command_verifier import (
    VERIFICATION_CHECKS,
    CommandVerifier,
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
    SimState,
    SurfaceState,
    TelemetryClient,
)

# ---------------------------------------------------------------------------
# Individual check functions
# ---------------------------------------------------------------------------


class TestCheckGearDown:
    def test_verified_when_gear_handle_true(self) -> None:
        before = SimState(surfaces=SurfaceState(gear_handle=False))
        after = SimState(surfaces=SurfaceState(gear_handle=True))
        result = _check_gear_down(before, after, 0)
        assert result.verified is True
        assert "confirmed" in result.message.lower()

    def test_not_verified_when_gear_still_up(self) -> None:
        before = SimState(surfaces=SurfaceState(gear_handle=False))
        after = SimState(surfaces=SurfaceState(gear_handle=False))
        result = _check_gear_down(before, after, 0)
        assert result.verified is False
        assert "failed" in result.message.lower()


class TestCheckGearUp:
    def test_verified_when_gear_handle_false(self) -> None:
        before = SimState(surfaces=SurfaceState(gear_handle=True))
        after = SimState(surfaces=SurfaceState(gear_handle=False))
        result = _check_gear_up(before, after, 0)
        assert result.verified is True

    def test_not_verified_when_gear_still_down(self) -> None:
        before = SimState(surfaces=SurfaceState(gear_handle=True))
        after = SimState(surfaces=SurfaceState(gear_handle=True))
        result = _check_gear_up(before, after, 0)
        assert result.verified is False


class TestCheckFlapsSet:
    def test_verified_within_tolerance(self) -> None:
        before = SimState(surfaces=SurfaceState(flaps_percent=0))
        after = SimState(surfaces=SurfaceState(flaps_percent=48))
        result = _check_flaps_set(before, after, 8191)
        assert result.verified is True

    def test_exact_match(self) -> None:
        before = SimState(surfaces=SurfaceState(flaps_percent=0))
        after = SimState(surfaces=SurfaceState(flaps_percent=100))
        result = _check_flaps_set(before, after, 16383)
        assert result.verified is True

    def test_not_verified_outside_tolerance(self) -> None:
        before = SimState(surfaces=SurfaceState(flaps_percent=0))
        after = SimState(surfaces=SurfaceState(flaps_percent=20))
        result = _check_flaps_set(before, after, 8191)
        assert result.verified is False

    def test_zero_flaps(self) -> None:
        before = SimState(surfaces=SurfaceState(flaps_percent=50))
        after = SimState(surfaces=SurfaceState(flaps_percent=0))
        result = _check_flaps_set(before, after, 0)
        assert result.verified is True


class TestCheckAPMaster:
    def test_verified_when_toggled_on(self) -> None:
        before = SimState(autopilot=AutopilotState(master=False))
        after = SimState(autopilot=AutopilotState(master=True))
        result = _check_ap_master(before, after, 0)
        assert result.verified is True
        assert "ON" in result.message

    def test_verified_when_toggled_off(self) -> None:
        before = SimState(autopilot=AutopilotState(master=True))
        after = SimState(autopilot=AutopilotState(master=False))
        result = _check_ap_master(before, after, 0)
        assert result.verified is True
        assert "OFF" in result.message

    def test_not_verified_when_unchanged(self) -> None:
        before = SimState(autopilot=AutopilotState(master=True))
        after = SimState(autopilot=AutopilotState(master=True))
        result = _check_ap_master(before, after, 0)
        assert result.verified is False
        assert "did not toggle" in result.message


class TestCheckHeadingBug:
    def test_verified_exact_match(self) -> None:
        before = SimState()
        after = SimState(autopilot=AutopilotState(heading=270))
        result = _check_heading_bug(before, after, 270)
        assert result.verified is True

    def test_verified_within_tolerance(self) -> None:
        before = SimState()
        after = SimState(autopilot=AutopilotState(heading=271))
        result = _check_heading_bug(before, after, 270)
        assert result.verified is True

    def test_not_verified_outside_tolerance(self) -> None:
        before = SimState()
        after = SimState(autopilot=AutopilotState(heading=275))
        result = _check_heading_bug(before, after, 270)
        assert result.verified is False

    def test_wraparound_360_to_0(self) -> None:
        before = SimState()
        after = SimState(autopilot=AutopilotState(heading=359))
        result = _check_heading_bug(before, after, 360)
        assert result.verified is True


class TestCheckAltSet:
    def test_verified_exact(self) -> None:
        before = SimState()
        after = SimState(autopilot=AutopilotState(altitude=5000))
        result = _check_alt_set(before, after, 5000)
        assert result.verified is True

    def test_verified_within_tolerance(self) -> None:
        before = SimState()
        after = SimState(autopilot=AutopilotState(altitude=5040))
        result = _check_alt_set(before, after, 5000)
        assert result.verified is True

    def test_not_verified_outside_tolerance(self) -> None:
        before = SimState()
        after = SimState(autopilot=AutopilotState(altitude=5100))
        result = _check_alt_set(before, after, 5000)
        assert result.verified is False


class TestCheckThrottle:
    def test_verified_rpm_increased_for_high_throttle(self) -> None:
        before = SimState(engines=Engines(engine_count=1, engines=[EngineData(rpm=1800)]))
        after = SimState(engines=Engines(engine_count=1, engines=[EngineData(rpm=2400)]))
        result = _check_throttle(before, after, 16383)
        assert result.verified is True

    def test_verified_rpm_decreased_for_low_throttle(self) -> None:
        before = SimState(engines=Engines(engine_count=1, engines=[EngineData(rpm=2400)]))
        after = SimState(engines=Engines(engine_count=1, engines=[EngineData(rpm=1200)]))
        result = _check_throttle(before, after, 2000)
        assert result.verified is True

    def test_not_verified_no_engines(self) -> None:
        before = SimState(engines=Engines(engine_count=0, engines=[]))
        after = SimState(engines=Engines(engine_count=0, engines=[]))
        result = _check_throttle(before, after, 16383)
        assert result.verified is False
        assert "no active engines" in result.actual

    def test_not_verified_wrong_direction(self) -> None:
        before = SimState(engines=Engines(engine_count=1, engines=[EngineData(rpm=2400)]))
        after = SimState(engines=Engines(engine_count=1, engines=[EngineData(rpm=1200)]))
        result = _check_throttle(before, after, 16383)
        assert result.verified is False


# ---------------------------------------------------------------------------
# CommandVerifier integration
# ---------------------------------------------------------------------------


class TestCommandVerifier:
    @pytest.mark.asyncio
    async def test_verify_gear_down_success(self) -> None:
        mock_client = MagicMock(spec=TelemetryClient)
        after_state = SimState(surfaces=SurfaceState(gear_handle=True))
        mock_client.get_state = AsyncMock(return_value=after_state)
        verifier = CommandVerifier(mock_client, timeout=1.0, poll_interval=0.1)
        before_state = SimState(surfaces=SurfaceState(gear_handle=False))
        result = await verifier.verify_command("GEAR_DOWN", 0, before_state)
        assert result.verified is True
        assert result.command == "GEAR_DOWN"

    @pytest.mark.asyncio
    async def test_verify_gear_down_timeout(self) -> None:
        mock_client = MagicMock(spec=TelemetryClient)
        after_state = SimState(surfaces=SurfaceState(gear_handle=False))
        mock_client.get_state = AsyncMock(return_value=after_state)
        verifier = CommandVerifier(mock_client, timeout=0.3, poll_interval=0.1)
        before_state = SimState(surfaces=SurfaceState(gear_handle=False))
        result = await verifier.verify_command("GEAR_DOWN", 0, before_state)
        assert result.verified is False
        assert "timed out" in result.message

    @pytest.mark.asyncio
    async def test_no_verification_rule_returns_verified(self) -> None:
        mock_client = MagicMock(spec=TelemetryClient)
        verifier = CommandVerifier(mock_client, timeout=1.0, poll_interval=0.1)
        result = await verifier.verify_command("TOGGLE_NAV_LIGHTS", 0, SimState())
        assert result.verified is True
        assert "no verification rule" in result.expected.lower()
        mock_client.get_state.assert_not_called()

    @pytest.mark.asyncio
    async def test_connection_error_during_poll(self) -> None:
        mock_client = MagicMock(spec=TelemetryClient)
        mock_client.get_state = AsyncMock(side_effect=ConnectionError("lost"))
        verifier = CommandVerifier(mock_client, timeout=0.3, poll_interval=0.1)
        before_state = SimState(surfaces=SurfaceState(gear_handle=False))
        result = await verifier.verify_command("GEAR_DOWN", 0, before_state)
        assert result.verified is False
        assert "no telemetry" in result.message.lower()

    @pytest.mark.asyncio
    async def test_eventual_success_after_polls(self) -> None:
        mock_client = MagicMock(spec=TelemetryClient)
        mock_client.get_state = AsyncMock(
            side_effect=[
                SimState(surfaces=SurfaceState(gear_handle=False)),
                SimState(surfaces=SurfaceState(gear_handle=True)),
            ]
        )
        verifier = CommandVerifier(mock_client, timeout=1.0, poll_interval=0.1)
        before_state = SimState(surfaces=SurfaceState(gear_handle=False))
        result = await verifier.verify_command("GEAR_DOWN", 0, before_state)
        assert result.verified is True
        assert mock_client.get_state.call_count == 2


class TestVerificationChecksRegistry:
    def test_all_expected_commands_registered(self) -> None:
        expected = {
            "GEAR_DOWN",
            "GEAR_UP",
            "FLAPS_SET",
            "AP_MASTER",
            "HEADING_BUG_SET",
            "AP_ALT_VAR_SET_ENGLISH",
            "THROTTLE_SET",
        }
        assert expected == set(VERIFICATION_CHECKS.keys())
