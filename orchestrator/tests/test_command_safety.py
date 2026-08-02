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
    SurfaceState,
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
    ground_speed: float = 0.0,
    gear_handle: bool = True,
) -> SimState:
    """Build a SimState with minimal overrides for safety check testing.

    ``gear_handle`` defaults to True (gear down) because that is the position
    from which ``GEAR_TOGGLE`` is hazardous -- a toggle only retracts when the
    gear is already extended.
    """
    agl = altitude_agl
    # on_ground is derived from altitude_agl < 10
    if on_ground:
        agl = 0.0
    return SimState(
        position=Position(altitude_agl=agl, altitude_msl=agl + 100),
        speeds=Speeds(indicated_airspeed=indicated_airspeed, ground_speed=ground_speed),
        flight_phase=flight_phase,
        autopilot=AutopilotState(master=ap_master),
        surfaces=SurfaceState(gear_handle=gear_handle),
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

    def test_gear_up_on_ground_blocked_regardless_of_handle_position(self) -> None:
        """GEAR_UP must not become conditional on gear_handle.

        The toggle guard reads ``gear_handle``; if it ever leaked into the
        GEAR_UP path, a stale or defaulted handle reading would silently
        unblock retraction on the ground.
        """
        state = _make_state(on_ground=True, gear_handle=False)
        checker = CommandSafetyCheck()
        result = checker.check("GEAR_UP", 0, state)
        assert result.safe is False
        assert result.severity == "blocked"


# ---------------------------------------------------------------------------
# Gear toggle rules -- the direction-blind command
# ---------------------------------------------------------------------------


class TestGearToggleSafety:
    """``GEAR_TOGGLE`` reaches the same hazard as ``GEAR_UP`` by another route.

    ``gear``/``toggle`` is in the tool enum and registered in the adapter, but
    carried no rule at all -- the same blind-toggle shape as ``parking_brake``
    (Gap 2 / CR-04), on a system where the consequence is a gear-up landing or
    a retraction on the runway. The rules key on ``gear_handle`` so a toggle
    that would *extend* stays available: blocking that would refuse a
    legitimate approach configuration, the same reasoning that gave crossfeed
    a warning rather than a block.
    """

    def test_toggle_on_ground_with_gear_down_blocked(self) -> None:
        state = _make_state(on_ground=True, gear_handle=True)
        checker = CommandSafetyCheck()
        result = checker.check("GEAR_TOGGLE", 0, state)
        assert result.safe is False
        assert result.severity == "blocked"

    def test_toggle_below_200ft_with_gear_down_blocked(self) -> None:
        state = _make_state(altitude_agl=150, gear_handle=True)
        checker = CommandSafetyCheck()
        result = checker.check("GEAR_TOGGLE", 0, state)
        assert result.safe is False
        assert result.severity == "blocked"

    def test_toggle_below_200ft_with_gear_already_up_is_allowed(self) -> None:
        """A toggle that would extend is the approach configuration, not the hazard."""
        state = _make_state(altitude_agl=150, gear_handle=False)
        checker = CommandSafetyCheck()
        result = checker.check("GEAR_TOGGLE", 0, state)
        assert result.safe is True
        assert result.severity == ""

    def test_toggle_at_cruise_altitude_with_gear_down_is_allowed(self) -> None:
        """Retraction well above the floor is normal after takeoff."""
        state = _make_state(altitude_agl=1500, gear_handle=True)
        checker = CommandSafetyCheck()
        result = checker.check("GEAR_TOGGLE", 0, state)
        assert result.safe is True
        assert result.severity == ""


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


# ---------------------------------------------------------------------------
# Gap 2 / CR-05 -- the fuel, mixture and parking-brake surface CMD-07 made live
# ---------------------------------------------------------------------------

_CR05_REGRESSION = (
    "CMD-07 registered FUEL_SELECTOR_* and CROSS_FEED_* in the adapter's CommandMap, "
    "turning a NACK into a real TransmitClientEvent, and both systems were already in "
    "the set_aircraft_control enum. MAGNETO_SET was held back from exactly that "
    "treatment because it 'turns a named tool call into a working in-flight engine "
    "shutdown with nothing in front of it' -- and fuel selector OFF in flight is an "
    "in-flight engine shutdown by another route. With no DEFAULT_RULES entry, the "
    "default AUTHORITY_LEVEL of full sends it unexamined and assisted cannot withhold "
    "what nothing flagged (CR-05)."
)

_GROUND_REGRESSION = (
    "A rule that fires during normal ground operations is worse than no rule: MERLIN "
    "refuses a routine shutdown, and a safety layer that blocks normal operations gets "
    "configured away (T-02-14-05)."
)


class TestFuelSelectorSafety:
    """`fuel_selector off` in flight is an engine shutdown; on the ground it is a shutdown."""

    def test_fuel_selector_off_in_flight_blocked(self) -> None:
        state = _make_state(altitude_agl=3000)
        result = CommandSafetyCheck().check("FUEL_SELECTOR_OFF", 0, state)
        assert result.severity == "blocked", _CR05_REGRESSION
        assert result.safe is False, _CR05_REGRESSION

    def test_fuel_selector_off_on_ground_is_untouched(self) -> None:
        state = _make_state(on_ground=True)
        result = CommandSafetyCheck().check("FUEL_SELECTOR_OFF", 0, state)
        assert result.severity == "", _GROUND_REGRESSION
        assert result.safe is True, _GROUND_REGRESSION

    def test_fuel_selector_set_to_index_zero_in_flight_blocked(self) -> None:
        """Index 0 is the OFF position on the selectors FUEL_SELECTOR_SET drives."""
        state = _make_state(altitude_agl=3000)
        result = CommandSafetyCheck().check("FUEL_SELECTOR_SET", 0, state)
        assert result.severity == "blocked", _CR05_REGRESSION

    def test_fuel_selector_set_to_a_tank_in_flight_is_untouched(self) -> None:
        """Which tank a non-zero index selects is aircraft-dependent; this layer cannot judge."""
        state = _make_state(altitude_agl=3000)
        result = CommandSafetyCheck().check("FUEL_SELECTOR_SET", 2, state)
        assert result.severity == ""
        assert result.safe is True

    def test_fuel_selector_set_to_index_zero_on_ground_is_untouched(self) -> None:
        state = _make_state(on_ground=True)
        result = CommandSafetyCheck().check("FUEL_SELECTOR_SET", 0, state)
        assert result.severity == "", _GROUND_REGRESSION

    def test_selecting_a_named_tank_is_never_flagged(self) -> None:
        """Selecting a tank is not selecting off, in any state."""
        checker = CommandSafetyCheck()
        for command in ("FUEL_SELECTOR_ALL", "FUEL_SELECTOR_LEFT", "FUEL_SELECTOR_RIGHT"):
            for state in (
                _make_state(altitude_agl=3000),
                _make_state(on_ground=True),
                _make_state(altitude_agl=100, flight_phase=FlightPhase.APPROACH),
            ):
                result = checker.check(command, 0, state)
                assert result.severity == "", f"{command} was flagged: {result.reason}"


class TestMixtureSafety:
    """`mixture set 0` scales to MIXTURE_SET 0 -- idle cut-off."""

    def test_mixture_idle_cutoff_in_flight_blocked(self) -> None:
        state = _make_state(altitude_agl=3000)
        result = CommandSafetyCheck().check("MIXTURE_SET", 0, state)
        assert result.severity == "blocked", _CR05_REGRESSION
        assert result.safe is False, _CR05_REGRESSION

    def test_mixture_full_rich_in_flight_is_untouched(self) -> None:
        state = _make_state(altitude_agl=3000)
        result = CommandSafetyCheck().check("MIXTURE_SET", 16383, state)
        assert result.severity == ""
        assert result.safe is True

    def test_mixture_idle_cutoff_on_ground_is_untouched(self) -> None:
        """Mixture to cut-off on the ground IS the normal shutdown."""
        state = _make_state(on_ground=True)
        result = CommandSafetyCheck().check("MIXTURE_SET", 0, state)
        assert result.severity == "", _GROUND_REGRESSION

    def test_mixture_leaned_in_flight_is_untouched(self) -> None:
        state = _make_state(altitude_agl=9000)
        result = CommandSafetyCheck().check("MIXTURE_SET", 8000, state)
        assert result.severity == ""


class TestCrossfeedSafety:
    """Crossfeed warns rather than blocks -- closing it is often the corrective move."""

    def test_every_crossfeed_event_warns_in_flight(self) -> None:
        checker = CommandSafetyCheck()
        state = _make_state(altitude_agl=5000)
        for command in ("CROSS_FEED_OPEN", "CROSS_FEED_OFF", "CROSS_FEED_TOGGLE"):
            result = checker.check(command, 0, state)
            assert result.severity == "warning", f"{command} did not warn in flight"
            assert result.safe is True, f"{command} was blocked; closing crossfeed must stay open"

    def test_crossfeed_on_ground_is_untouched(self) -> None:
        checker = CommandSafetyCheck()
        state = _make_state(on_ground=True)
        for command in ("CROSS_FEED_OPEN", "CROSS_FEED_OFF", "CROSS_FEED_TOGGLE"):
            result = checker.check(command, 0, state)
            assert result.severity == "", _GROUND_REGRESSION


class TestParkingBrakeSafety:
    """The explicit toggle that survives the CR-04 refusal still needs a rule behind it."""

    def test_parking_brake_while_rolling_is_blocked(self) -> None:
        state = _make_state(on_ground=True, ground_speed=45.0, indicated_airspeed=45.0)
        result = CommandSafetyCheck().check("PARKING_BRAKES", 0, state)
        assert result.severity == "blocked", (
            "a parking-brake toggle at landing-rollout speed is a runway excursion (T-02-14-01)"
        )
        assert result.safe is False

    def test_parking_brake_at_rest_is_untouched(self) -> None:
        state = _make_state(on_ground=True, ground_speed=0.0)
        result = CommandSafetyCheck().check("PARKING_BRAKES", 0, state)
        assert result.severity == "", _GROUND_REGRESSION
        assert result.safe is True

    def test_parking_brake_at_the_threshold_is_untouched(self) -> None:
        """The threshold is 'stopped, or as good as' -- at it, not above it, is fine."""
        from orchestrator.command_safety import PARKING_BRAKE_MAX_GROUND_SPEED_KT

        state = _make_state(on_ground=True, ground_speed=PARKING_BRAKE_MAX_GROUND_SPEED_KT)
        result = CommandSafetyCheck().check("PARKING_BRAKES", 0, state)
        assert result.severity == ""

    def test_parking_brake_in_flight_warns(self) -> None:
        state = _make_state(altitude_agl=2000)
        result = CommandSafetyCheck().check("PARKING_BRAKES", 0, state)
        assert result.severity == "warning"
        assert result.safe is True


class TestRuleSetShape:
    def test_rule_count(self) -> None:
        assert len(DEFAULT_RULES) == 13, (
            "seven original rules plus the six Gap 2 rules for the fuel, mixture and "
            "parking-brake surface"
        )

    def test_every_message_template_formats_with_the_supported_keys(self) -> None:
        """`check()` formats with exactly these five names and no others.

        Any other placeholder raises `KeyError` at check time -- inside the command
        path, only when the rule actually fires, which is in flight. That is the worst
        possible place to discover a typo (T-02-14-07).
        """
        for rule in DEFAULT_RULES:
            rule.message_template.format(
                command="X",
                ias=0.0,
                agl=0.0,
                phase="CRUISE",
                vfe=0.0,
            )
