"""Tests for orchestrator.command_safety — pre-execution safety validation."""

from __future__ import annotations

from orchestrator.command_safety import (
    DEFAULT_RULES,
    CommandSafetyCheck,
    SafetyResult,
    SafetyRule,
)
from orchestrator.sim_client import (
    AutopilotState,
    FlightPhase,
    Position,
    SimState,
    Speeds,
)

# ---------------------------------------------------------------------------
# SafetyResult dataclass
# ---------------------------------------------------------------------------


class TestSafetyResult:
    def test_all_fields_present(self) -> None:
        r = SafetyResult(
            safe=True,
            command="GEAR_DOWN",
            reason="",
            severity="",
        )
        assert r.safe is True
        assert r.command == "GEAR_DOWN"
        assert r.reason == ""
        assert r.severity == ""

    def test_blocked_result_fields(self) -> None:
        r = SafetyResult(
            safe=False,
            command="GEAR_UP",
            reason="Too low",
            severity="blocked",
        )
        assert r.safe is False
        assert r.severity == "blocked"

    def test_warning_result_fields(self) -> None:
        r = SafetyResult(
            safe=True,
            command="GEAR_DOWN",
            reason="High speed",
            severity="warning",
        )
        assert r.safe is True
        assert r.severity == "warning"


# ---------------------------------------------------------------------------
# Helper: build states for testing
# ---------------------------------------------------------------------------


def _make_state(
    altitude_agl: float = 1000,
    indicated_airspeed: float = 100,
    on_ground: bool = False,
    flight_phase: FlightPhase = FlightPhase.CRUISE,
    ap_master: bool = False,
) -> SimState:
    """Build a SimState with minimal overrides for safety check testing."""
    agl = altitude_agl
    # on_ground is derived from altitude_agl < 10
    if on_ground:
        agl = 0.0
    return SimState(
        position=Position(altitude_agl=agl, altitude_msl=agl + 100),
        speeds=Speeds(indicated_airspeed=indicated_airspeed),
        flight_phase=flight_phase,
        autopilot=AutopilotState(master=ap_master),
    )


# ---------------------------------------------------------------------------
# Gear up rules
# ---------------------------------------------------------------------------


class TestGearUpSafety:
    def test_gear_up_below_200ft_agl_blocked(self) -> None:
        """Gear retraction below 200ft AGL should be blocked."""
        state = _make_state(altitude_agl=150)
        checker = CommandSafetyCheck()
        result = checker.check("GEAR_UP", 0, state)
        assert result.safe is False
        assert result.severity == "blocked"

    def test_gear_up_at_500ft_agl_safe(self) -> None:
        """Gear retraction at 500ft AGL should be safe."""
        state = _make_state(altitude_agl=500)
        checker = CommandSafetyCheck()
        result = checker.check("GEAR_UP", 0, state)
        assert result.safe is True
        assert result.severity == ""

    def test_gear_up_on_ground_blocked(self) -> None:
        """Gear retraction on the ground should be blocked."""
        state = _make_state(on_ground=True)
        checker = CommandSafetyCheck()
        result = checker.check("GEAR_UP", 0, state)
        assert result.safe is False
        assert result.severity == "blocked"


# ---------------------------------------------------------------------------
# Gear down rules
# ---------------------------------------------------------------------------


class TestGearDownSafety:
    def test_gear_down_above_180kt_warning(self) -> None:
        """Gear extension above 180kt should produce a warning."""
        state = _make_state(indicated_airspeed=200)
        checker = CommandSafetyCheck()
        result = checker.check("GEAR_DOWN", 0, state)
        assert result.severity == "warning"

    def test_gear_down_at_150kt_safe(self) -> None:
        """Gear extension at 150kt should be safe."""
        state = _make_state(indicated_airspeed=150)
        checker = CommandSafetyCheck()
        result = checker.check("GEAR_DOWN", 0, state)
        assert result.safe is True
        assert result.severity == ""


# ---------------------------------------------------------------------------
# Flaps rules
# ---------------------------------------------------------------------------


class TestFlapsSafety:
    def test_flaps_full_above_vfe_warning(self) -> None:
        """Flaps above Vfe should produce a warning when aircraft limits known."""
        state = _make_state(indicated_airspeed=120)
        checker = CommandSafetyCheck()
        # C172 Vfe is 110kt
        result = checker.check("FLAPS_SET", 16383, state, aircraft_type="C172")
        assert result.severity == "warning"

    def test_flaps_full_below_vfe_safe(self) -> None:
        """Flaps below Vfe should be safe."""
        state = _make_state(indicated_airspeed=90)
        checker = CommandSafetyCheck()
        result = checker.check("FLAPS_SET", 16383, state, aircraft_type="C172")
        assert result.safe is True

    def test_flaps_full_above_150kt_structural_warning(self) -> None:
        """Full flaps above 150kt triggers structural advisory."""
        state = _make_state(indicated_airspeed=160)
        checker = CommandSafetyCheck()
        # No aircraft type -- falls through to structural check
        result = checker.check("FLAPS_SET", 16383, state)
        assert result.severity == "warning"


