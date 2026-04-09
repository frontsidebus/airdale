"""Tests for the DeviationMonitor and default deviation rules."""

from __future__ import annotations

import pytest

from orchestrator.deviation_monitor import (
    DeviationAlert,
    DeviationMonitor,
    DeviationRule,
)
from orchestrator.sim_client import (
    Attitude,
    AutopilotState,
    FlightPhase,
    Position,
    SimState,
    Speeds,
    SurfaceState,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_state(
    *,
    flight_phase: FlightPhase = FlightPhase.CRUISE,
    ias: float = 120.0,
    altitude_msl: float = 5000.0,
    altitude_agl: float = 4500.0,
    vertical_speed: float = 0.0,
    pitch: float = 0.0,
    bank: float = 0.0,
    gear_handle: bool = False,
    flaps_percent: float = 0.0,
    ap_master: bool = False,
    ap_altitude: float = 5000.0,
) -> SimState:
    """Build a SimState with sensible defaults and easy overrides."""
    return SimState(
        connected=True,
        flight_phase=flight_phase,
        position=Position(altitude_msl=altitude_msl, altitude_agl=altitude_agl),
        attitude=Attitude(pitch=pitch, bank=bank),
        speeds=Speeds(indicated_airspeed=ias, vertical_speed=vertical_speed),
        surfaces=SurfaceState(gear_handle=gear_handle, flaps_percent=flaps_percent),
        autopilot=AutopilotState(master=ap_master, altitude=ap_altitude),
    )


# ---------------------------------------------------------------------------
# Speed deviation rules
# ---------------------------------------------------------------------------


class TestSpeedHighApproach:
    def test_fires_when_fast_on_approach(self) -> None:
        monitor = DeviationMonitor()
        state = _make_state(flight_phase=FlightPhase.APPROACH, ias=170.0)
        alerts = monitor.check(state)
        names = [a.name for a in alerts]
        assert "speed_high_approach" in names

    def test_no_alert_at_normal_speed(self) -> None:
        monitor = DeviationMonitor()
        state = _make_state(flight_phase=FlightPhase.APPROACH, ias=130.0)
        alerts = monitor.check(state)
        names = [a.name for a in alerts]
        assert "speed_high_approach" not in names

    def test_not_checked_during_cruise(self) -> None:
        monitor = DeviationMonitor()
        state = _make_state(flight_phase=FlightPhase.CRUISE, ias=200.0)
        alerts = monitor.check(state)
        names = [a.name for a in alerts]
        assert "speed_high_approach" not in names


class TestSpeedLowApproach:
    def test_fires_when_slow(self) -> None:
        monitor = DeviationMonitor()
        state = _make_state(flight_phase=FlightPhase.APPROACH, ias=50.0)
        alerts = monitor.check(state)
        names = [a.name for a in alerts]
        assert "speed_low_approach" in names

    def test_no_alert_at_normal_speed(self) -> None:
        monitor = DeviationMonitor()
        state = _make_state(flight_phase=FlightPhase.APPROACH, ias=80.0)
        alerts = monitor.check(state)
        names = [a.name for a in alerts]
        assert "speed_low_approach" not in names


class TestOverspeedBelow10k:
    def test_fires_when_fast_and_low(self) -> None:
        monitor = DeviationMonitor()
        state = _make_state(flight_phase=FlightPhase.DESCENT, ias=270.0, altitude_msl=8000.0)
        alerts = monitor.check(state)
        names = [a.name for a in alerts]
        assert "overspeed_below_10k" in names

    def test_no_alert_above_10k(self) -> None:
        monitor = DeviationMonitor()
        state = _make_state(flight_phase=FlightPhase.CRUISE, ias=300.0, altitude_msl=15000.0)
        alerts = monitor.check(state)
        names = [a.name for a in alerts]
        assert "overspeed_below_10k" not in names

    def test_no_alert_at_normal_speed(self) -> None:
        monitor = DeviationMonitor()
        state = _make_state(flight_phase=FlightPhase.CLIMB, ias=200.0, altitude_msl=5000.0)
        alerts = monitor.check(state)
        names = [a.name for a in alerts]
        assert "overspeed_below_10k" not in names


class TestStallWarning:
    def test_fires_when_slow_airborne(self) -> None:
        monitor = DeviationMonitor()
        state = _make_state(flight_phase=FlightPhase.APPROACH, ias=45.0, altitude_agl=500.0)
        alerts = monitor.check(state)
        names = [a.name for a in alerts]
        assert "stall_warning" in names
        alert = next(a for a in alerts if a.name == "stall_warning")
        assert alert.severity == "warning"

    def test_no_alert_on_ground(self) -> None:
        monitor = DeviationMonitor()
        # on_ground is True when altitude_agl < 10
        state = _make_state(flight_phase=FlightPhase.TAKEOFF, ias=30.0, altitude_agl=5.0)
        alerts = monitor.check(state)
        names = [a.name for a in alerts]
        assert "stall_warning" not in names

    def test_no_alert_at_normal_speed(self) -> None:
        monitor = DeviationMonitor()
        state = _make_state(flight_phase=FlightPhase.CRUISE, ias=120.0)
        alerts = monitor.check(state)
        names = [a.name for a in alerts]
        assert "stall_warning" not in names


# ---------------------------------------------------------------------------
# Altitude deviation rules
# ---------------------------------------------------------------------------


class TestAltitudeBust:
    def test_fires_when_deviating_with_ap(self) -> None:
        monitor = DeviationMonitor()
        state = _make_state(
            flight_phase=FlightPhase.CRUISE,
            altitude_msl=5500.0,
            ap_master=True,
            ap_altitude=5000.0,
        )
        alerts = monitor.check(state)
        names = [a.name for a in alerts]
        assert "altitude_bust" in names
        alert = next(a for a in alerts if a.name == "altitude_bust")
        assert alert.deviation == pytest.approx(500.0)

    def test_no_alert_without_ap(self) -> None:
        monitor = DeviationMonitor()
        state = _make_state(
            flight_phase=FlightPhase.CRUISE,
            altitude_msl=5500.0,
            ap_master=False,
            ap_altitude=5000.0,
        )
        alerts = monitor.check(state)
        names = [a.name for a in alerts]
        assert "altitude_bust" not in names

    def test_no_alert_within_tolerance(self) -> None:
        monitor = DeviationMonitor()
        state = _make_state(
            flight_phase=FlightPhase.CRUISE,
            altitude_msl=5100.0,
            ap_master=True,
            ap_altitude=5000.0,
        )
        alerts = monitor.check(state)
        names = [a.name for a in alerts]
        assert "altitude_bust" not in names

    def test_not_checked_on_approach(self) -> None:
        monitor = DeviationMonitor()
        state = _make_state(
            flight_phase=FlightPhase.APPROACH,
            altitude_msl=3500.0,
            ap_master=True,
            ap_altitude=3000.0,
        )
        alerts = monitor.check(state)
        names = [a.name for a in alerts]
        assert "altitude_bust" not in names


class TestTooLowTerrain:
    def test_fires_during_cruise(self) -> None:
        monitor = DeviationMonitor()
        state = _make_state(
            flight_phase=FlightPhase.CRUISE, altitude_agl=300.0, altitude_msl=3000.0
        )
        alerts = monitor.check(state)
        names = [a.name for a in alerts]
        assert "too_low_terrain" in names

    def test_fires_during_climb(self) -> None:
        monitor = DeviationMonitor()
        state = _make_state(flight_phase=FlightPhase.CLIMB, altitude_agl=400.0, altitude_msl=2000.0)
        alerts = monitor.check(state)
        names = [a.name for a in alerts]
        assert "too_low_terrain" in names

    def test_no_alert_high_enough(self) -> None:
        monitor = DeviationMonitor()
        state = _make_state(
            flight_phase=FlightPhase.CRUISE, altitude_agl=2000.0, altitude_msl=5000.0
        )
        alerts = monitor.check(state)
        names = [a.name for a in alerts]
        assert "too_low_terrain" not in names

    def test_not_checked_on_approach(self) -> None:
        monitor = DeviationMonitor()
        state = _make_state(
            flight_phase=FlightPhase.APPROACH, altitude_agl=300.0, altitude_msl=1000.0
        )
        alerts = monitor.check(state)
        names = [a.name for a in alerts]
        assert "too_low_terrain" not in names


# ---------------------------------------------------------------------------
# Configuration deviation rules
# ---------------------------------------------------------------------------


class TestGearNotDownLow:
    def test_fires_when_gear_up_low_on_approach(self) -> None:
        monitor = DeviationMonitor()
        state = _make_state(
            flight_phase=FlightPhase.APPROACH,
            altitude_agl=400.0,
            gear_handle=False,
        )
        alerts = monitor.check(state)
        names = [a.name for a in alerts]
        assert "gear_not_down_low" in names

    def test_no_alert_when_gear_down(self) -> None:
        monitor = DeviationMonitor()
        state = _make_state(
            flight_phase=FlightPhase.APPROACH,
            altitude_agl=400.0,
            gear_handle=True,
        )
        alerts = monitor.check(state)
        names = [a.name for a in alerts]
        assert "gear_not_down_low" not in names

    def test_no_alert_when_high(self) -> None:
        monitor = DeviationMonitor()
        state = _make_state(
            flight_phase=FlightPhase.APPROACH,
            altitude_agl=600.0,
            gear_handle=False,
        )
        alerts = monitor.check(state)
        names = [a.name for a in alerts]
        assert "gear_not_down_low" not in names


class TestFlapsNotSetApproach:
    def test_fires_when_no_flaps_low(self) -> None:
        monitor = DeviationMonitor()
        state = _make_state(
            flight_phase=FlightPhase.APPROACH,
            altitude_agl=800.0,
            flaps_percent=0.0,
        )
        alerts = monitor.check(state)
        names = [a.name for a in alerts]
        assert "flaps_not_set_approach" in names

    def test_no_alert_with_flaps(self) -> None:
        monitor = DeviationMonitor()
        state = _make_state(
            flight_phase=FlightPhase.APPROACH,
            altitude_agl=800.0,
            flaps_percent=20.0,
        )
        alerts = monitor.check(state)
        names = [a.name for a in alerts]
        assert "flaps_not_set_approach" not in names

    def test_no_alert_when_high(self) -> None:
        monitor = DeviationMonitor()
        state = _make_state(
            flight_phase=FlightPhase.APPROACH,
            altitude_agl=1500.0,
            flaps_percent=0.0,
        )
        alerts = monitor.check(state)
        names = [a.name for a in alerts]
        assert "flaps_not_set_approach" not in names


class TestNoApHighWorkload:
    def test_fires_when_no_ap_low_on_approach(self) -> None:
        monitor = DeviationMonitor()
        state = _make_state(
            flight_phase=FlightPhase.APPROACH,
            altitude_agl=800.0,
            ap_master=False,
        )
        alerts = monitor.check(state)
        names = [a.name for a in alerts]
        assert "no_ap_high_workload" in names

    def test_no_alert_with_ap(self) -> None:
        monitor = DeviationMonitor()
        state = _make_state(
            flight_phase=FlightPhase.APPROACH,
            altitude_agl=800.0,
            ap_master=True,
        )
        alerts = monitor.check(state)
        names = [a.name for a in alerts]
        assert "no_ap_high_workload" not in names

    def test_no_alert_when_high(self) -> None:
        monitor = DeviationMonitor()
        state = _make_state(
            flight_phase=FlightPhase.APPROACH,
            altitude_agl=1500.0,
            ap_master=False,
        )
        alerts = monitor.check(state)
        names = [a.name for a in alerts]
        assert "no_ap_high_workload" not in names


# ---------------------------------------------------------------------------
# Attitude deviation rules
# ---------------------------------------------------------------------------


class TestExcessiveBank:
    def test_fires_on_approach(self) -> None:
        monitor = DeviationMonitor()
        state = _make_state(flight_phase=FlightPhase.APPROACH, bank=35.0)
        alerts = monitor.check(state)
        names = [a.name for a in alerts]
        assert "excessive_bank" in names

    def test_fires_on_landing(self) -> None:
        monitor = DeviationMonitor()
        state = _make_state(flight_phase=FlightPhase.LANDING, bank=-35.0)
        alerts = monitor.check(state)
        names = [a.name for a in alerts]
        assert "excessive_bank" in names

    def test_no_alert_normal_bank(self) -> None:
        monitor = DeviationMonitor()
        state = _make_state(flight_phase=FlightPhase.APPROACH, bank=20.0)
        alerts = monitor.check(state)
        names = [a.name for a in alerts]
        assert "excessive_bank" not in names

    def test_not_checked_during_cruise(self) -> None:
        monitor = DeviationMonitor()
        state = _make_state(flight_phase=FlightPhase.CRUISE, bank=40.0)
        alerts = monitor.check(state)
        names = [a.name for a in alerts]
        assert "excessive_bank" not in names


class TestExcessivePitchUp:
    def test_fires_during_cruise(self) -> None:
        monitor = DeviationMonitor()
        state = _make_state(flight_phase=FlightPhase.CRUISE, pitch=20.0)
        alerts = monitor.check(state)
        names = [a.name for a in alerts]
        assert "excessive_pitch_up" in names

    def test_not_checked_during_takeoff(self) -> None:
        monitor = DeviationMonitor()
        state = _make_state(flight_phase=FlightPhase.TAKEOFF, pitch=20.0)
        alerts = monitor.check(state)
        names = [a.name for a in alerts]
        assert "excessive_pitch_up" not in names

    def test_no_alert_normal_pitch(self) -> None:
        monitor = DeviationMonitor()
        state = _make_state(flight_phase=FlightPhase.CRUISE, pitch=5.0)
        alerts = monitor.check(state)
        names = [a.name for a in alerts]
        assert "excessive_pitch_up" not in names


class TestExcessivePitchDown:
    def test_fires_on_any_phase(self) -> None:
        monitor = DeviationMonitor()
        for phase in FlightPhase:
            monitor.reset()
            state = _make_state(flight_phase=phase, pitch=-15.0)
            alerts = monitor.check(state)
            names = [a.name for a in alerts]
            assert "excessive_pitch_down" in names, f"Expected alert in {phase}"

    def test_no_alert_normal_pitch(self) -> None:
        monitor = DeviationMonitor()
        state = _make_state(flight_phase=FlightPhase.CRUISE, pitch=-5.0)
        alerts = monitor.check(state)
        names = [a.name for a in alerts]
        assert "excessive_pitch_down" not in names


# ---------------------------------------------------------------------------
# Cooldown behavior
# ---------------------------------------------------------------------------


class TestCooldown:
    def test_second_alert_suppressed_within_cooldown(self) -> None:
        fake_time = 100.0

        def time_fn() -> float:
            return fake_time

        monitor = DeviationMonitor(time_fn=time_fn)
        state = _make_state(flight_phase=FlightPhase.CRUISE, pitch=20.0)

        # First check fires
        alerts1 = monitor.check(state)
        assert any(a.name == "excessive_pitch_up" for a in alerts1)

        # Advance 10 seconds (within 30s cooldown)
        fake_time = 110.0
        alerts2 = monitor.check(state)
        assert not any(a.name == "excessive_pitch_up" for a in alerts2)

    def test_alert_fires_again_after_cooldown(self) -> None:
        fake_time = 100.0

        def time_fn() -> float:
            return fake_time

        monitor = DeviationMonitor(time_fn=time_fn)
        state = _make_state(flight_phase=FlightPhase.CRUISE, pitch=20.0)

        alerts1 = monitor.check(state)
        assert any(a.name == "excessive_pitch_up" for a in alerts1)

        # Advance past the 30s cooldown
        fake_time = 131.0
        alerts2 = monitor.check(state)
        assert any(a.name == "excessive_pitch_up" for a in alerts2)

    def test_custom_cooldown(self) -> None:
        fake_time = 100.0

        def time_fn() -> float:
            return fake_time

        def always_alert(state: SimState) -> DeviationAlert | None:
            return DeviationAlert(
                name="test_rule",
                message="test",
                severity="caution",
                value=0.0,
                expected=0.0,
                deviation=0.0,
            )

        rule = DeviationRule(
            name="test_rule",
            check=always_alert,
            phases=set(FlightPhase),
            cooldown_secs=5.0,
        )
        monitor = DeviationMonitor(rules=[rule], time_fn=time_fn)
        state = _make_state()

        assert len(monitor.check(state)) == 1

        fake_time = 104.0
        assert len(monitor.check(state)) == 0

        fake_time = 106.0
        assert len(monitor.check(state)) == 1

    def test_reset_clears_cooldowns(self) -> None:
        fake_time = 100.0

        def time_fn() -> float:
            return fake_time

        monitor = DeviationMonitor(time_fn=time_fn)
        state = _make_state(flight_phase=FlightPhase.CRUISE, pitch=20.0)

        monitor.check(state)

        fake_time = 105.0
        # Normally suppressed
        assert not any(a.name == "excessive_pitch_up" for a in monitor.check(state))

        monitor.reset()
        # Now fires again
        assert any(a.name == "excessive_pitch_up" for a in monitor.check(state))


# ---------------------------------------------------------------------------
# Phase filtering
# ---------------------------------------------------------------------------


class TestPhaseFiltering:
    def test_rules_only_fire_in_matching_phases(self) -> None:
        """Verify each default rule respects its phase set."""
        monitor = DeviationMonitor()

        # A state that would trigger many rules
        trigger_state = _make_state(
            ias=45.0,
            altitude_msl=300.0,
            altitude_agl=300.0,
            pitch=-15.0,
            bank=40.0,
            gear_handle=False,
            flaps_percent=0.0,
            ap_master=False,
        )

        for phase in FlightPhase:
            monitor.reset()
            trigger_state.flight_phase = phase
            alerts = monitor.check(trigger_state)
            for alert in alerts:
                # Find the matching rule
                matching_rules = [r for r in monitor._rules if r.name == alert.name]
                assert len(matching_rules) == 1
                rule = matching_rules[0]
                assert phase in rule.phases, (
                    f"Rule '{alert.name}' fired in phase {phase} but its phases are {rule.phases}"
                )


# ---------------------------------------------------------------------------
# Alert data integrity
# ---------------------------------------------------------------------------


class TestAlertData:
    def test_speed_high_approach_alert_values(self) -> None:
        monitor = DeviationMonitor()
        state = _make_state(flight_phase=FlightPhase.APPROACH, ias=180.0)
        alerts = monitor.check(state)
        alert = next(a for a in alerts if a.name == "speed_high_approach")
        assert alert.severity == "caution"
        assert alert.value == pytest.approx(180.0)
        assert alert.expected == pytest.approx(160.0)
        assert alert.deviation == pytest.approx(20.0)

    def test_altitude_bust_alert_values(self) -> None:
        monitor = DeviationMonitor()
        state = _make_state(
            flight_phase=FlightPhase.CRUISE,
            altitude_msl=5400.0,
            ap_master=True,
            ap_altitude=5000.0,
        )
        alerts = monitor.check(state)
        alert = next(a for a in alerts if a.name == "altitude_bust")
        assert alert.severity == "caution"
        assert alert.value == pytest.approx(5400.0)
        assert alert.expected == pytest.approx(5000.0)
        assert alert.deviation == pytest.approx(400.0)

    def test_stall_warning_is_warning_severity(self) -> None:
        monitor = DeviationMonitor()
        state = _make_state(flight_phase=FlightPhase.APPROACH, ias=40.0, altitude_agl=500.0)
        alerts = monitor.check(state)
        alert = next(a for a in alerts if a.name == "stall_warning")
        assert alert.severity == "warning"


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


class TestEdgeCases:
    def test_no_alerts_on_normal_flight(self) -> None:
        monitor = DeviationMonitor()
        state = _make_state(
            flight_phase=FlightPhase.CRUISE,
            ias=150.0,
            altitude_msl=8000.0,
            altitude_agl=7500.0,
            pitch=2.0,
            bank=5.0,
        )
        alerts = monitor.check(state)
        assert len(alerts) == 0

    def test_multiple_alerts_fire_simultaneously(self) -> None:
        monitor = DeviationMonitor()
        state = _make_state(
            flight_phase=FlightPhase.APPROACH,
            ias=45.0,  # triggers speed_low_approach + stall_warning
            altitude_agl=400.0,
            gear_handle=False,  # triggers gear_not_down_low
            flaps_percent=0.0,  # triggers flaps_not_set_approach
            ap_master=False,  # triggers no_ap_high_workload
            bank=35.0,  # triggers excessive_bank
        )
        alerts = monitor.check(state)
        names = {a.name for a in alerts}
        assert "speed_low_approach" in names
        assert "stall_warning" in names
        assert "gear_not_down_low" in names
        assert "flaps_not_set_approach" in names
        assert "no_ap_high_workload" in names
        assert "excessive_bank" in names

    def test_empty_rules(self) -> None:
        monitor = DeviationMonitor(rules=[])
        state = _make_state()
        assert monitor.check(state) == []

    def test_preflight_mostly_silent(self) -> None:
        """Preflight should not trigger speed/altitude/config rules."""
        monitor = DeviationMonitor()
        state = _make_state(
            flight_phase=FlightPhase.PREFLIGHT,
            ias=0.0,
            altitude_agl=5.0,
            altitude_msl=100.0,
        )
        alerts = monitor.check(state)
        # Only pitch_down could fire if pitch were extreme, nothing else
        assert len(alerts) == 0
