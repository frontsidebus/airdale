"""Tests for LLM optimization: dynamic temperature, model routing, query classification."""

from __future__ import annotations

import pytest

from orchestrator.claude_client import (
    classify_query,
    get_model_for_query,
    get_temperature_for_context,
)
from orchestrator.sim_client import FlightPhase

# ---------------------------------------------------------------------------
# Dynamic temperature
# ---------------------------------------------------------------------------


class TestDynamicTemperature:
    """Test temperature selection based on flight phase and query type."""

    @pytest.mark.parametrize(
        "phase,expected",
        [
            (FlightPhase.TAKEOFF, 0.1),
            (FlightPhase.APPROACH, 0.1),
            (FlightPhase.LANDING, 0.1),
        ],
    )
    def test_critical_phases(self, phase: FlightPhase, expected: float) -> None:
        temp = get_temperature_for_context(phase, "normal")
        assert temp == expected

    @pytest.mark.parametrize(
        "phase,expected",
        [
            (FlightPhase.CLIMB, 0.3),
            (FlightPhase.DESCENT, 0.3),
            (FlightPhase.TAXI, 0.3),
        ],
    )
    def test_normal_phases(self, phase: FlightPhase, expected: float) -> None:
        temp = get_temperature_for_context(phase, "normal")
        assert temp == expected

    @pytest.mark.parametrize(
        "phase,expected",
        [
            (FlightPhase.PREFLIGHT, 0.5),
            (FlightPhase.CRUISE, 0.5),
            (FlightPhase.LANDED, 0.5),
        ],
    )
    def test_relaxed_phases(self, phase: FlightPhase, expected: float) -> None:
        temp = get_temperature_for_context(phase, "normal")
        assert temp == expected

    def test_emergency_query_overrides_phase(self) -> None:
        """Emergency queries should use normal temp regardless of phase."""
        temp = get_temperature_for_context(FlightPhase.CRUISE, "emergency")
        assert temp == 0.3  # normal, not relaxed

    def test_short_query_overrides_phase(self) -> None:
        temp = get_temperature_for_context(FlightPhase.CRUISE, "short")
        assert temp == 0.3

    def test_briefing_query_overrides_phase(self) -> None:
        temp = get_temperature_for_context(FlightPhase.CRUISE, "briefing")
        assert temp == 0.3

    def test_custom_temperatures(self) -> None:
        temp = get_temperature_for_context(
            FlightPhase.TAKEOFF,
            "normal",
            temp_critical=0.05,
            temp_normal=0.2,
            temp_relaxed=0.4,
        )
        assert temp == 0.05


# ---------------------------------------------------------------------------
# Model routing
# ---------------------------------------------------------------------------


class TestModelRouting:
    def test_short_query_uses_fast_model(self) -> None:
        model = get_model_for_query(
            "short",
            model_default="claude-sonnet-4-6-20250514",
            model_fast="claude-haiku-4-5-20251001",
        )
        assert model == "claude-haiku-4-5-20251001"

    def test_normal_query_uses_default_model(self) -> None:
        model = get_model_for_query(
            "normal",
            model_default="claude-sonnet-4-6-20250514",
            model_fast="claude-haiku-4-5-20251001",
        )
        assert model == "claude-sonnet-4-6-20250514"

    def test_briefing_query_uses_default_model(self) -> None:
        model = get_model_for_query(
            "briefing",
            model_default="claude-sonnet-4-6-20250514",
            model_fast="claude-haiku-4-5-20251001",
        )
        assert model == "claude-sonnet-4-6-20250514"

    def test_emergency_query_uses_default_model(self) -> None:
        model = get_model_for_query(
            "emergency",
            model_default="claude-sonnet-4-6-20250514",
            model_fast="claude-haiku-4-5-20251001",
        )
        assert model == "claude-sonnet-4-6-20250514"


# ---------------------------------------------------------------------------
# Query classification (enhanced with emergency)
# ---------------------------------------------------------------------------


class TestQueryClassification:
    """Test the enhanced query classifier with emergency detection."""

    @pytest.mark.parametrize(
        "message,expected",
        [
            ("Mayday mayday mayday", "emergency"),
            ("We have an engine fire", "emergency"),
            ("Engine failure!", "emergency"),
            ("Pan-Pan, we have smoke in the cockpit", "emergency"),
            ("I need to declare an emergency", "emergency"),
            ("TCAS RA!", "emergency"),
            ("GPWS terrain warning", "emergency"),
        ],
    )
    def test_emergency_classification(self, message: str, expected: str) -> None:
        assert classify_query(message) == expected

    @pytest.mark.parametrize(
        "message,expected",
        [
            ("Roger", "short"),
            ("Copy that", "short"),
            ("Thanks", "short"),
            ("What's my altitude?", "short"),
            ("How far to the airport?", "short"),
            ("Yes", "short"),
        ],
    )
    def test_short_classification(self, message: str, expected: str) -> None:
        assert classify_query(message) == expected

    @pytest.mark.parametrize(
        "message,expected",
        [
            ("Brief me on the approach", "briefing"),
            ("Walk me through the engine start procedure", "briefing"),
            ("Create a flight plan from KJFK to KLAX", "briefing"),
            ("Explain how the autopilot works", "briefing"),
        ],
    )
    def test_briefing_classification(self, message: str, expected: str) -> None:
        assert classify_query(message) == expected

    def test_normal_classification(self) -> None:
        assert classify_query("What's the weather like at our destination?") == "normal"

    def test_emergency_takes_priority_over_short(self) -> None:
        """'Mayday' should be emergency, not short (even if it starts with a short word)."""
        assert classify_query("Mayday") == "emergency"