# ---------------------------------------------------------------------------
# Autopilot disconnect
# ---------------------------------------------------------------------------


class TestApDisconnectSafety:
    def test_ap_disconnect_below_500ft_agl_warning(self) -> None:
        """AP disconnect below 500ft AGL should produce a warning."""
        state = _make_state(altitude_agl=300, ap_master=True)
        checker = CommandSafetyCheck()
        result = checker.check("AP_MASTER", 0, state)
        assert result.severity == "warning"

    def test_ap_disconnect_at_1000ft_safe(self) -> None:
        """AP disconnect at 1000ft AGL should be safe."""
        state = _make_state(altitude_agl=1000, ap_master=True)
        checker = CommandSafetyCheck()
        result = checker.check("AP_MASTER", 0, state)
        assert result.safe is True
        assert result.severity == ""

    def test_ap_disconnect_on_ground_no_warning(self) -> None:
        """AP disconnect on the ground should not trigger low-alt warning."""
        state = _make_state(on_ground=True, ap_master=True)
        checker = CommandSafetyCheck()
        result = checker.check("AP_MASTER", 0, state)
        # on_ground check in the rule should exclude ground state
        assert result.safe is True


# ---------------------------------------------------------------------------
# Throttle idle on approach
# ---------------------------------------------------------------------------


class TestThrottleIdleSafety:
    def test_throttle_idle_on_approach_above_100ft_warning(self) -> None:
        """Throttle idle on approach above 100ft AGL should warn."""
        state = _make_state(
            altitude_agl=500,
            flight_phase=FlightPhase.APPROACH,
        )
        checker = CommandSafetyCheck()
        # THROTTLE_SET value 0 = idle
        result = checker.check("THROTTLE_SET", 0, state)
        assert result.severity == "warning"

    def test_throttle_idle_on_approach_below_100ft_safe(self) -> None:
        """Throttle idle on approach below 100ft AGL is OK (short final)."""
        state = _make_state(
            altitude_agl=50,
            flight_phase=FlightPhase.APPROACH,
        )
        checker = CommandSafetyCheck()
        result = checker.check("THROTTLE_SET", 0, state)
        assert result.safe is True

    def test_throttle_midrange_on_approach_safe(self) -> None:
        """Normal throttle on approach should be safe."""
        state = _make_state(
            altitude_agl=500,
            flight_phase=FlightPhase.APPROACH,
        )
        checker = CommandSafetyCheck()
        # ~50% throttle
        result = checker.check("THROTTLE_SET", 8192, state)
        assert result.safe is True
        assert result.severity == ""


# ---------------------------------------------------------------------------
# CommandSafetyCheck general behavior
# ---------------------------------------------------------------------------


class TestCommandSafetyCheckGeneral:
    def test_safe_command_returns_safe_true(self) -> None:
        """A command with no triggered rules should be safe."""
        state = _make_state(altitude_agl=3000, indicated_airspeed=100)
        checker = CommandSafetyCheck()
        result = checker.check("GEAR_DOWN", 0, state)
        assert result.safe is True
        assert result.severity == ""

    def test_blocked_commands_have_severity_blocked(self) -> None:
        state = _make_state(on_ground=True)
        checker = CommandSafetyCheck()
        result = checker.check("GEAR_UP", 0, state)
        assert result.severity == "blocked"

    def test_warning_commands_have_severity_warning(self) -> None:
        state = _make_state(indicated_airspeed=200)
        checker = CommandSafetyCheck()
        result = checker.check("GEAR_DOWN", 0, state)
        assert result.severity == "warning"

    def test_unrecognized_command_is_safe(self) -> None:
        """Commands with no matching rules should pass safely."""
        state = _make_state()
        checker = CommandSafetyCheck()
        result = checker.check("SOME_OTHER_COMMAND", 0, state)
        assert result.safe is True
        assert result.severity == ""

    def test_custom_rule_can_be_added(self) -> None:
        """Custom rules added via add_rule should be evaluated."""
        checker = CommandSafetyCheck()
        custom_rule = SafetyRule(
            name="test_custom",
            commands={"TEST_CMD"},
            condition=lambda cmd, val, state, limits: True,
            severity="warning",
            message_template="Custom warning for {command}",
        )
        checker.add_rule(custom_rule)
        state = _make_state()
        result = checker.check("TEST_CMD", 0, state)
        assert result.severity == "warning"
        assert "Custom warning" in result.reason

    def test_rules_property_accessible(self) -> None:
        checker = CommandSafetyCheck()
        assert len(checker.rules) == len(DEFAULT_RULES)

    def test_blocked_rule_short_circuits_warnings(self) -> None:
        """A blocked rule should return immediately without checking further."""
        state = _make_state(on_ground=True)
        checker = CommandSafetyCheck()
        result = checker.check("GEAR_UP", 0, state)
        assert result.safe is False
        assert result.severity == "blocked"
