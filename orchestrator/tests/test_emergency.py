"""Tests for the emergency detection and fast-path response system."""

from __future__ import annotations

import pytest

from orchestrator.emergency import (
    EmergencyDetector,
    EmergencyThresholds,
    EmergencyType,
    build_emergency_response,
)
from orchestrator.sim_client import (
    EngineData,
    Engines,
    FlightPhase,
    Position,
    SimState,
    Speeds,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_state(
    *,
    phase: FlightPhase = FlightPhase.CRUISE,
    rpm: float = 2400.0,
    egt: float = 800.0,
    altitude_msl: float = 5000.0,
    altitude_agl: float = 4500.0,
    ias: float = 120.0,
) -> SimState:
    """Create a SimState with sensible defaults for testing."""
    return SimState(
        connected=True,
        aircraft="C172",
        flight_phase=phase,
        position=Position(
            latitude=40.0,
            longitude=-74.0,
            altitude_msl=altitude_msl,
            altitude_agl=altitude_agl,
        ),
        speeds=Speeds(indicated_airspeed=ias, ground_speed=110.0),
        engines=Engines(
            engine_count=1,
            engines=[EngineData(rpm=rpm, egt=egt, oil_temp=180.0, oil_pressure=60.0)],
        ),
    )


# ---------------------------------------------------------------------------
# EmergencyResponse
# ---------------------------------------------------------------------------


class TestEmergencyResponse:
    def test_spoken_response_format(self) -> None:
        resp = build_emergency_response(
            EmergencyType.ENGINE_FAILURE_TAKEOFF,
            _make_state(phase=FlightPhase.TAKEOFF, rpm=0),
        )
        spoken = resp.spoken_response
        assert "ENGINE FAILURE" in spoken
        assert "Step 1:" in spoken
        assert "Step 2:" in spoken
        assert "Step 3:" in spoken

    def test_full_response_includes_followup(self) -> None:
        resp = build_emergency_response(
            EmergencyType.ENGINE_FIRE,
            _make_state(egt=1600),
        )
        full = resp.full_response
        assert "Follow-up:" in full
        assert "Fuel selector" in full

    def test_context_includes_emergency_type(self) -> None:
        state = _make_state()
        resp = build_emergency_response(EmergencyType.ENGINE_FAILURE_CRUISE, state)
        ctx = resp.build_context(state)
        assert ctx["emergency_type"] == "ENGINE_FAILURE_CRUISE"
        assert ctx["emergency_start_altitude"] == 5000.0
        assert ctx["squawk"] == "7700"

    def test_send_to_llm_default_true(self) -> None:
        resp = build_emergency_response(EmergencyType.RAPID_DECOMPRESSION, _make_state())
        assert resp.send_to_llm is True


# ---------------------------------------------------------------------------
# EmergencyDetector — engine failure
# ---------------------------------------------------------------------------


class TestEngineFailureDetection:
    def test_engine_failure_during_takeoff(self) -> None:
        detector = EmergencyDetector(EmergencyThresholds(min_detection_duration=0.0))
        prev = _make_state(phase=FlightPhase.TAKEOFF, rpm=2400)
        curr = _make_state(phase=FlightPhase.TAKEOFF, rpm=0)

        result = detector.evaluate(prev, curr)
        assert result is not None
        assert result.emergency_type == EmergencyType.ENGINE_FAILURE_TAKEOFF

    def test_engine_failure_during_cruise(self) -> None:
        detector = EmergencyDetector(EmergencyThresholds(min_detection_duration=0.0))
        prev = _make_state(phase=FlightPhase.CRUISE, rpm=2300)
        curr = _make_state(phase=FlightPhase.CRUISE, rpm=50)

        result = detector.evaluate(prev, curr)
        assert result is not None
        assert result.emergency_type == EmergencyType.ENGINE_FAILURE_CRUISE

    def test_no_false_positive_normal_operation(self) -> None:
        detector = EmergencyDetector(EmergencyThresholds(min_detection_duration=0.0))
        prev = _make_state(phase=FlightPhase.CRUISE, rpm=2400)
        curr = _make_state(phase=FlightPhase.CRUISE, rpm=2350)

        result = detector.evaluate(prev, curr)
        assert result is None

    def test_no_detection_on_ground_preflight(self) -> None:
        """Engine shutdown during preflight is normal, not an emergency."""
        detector = EmergencyDetector(EmergencyThresholds(min_detection_duration=0.0))
        prev = _make_state(phase=FlightPhase.PREFLIGHT, rpm=800, altitude_agl=0)
        curr = _make_state(phase=FlightPhase.PREFLIGHT, rpm=0, altitude_agl=0)

        result = detector.evaluate(prev, curr)
        assert result is None

    def test_only_one_emergency_at_a_time(self) -> None:
        detector = EmergencyDetector(EmergencyThresholds(min_detection_duration=0.0))
        prev = _make_state(phase=FlightPhase.CRUISE, rpm=2400)
        curr = _make_state(phase=FlightPhase.CRUISE, rpm=0)

        result1 = detector.evaluate(prev, curr)
        assert result1 is not None

        # Second evaluation should return None (already handling)
        result2 = detector.evaluate(prev, curr)
        assert result2 is None

    def test_clear_allows_new_detection(self) -> None:
        detector = EmergencyDetector(EmergencyThresholds(min_detection_duration=0.0))
        prev = _make_state(phase=FlightPhase.CRUISE, rpm=2400)
        curr = _make_state(phase=FlightPhase.CRUISE, rpm=0)

        detector.evaluate(prev, curr)
        detector.clear()

        result = detector.evaluate(prev, curr)
        assert result is not None


# ---------------------------------------------------------------------------
# EmergencyDetector — engine fire
# ---------------------------------------------------------------------------


class TestEngineFireDetection:
    def test_high_egt_triggers_fire(self) -> None:
        detector = EmergencyDetector(EmergencyThresholds(min_detection_duration=0.0))
        prev = _make_state(phase=FlightPhase.CRUISE, egt=800)
        curr = _make_state(phase=FlightPhase.CRUISE, egt=1600, rpm=2000)

        result = detector.evaluate(prev, curr)
        assert result is not None
        assert result.emergency_type == EmergencyType.ENGINE_FIRE

    def test_high_egt_dead_engine_no_fire(self) -> None:
        """High EGT on a dead engine might be residual heat, not fire."""
        detector = EmergencyDetector(EmergencyThresholds(min_detection_duration=0.0))
        prev = _make_state(phase=FlightPhase.CRUISE, egt=800)
        # RPM below threshold means engine is dead; don't call it a fire
        curr = _make_state(phase=FlightPhase.CRUISE, egt=1600, rpm=50)

        result = detector.evaluate(prev, curr)
        # Should detect engine failure, not fire
        assert result is None or result.emergency_type != EmergencyType.ENGINE_FIRE


# ---------------------------------------------------------------------------
# EmergencyDetector — debouncing
# ---------------------------------------------------------------------------


class TestDebouncing:
    def test_debounce_requires_sustained_detection(self) -> None:
        """With a non-zero duration, first detection should not trigger."""
        detector = EmergencyDetector(EmergencyThresholds(min_detection_duration=1.0))
        prev = _make_state(phase=FlightPhase.CRUISE, rpm=2400)
        curr = _make_state(phase=FlightPhase.CRUISE, rpm=0)

        # First call: sets candidate but doesn't confirm
        result = detector.evaluate(prev, curr)
        assert result is None


# ---------------------------------------------------------------------------
# All emergency types have procedures
# ---------------------------------------------------------------------------


class TestAllProcedures:
    @pytest.mark.parametrize("etype", list(EmergencyType))
    def test_every_type_has_a_procedure(self, etype: EmergencyType) -> None:
        resp = build_emergency_response(etype, _make_state())
        assert resp.title
        assert len(resp.immediate_actions) > 0
        assert resp.squawk == "7700"
