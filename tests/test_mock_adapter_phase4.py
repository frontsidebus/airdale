"""Tests for mock adapter Phase 4 compatibility.

Verifies that the mock adapter can handle any proactive-copilot-related
commands and that its telemetry output is compatible with Phase 4 modules
(callout engine, deviation monitor, emergency detector).
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

# mock_adapter lives in tools/ which is not a package.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))

from mock_adapter import MockAircraftState

# Phase 4 modules — import with graceful fallback.
try:
    from orchestrator.sim_client import SimState
except ImportError:
    SimState = None  # type: ignore[assignment,misc]

try:
    from orchestrator.callouts import CalloutEngine
except ImportError:
    CalloutEngine = None  # type: ignore[assignment,misc]

try:
    from orchestrator.deviation_monitor import DeviationMonitor
except ImportError:
    DeviationMonitor = None  # type: ignore[assignment,misc]

try:
    from orchestrator.emergency import EmergencyDetector, EmergencyThresholds
except ImportError:
    EmergencyDetector = None  # type: ignore[assignment,misc]
    EmergencyThresholds = None  # type: ignore[assignment,misc]


# ============================================================================
# Mock adapter telemetry -> SimState compatibility
# ============================================================================


@pytest.mark.skipif(SimState is None, reason="orchestrator.sim_client not importable")
class TestMockAdapterTelemetryCompat:
    """Verify that MockAircraftState.to_telemetry_json() produces JSON
    that SimState can parse, which is required for all Phase 4 modules.
    """

    def test_telemetry_json_parses_as_simstate(self) -> None:
        state = MockAircraftState()
        telem = state.to_telemetry_json()
        sim_state = SimState.model_validate(telem)
        assert sim_state.connected is True
        assert sim_state.aircraft == state.aircraft

    def test_engine_data_round_trips(self) -> None:
        state = MockAircraftState(engine_rpm=2400.0, oil_temp=190.0, oil_pressure=65.0)
        telem = state.to_telemetry_json()
        sim_state = SimState.model_validate(telem)

        engines = sim_state.engines.active_engines
        assert len(engines) >= 1
        assert engines[0].rpm == pytest.approx(2400.0)
        assert engines[0].oil_temp == pytest.approx(190.0)

    def test_surfaces_round_trip(self) -> None:
        state = MockAircraftState(gear_handle=True, flaps_percent=30.0, spoilers_percent=50.0)
        telem = state.to_telemetry_json()
        sim_state = SimState.model_validate(telem)

        assert sim_state.surfaces.gear_handle is True
        assert sim_state.surfaces.flaps_percent == pytest.approx(30.0)
        assert sim_state.surfaces.spoilers_percent == pytest.approx(50.0)

    def test_speeds_round_trip(self) -> None:
        state = MockAircraftState(
            indicated_airspeed=120.0, ground_speed=130.0, vertical_speed=-500.0
        )
        telem = state.to_telemetry_json()
        sim_state = SimState.model_validate(telem)

        assert sim_state.speeds.indicated_airspeed == pytest.approx(120.0)
        assert sim_state.speeds.ground_speed == pytest.approx(130.0)
        assert sim_state.speeds.vertical_speed == pytest.approx(-500.0)

    def test_position_round_trip(self) -> None:
        state = MockAircraftState(
            latitude=40.0, longitude=-74.0, altitude_msl=5000.0, altitude_agl=4500.0
        )
        telem = state.to_telemetry_json()
        sim_state = SimState.model_validate(telem)

        assert sim_state.position.altitude_msl == pytest.approx(5000.0)
        assert sim_state.position.altitude_agl == pytest.approx(4500.0)


# ============================================================================
# Mock adapter -> CalloutEngine compatibility
# ============================================================================


@pytest.mark.skipif(
    CalloutEngine is None or SimState is None,
    reason="callouts or sim_client module not available",
)
class TestMockAdapterCalloutCompat:
    """Verify that mock adapter telemetry can be fed to the CalloutEngine."""

    def test_callout_engine_accepts_mock_telemetry(self) -> None:
        """CalloutEngine.update() should not error on mock adapter states."""
        engine = CalloutEngine()

        state1 = MockAircraftState(indicated_airspeed=50.0, altitude_agl=0.0)
        state2 = MockAircraftState(indicated_airspeed=90.0, altitude_agl=0.0)

        sim1 = SimState.model_validate(state1.to_telemetry_json())
        sim2 = SimState.model_validate(state2.to_telemetry_json())

        # Should not raise
        callouts = engine.update(sim2, sim1)
        assert isinstance(callouts, list)


# ============================================================================
# Mock adapter -> DeviationMonitor compatibility
# ============================================================================


@pytest.mark.skipif(
    DeviationMonitor is None or SimState is None,
    reason="deviation_monitor or sim_client module not available",
)
class TestMockAdapterDeviationCompat:
    """Verify that mock adapter telemetry can be fed to the DeviationMonitor."""

    def test_deviation_monitor_accepts_mock_telemetry(self) -> None:
        monitor = DeviationMonitor()

        state = MockAircraftState(indicated_airspeed=180.0, altitude_agl=1400.0)
        sim_state = SimState.model_validate(state.to_telemetry_json())
        # Set approach phase for deviation rules to evaluate
        sim_state.flight_phase = "APPROACH"

        # Should not raise
        alerts = monitor.check(sim_state)
        assert isinstance(alerts, list)


# ============================================================================
# Mock adapter -> EmergencyDetector compatibility
# ============================================================================


@pytest.mark.skipif(
    EmergencyDetector is None or SimState is None,
    reason="emergency or sim_client module not available",
)
class TestMockAdapterEmergencyCompat:
    """Verify that mock adapter telemetry works with EmergencyDetector."""

    def test_emergency_detector_accepts_mock_telemetry(self) -> None:
        detector = EmergencyDetector(
            thresholds=EmergencyThresholds(min_detection_duration=0),
        )

        healthy = MockAircraftState(engine_rpm=2400.0)
        failed = MockAircraftState(engine_rpm=0.0)

        sim_healthy = SimState.model_validate(healthy.to_telemetry_json())
        sim_failed = SimState.model_validate(failed.to_telemetry_json())

        sim_healthy.flight_phase = "CRUISE"
        sim_failed.flight_phase = "CRUISE"

        # Should not raise
        result = detector.evaluate(sim_healthy, sim_failed)
        # Engine failure should be detected
        assert result is not None
        assert "ENGINE" in result.emergency_type.value


# ============================================================================
# Mock adapter command handling — Phase 4 proactive commands
# ============================================================================


class TestMockAdapterPhase4Commands:
    """Verify mock adapter handles commands that might be issued by
    Phase 4 proactive systems (e.g., gear up after positive rate).
    """

    def test_gear_up_command(self) -> None:
        """Proactive gear-up prompt results in GEAR_UP command."""
        state = MockAircraftState(gear_handle=True)
        desc = state.apply_command("GEAR_UP", 0)
        assert state.gear_handle is False
        assert isinstance(desc, str)

    def test_gear_down_command(self) -> None:
        """Approach gear-down advisory results in GEAR_DOWN command."""
        state = MockAircraftState(gear_handle=False)
        state.apply_command("GEAR_DOWN", 0)
        assert state.gear_handle is True

    def test_throttle_adjustment_for_speed_deviation(self) -> None:
        """Speed deviation might lead to throttle adjustment."""
        state = MockAircraftState()
        desc = state.apply_command("THROTTLE_SET", 8191)
        assert isinstance(desc, str)
        assert len(desc) > 0

    def test_flaps_for_approach_config(self) -> None:
        """Approach checklist may require flap settings."""
        state = MockAircraftState(flaps_percent=0.0)
        state.apply_command("FLAPS_1", 0)
        assert state.flaps_percent > 0

    def test_command_log_tracks_phase4_commands(self) -> None:
        """Command log should track all commands issued by proactive systems."""
        state = MockAircraftState(gear_handle=True)
        state.apply_command("GEAR_UP", 0)
        state.apply_command("FLAPS_1", 0)

        assert len(state.command_log) == 2
        commands_issued = [entry["command"] for entry in state.command_log]
        assert "GEAR_UP" in commands_issued
        assert "FLAPS_1" in commands_issued
