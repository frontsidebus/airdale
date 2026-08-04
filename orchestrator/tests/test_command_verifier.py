"""Tests for orchestrator.command_verifier -- post-execution state verification."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from orchestrator.command_verifier import (
    NO_RULE_EXPECTED,
    VERIFICATION_CHECKS,
    CommandVerifier,
    _check_alt_set,
    _check_ap_master,
    _check_ap_speed,
    _check_ap_vertical_speed,
    _check_com1,
    _check_com2,
    _check_flaps_1,
    _check_flaps_full,
    _check_flaps_set,
    _check_flaps_up,
    _check_gear_down,
    _check_gear_toggle,
    _check_gear_up,
    _check_heading_bug,
    _check_kohlsman,
    _check_nav1,
    _check_nav2,
    _check_spoilers_set,
    _check_spoilers_toggle,
    _check_throttle,
    has_verification_rule,
)
from orchestrator.sim_client import (
    AutopilotState,
    EngineData,
    Engines,
    Environment,
    RadioState,
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
# Checks added so every observable command has a real rule (plan 02-06)
# ---------------------------------------------------------------------------


class TestCheckGearToggle:
    def test_verified_when_handle_flips(self) -> None:
        before = SimState(surfaces=SurfaceState(gear_handle=False))
        after = SimState(surfaces=SurfaceState(gear_handle=True))
        result = _check_gear_toggle(before, after, 0)
        assert result.verified is True
        assert "down" in result.message.lower()

    def test_not_verified_when_handle_unchanged(self) -> None:
        before = SimState(surfaces=SurfaceState(gear_handle=True))
        after = SimState(surfaces=SurfaceState(gear_handle=True))
        result = _check_gear_toggle(before, after, 0)
        assert result.verified is False
        assert "did not move" in result.message


class TestCheckFlapsDetents:
    def test_flaps_up_verified_when_retracting(self) -> None:
        before = SimState(surfaces=SurfaceState(flaps_percent=30))
        after = SimState(surfaces=SurfaceState(flaps_percent=0))
        result = _check_flaps_up(before, after, 0)
        assert result.verified is True
        assert result.command == "FLAPS_UP"

    def test_flaps_up_not_verified_when_still_extended(self) -> None:
        before = SimState(surfaces=SurfaceState(flaps_percent=30))
        after = SimState(surfaces=SurfaceState(flaps_percent=30))
        result = _check_flaps_up(before, after, 0)
        assert result.verified is False
        assert "retract" in result.message

    def test_flaps_1_verified_when_extending_from_clean(self) -> None:
        before = SimState(surfaces=SurfaceState(flaps_percent=0))
        after = SimState(surfaces=SurfaceState(flaps_percent=30))
        result = _check_flaps_1(before, after, 0)
        assert result.verified is True

    def test_flaps_1_not_verified_when_nothing_moved(self) -> None:
        before = SimState(surfaces=SurfaceState(flaps_percent=0))
        after = SimState(surfaces=SurfaceState(flaps_percent=0))
        result = _check_flaps_1(before, after, 0)
        assert result.verified is False
        assert "extend" in result.message

    def test_flaps_full_verified_when_extending(self) -> None:
        before = SimState(surfaces=SurfaceState(flaps_percent=0))
        after = SimState(surfaces=SurfaceState(flaps_percent=100))
        result = _check_flaps_full(before, after, 0)
        assert result.verified is True

    def test_flaps_full_not_verified_when_stuck(self) -> None:
        before = SimState(surfaces=SurfaceState(flaps_percent=0))
        after = SimState(surfaces=SurfaceState(flaps_percent=2))
        result = _check_flaps_full(before, after, 0)
        assert result.verified is False

    def test_reselecting_the_current_detent_verifies_without_movement(self) -> None:
        # Already at the commanded detent: no movement is the correct outcome.
        before = SimState(surfaces=SurfaceState(flaps_percent=25))
        after = SimState(surfaces=SurfaceState(flaps_percent=25))
        result = _check_flaps_1(before, after, 0)
        assert result.verified is True

    def test_unexpected_movement_at_the_current_detent_fails(self) -> None:
        before = SimState(surfaces=SurfaceState(flaps_percent=25))
        after = SimState(surfaces=SurfaceState(flaps_percent=80))
        result = _check_flaps_1(before, after, 0)
        assert result.verified is False
        assert "already at the commanded detent" in result.message


class TestCheckSpoilersSet:
    def test_verified_within_tolerance(self) -> None:
        before = SimState(surfaces=SurfaceState(spoilers_percent=0))
        after = SimState(surfaces=SurfaceState(spoilers_percent=48))
        result = _check_spoilers_set(before, after, 8191)
        assert result.verified is True

    def test_not_verified_outside_tolerance(self) -> None:
        before = SimState(surfaces=SurfaceState(spoilers_percent=0))
        after = SimState(surfaces=SurfaceState(spoilers_percent=20))
        result = _check_spoilers_set(before, after, 8191)
        assert result.verified is False


class TestCheckSpoilersToggle:
    def test_verified_on_deployment(self) -> None:
        before = SimState(surfaces=SurfaceState(spoilers_percent=0))
        after = SimState(surfaces=SurfaceState(spoilers_percent=100))
        result = _check_spoilers_toggle(before, after, 0)
        assert result.verified is True

    def test_verified_on_stow_too(self) -> None:
        # Direction-free: stowing is as much a successful toggle as deploying.
        before = SimState(surfaces=SurfaceState(spoilers_percent=100))
        after = SimState(surfaces=SurfaceState(spoilers_percent=0))
        result = _check_spoilers_toggle(before, after, 0)
        assert result.verified is True

    def test_not_verified_on_sub_tolerance_jitter(self) -> None:
        before = SimState(surfaces=SurfaceState(spoilers_percent=0))
        after = SimState(surfaces=SurfaceState(spoilers_percent=2))
        result = _check_spoilers_toggle(before, after, 0)
        assert result.verified is False


class TestCheckAPSpeed:
    def test_verified_within_tolerance(self) -> None:
        before = SimState()
        after = SimState(autopilot=AutopilotState(airspeed=121))
        result = _check_ap_speed(before, after, 120)
        assert result.verified is True

    def test_not_verified_outside_tolerance(self) -> None:
        before = SimState()
        after = SimState(autopilot=AutopilotState(airspeed=130))
        result = _check_ap_speed(before, after, 120)
        assert result.verified is False


class TestCheckAPVerticalSpeed:
    def test_verified_within_tolerance(self) -> None:
        before = SimState()
        after = SimState(autopilot=AutopilotState(vertical_speed=-520))
        result = _check_ap_vertical_speed(before, after, -500)
        assert result.verified is True

    def test_not_verified_outside_tolerance(self) -> None:
        before = SimState()
        after = SimState(autopilot=AutopilotState(vertical_speed=-200))
        result = _check_ap_vertical_speed(before, after, -500)
        assert result.verified is False


class TestCheckKohlsman:
    def test_verified_within_tolerance(self) -> None:
        # Command value is inHg x 100 (tools.py:135).
        before = SimState()
        after = SimState(environment=Environment(barometer_inhg=29.93))
        result = _check_kohlsman(before, after, 2992)
        assert result.verified is True

    def test_not_verified_outside_tolerance(self) -> None:
        before = SimState()
        after = SimState(environment=Environment(barometer_inhg=30.10))
        result = _check_kohlsman(before, after, 2992)
        assert result.verified is False


class TestCheckRadios:
    def test_com1_verified(self) -> None:
        # Command value is Hz (tools.py:125); telemetry reports MHz.
        before = SimState()
        after = SimState(radios=RadioState(com1=121.9))
        result = _check_com1(before, after, 121_900_000)
        assert result.verified is True
        assert result.command == "COM_RADIO_SET_HZ"

    def test_com1_not_verified_when_unchanged(self) -> None:
        before = SimState()
        after = SimState(radios=RadioState(com1=118.0))
        result = _check_com1(before, after, 121_900_000)
        assert result.verified is False

    def test_com2_verified(self) -> None:
        before = SimState()
        after = SimState(radios=RadioState(com2=118.5))
        result = _check_com2(before, after, 118_500_000)
        assert result.verified is True

    def test_nav1_verified(self) -> None:
        before = SimState()
        after = SimState(radios=RadioState(nav1=110.5))
        result = _check_nav1(before, after, 110_500_000)
        assert result.verified is True

    def test_nav2_not_verified_when_wrong_frequency(self) -> None:
        before = SimState()
        after = SimState(radios=RadioState(nav2=110.5))
        result = _check_nav2(before, after, 112_300_000)
        assert result.verified is False


class TestHasVerificationRule:
    def test_true_for_a_newly_registered_command(self) -> None:
        assert has_verification_rule("SPOILERS_SET") is True
        assert has_verification_rule("KOHLSMAN_SET") is True

    def test_true_for_a_pre_existing_command(self) -> None:
        assert has_verification_rule("GEAR_DOWN") is True

    def test_false_for_a_command_with_no_rule(self) -> None:
        # MIXTURE_SET moves no observable SimState field, so it stays rule-less.
        assert has_verification_rule("MIXTURE_SET") is False


class TestEveryCheckResolvesAgainstDefaultState:
    def test_no_registered_check_raises_on_a_default_sim_state(self) -> None:
        """Every dotted SimState path a check reads must exist on a bare SimState()."""
        for command, check in VERIFICATION_CHECKS.items():
            result = check(SimState(), SimState(), 0)
            assert result.command, f"{command} returned an unnamed result"


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
    async def test_rule_less_command_short_circuits_before_any_poll(self) -> None:
        """MIXTURE_SET moves no observable field, so the early return must still fire."""
        mock_client = MagicMock(spec=TelemetryClient)
        verifier = CommandVerifier(mock_client, timeout=1.0, poll_interval=0.1)
        result = await verifier.verify_command("MIXTURE_SET", 8000, SimState())
        assert result.verified is True
        assert result.expected == NO_RULE_EXPECTED
        mock_client.get_state.assert_not_called()

    @pytest.mark.asyncio
    async def test_registered_command_does_poll(self) -> None:
        """A command that gained a rule must no longer take the rule-less path."""
        mock_client = MagicMock(spec=TelemetryClient)
        mock_client.get_state = AsyncMock(
            return_value=SimState(surfaces=SurfaceState(spoilers_percent=100))
        )
        verifier = CommandVerifier(mock_client, timeout=1.0, poll_interval=0.1)
        result = await verifier.verify_command("SPOILERS_SET", 16383, SimState())
        assert result.verified is True
        assert result.expected != NO_RULE_EXPECTED
        mock_client.get_state.assert_called()

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
            "GEAR_TOGGLE",
            "FLAPS_SET",
            "FLAPS_UP",
            "FLAPS_1",
            "FLAPS_2",
            "FLAPS_3",
            "FLAPS_FULL",
            "SPOILERS_SET",
            "SPOILERS_TOGGLE",
            "AP_MASTER",
            "HEADING_BUG_SET",
            "AP_ALT_VAR_SET_ENGLISH",
            "AP_VS_VAR_SET_ENGLISH",
            "AP_SPD_VAR_SET",
            "KOHLSMAN_SET",
            "COM_RADIO_SET_HZ",
            "COM2_RADIO_SET_HZ",
            "NAV1_RADIO_SET_HZ",
            "NAV2_RADIO_SET_HZ",
            "THROTTLE_SET",
        }
        assert expected == set(VERIFICATION_CHECKS.keys())

    def test_every_observable_command_has_a_rule(self) -> None:
        """The set RESEARCH F2 named as verifiable-but-unverified is now covered."""
        for command in (
            "SPOILERS_SET",
            "AP_SPD_VAR_SET",
            "AP_VS_VAR_SET_ENGLISH",
            "KOHLSMAN_SET",
            "FLAPS_1",
            "FLAPS_2",
            "FLAPS_3",
            "COM_RADIO_SET_HZ",
            "NAV1_RADIO_SET_HZ",
        ):
            assert has_verification_rule(command), f"{command} still has no rule"
