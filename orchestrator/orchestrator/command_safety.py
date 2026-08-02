"""Pre-execution safety validation for aircraft control commands.

Checks proposed SimConnect commands against current telemetry to prevent
dangerous actions (e.g., gear up on the ground, flaps above Vfe). Each rule
is a data-driven ``SafetyRule`` that can be added or modified without touching
evaluation logic.

Usage:
    checker = CommandSafetyCheck()
    result = checker.check("GEAR_UP", 0, sim_state, aircraft_type="C172")
    if result.severity == "blocked":
        return {"error": result.reason}
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass

from .sim_client import FlightPhase, SimState
from .validation import AircraftLimits, resolve_aircraft_type

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Result type
# ---------------------------------------------------------------------------


@dataclass
class SafetyResult:
    """Outcome of a pre-execution safety check."""

    safe: bool
    command: str
    reason: str = ""
    severity: str = ""  # "warning" or "blocked"; empty when safe


# ---------------------------------------------------------------------------
# Rule definition
# ---------------------------------------------------------------------------


@dataclass
class SafetyRule:
    """A single data-driven safety rule.

    Attributes:
        name: Human-readable identifier for logging / diagnostics.
        commands: Set of SimConnect command strings this rule applies to.
        condition: Callable that receives (command, value, state, limits) and
            returns ``True`` when the unsafe condition is detected.
        severity: ``"blocked"`` prevents execution; ``"warning"`` allows it
            but includes an advisory message.
        message_template: Format string for the reason.  May reference
            ``{command}``, ``{ias}``, ``{agl}``, ``{phase}``, ``{vfe}``.
    """

    name: str
    commands: set[str]
    condition: Callable[[str, int, SimState, AircraftLimits | None], bool]
    severity: str  # "blocked" | "warning"
    message_template: str


# ---------------------------------------------------------------------------
# Built-in rules
# ---------------------------------------------------------------------------


def _gear_up_too_low(_cmd: str, _val: int, state: SimState, _limits: AircraftLimits | None) -> bool:
    return state.position.altitude_agl < 200 and not state.on_ground


def _gear_up_on_ground(
    _cmd: str, _val: int, state: SimState, _limits: AircraftLimits | None
) -> bool:
    return state.on_ground


def _gear_down_too_fast(
    _cmd: str, _val: int, state: SimState, _limits: AircraftLimits | None
) -> bool:
    return state.speeds.indicated_airspeed > 180


def _flaps_above_vfe(_cmd: str, _val: int, state: SimState, limits: AircraftLimits | None) -> bool:
    vfe = limits.vfe if limits else 0
    if vfe <= 0:
        return False
    return state.speeds.indicated_airspeed > vfe


def _flaps_full_at_cruise_speed(
    cmd: str, val: int, state: SimState, _limits: AircraftLimits | None
) -> bool:
    # FLAPS_SET with max value (16383) or FLAPS_FULL-equivalent
    is_full = (cmd == "FLAPS_SET" and val >= 16383) or cmd == "FLAPS_FULL"
    return is_full and state.speeds.indicated_airspeed > 150


def _ap_disconnect_low(
    _cmd: str, _val: int, state: SimState, _limits: AircraftLimits | None
) -> bool:
    return state.autopilot.master and state.position.altitude_agl < 500 and not state.on_ground


def _throttle_idle_on_approach(
    _cmd: str, val: int, state: SimState, _limits: AircraftLimits | None
) -> bool:
    # THROTTLE_SET uses 0-16383 range; 10% ~ 1638
    throttle_pct = val / 16383 * 100 if val >= 0 else 0
    return (
        throttle_pct < 10
        and state.flight_phase == FlightPhase.APPROACH
        and state.position.altitude_agl > 100
    )


# ---------------------------------------------------------------------------
# Gap 2 / CR-05 -- rules for the surface this phase itself made reachable
# ---------------------------------------------------------------------------
#
# Phase 2 records an explicit non-goal: "no new envelope rules. Those are SAFE-*
# territory and already exist." The six rules below are not a breach of it.
#
# CMD-07 -- Phase 2's own work, in plan 02-02 -- registered FUEL_SELECTOR_OFF,
# FUEL_SELECTOR_ALL/LEFT/RIGHT/SET and CROSS_FEED_OPEN/OFF/TOGGLE in the MSFS
# adapter's CommandMap. Before that change those events NACKed; after it,
# TransmitClientEvent fires for real. Both systems were already in the
# set_aircraft_control enum, so the change widened what a named tool call can
# actually do to the aircraft.
#
# MAGNETO_SET was deliberately held back from exactly that treatment, with the
# stated reason that registering it "turns a named tool call into a working
# in-flight engine shutdown with nothing in front of it" (D-01). Fuel selector OFF
# in flight is an in-flight engine shutdown by another route, and it had *less* in
# front of it than magnetos would have: no DEFAULT_RULES entry, a default
# AUTHORITY_LEVEL of `full`, and an `assisted` level that cannot withhold what no
# rule flagged. The reachable set and the deferred set have to follow one severity
# rationale; before these rules they followed two.
#
# So these add no coverage beyond the surface this phase itself made reachable --
# they restore the posture that this phase's own change removed. A phase that
# widens the write surface owns the rules for what it widened.
#
# Every message_template below may reference only {command}, {ias}, {agl}, {phase}
# and {vfe}. check() formats with exactly those five; anything else raises KeyError
# at check time, inside the command path, when the rule fires -- which is in flight.


# "Stopped, or as good as", not a taxi speed. The case this exists for is a brake
# toggle at landing-rollout speed, and a rule set at normal taxi speed would let
# that through. Anything above a walking pace is still moving.
PARKING_BRAKE_MAX_GROUND_SPEED_KT = 5.0


def _fuel_selector_off_in_flight(
    _cmd: str, _val: int, state: SimState, _limits: AircraftLimits | None
) -> bool:
    return not state.on_ground


def _fuel_selector_set_to_off_in_flight(
    _cmd: str, val: int, state: SimState, _limits: AircraftLimits | None
) -> bool:
    # FUEL_SELECTOR_SET takes a raw, unscaled selector index; 0 is OFF. Non-zero
    # indices are deliberately untouched: which tank a given index selects is
    # aircraft-dependent and this layer has no basis on which to judge it.
    return val == 0 and not state.on_ground


def _mixture_cutoff_in_flight(
    _cmd: str, val: int, state: SimState, _limits: AircraftLimits | None
) -> bool:
    # _resolve_command scales a percentage by 16383/100, so "mixture set 0" arrives
    # here as 0 -- idle cut-off.
    return val <= 0 and not state.on_ground


def _crossfeed_change_in_flight(
    _cmd: str, _val: int, state: SimState, _limits: AircraftLimits | None
) -> bool:
    # WARNING, not blocked, and the choice is deliberate. Crossfeed is a legitimate
    # in-flight fuel-balancing action, and CLOSING it is frequently the corrective
    # move -- blocking CROSS_FEED_OFF in flight would prevent the safe action along
    # with the unsafe one, which is how a safety layer earns being configured away.
    # A warning is enough to do the work: `assisted` withholds on it and `full`
    # executes with the concern attached (T-02-14-04).
    return not state.on_ground


def _parking_brake_on_the_roll(
    _cmd: str, _val: int, state: SimState, _limits: AircraftLimits | None
) -> bool:
    return state.on_ground and state.speeds.ground_speed > PARKING_BRAKE_MAX_GROUND_SPEED_KT


def _parking_brake_in_flight(
    _cmd: str, _val: int, state: SimState, _limits: AircraftLimits | None
) -> bool:
    return not state.on_ground


DEFAULT_RULES: list[SafetyRule] = [
    SafetyRule(
        name="gear_up_on_ground",
        commands={"GEAR_UP"},
        condition=_gear_up_on_ground,
        severity="blocked",
        message_template="Cannot retract gear while on the ground",
    ),
    SafetyRule(
        name="gear_up_too_low",
        commands={"GEAR_UP"},
        condition=_gear_up_too_low,
        severity="blocked",
        message_template="Gear retraction blocked -- altitude AGL ({agl:.0f} ft) is below 200 ft",
    ),
    SafetyRule(
        name="gear_down_too_fast",
        commands={"GEAR_DOWN"},
        condition=_gear_down_too_fast,
        severity="warning",
        message_template=(
            "Gear extension at {ias:.0f} kt IAS exceeds 180 kt limit -- risk of gear door damage"
        ),
    ),
    SafetyRule(
        name="flaps_above_vfe",
        commands={"FLAPS_SET", "FLAPS_1", "FLAPS_2", "FLAPS_3", "FLAPS_FULL", "FLAPS_INCR"},
        condition=_flaps_above_vfe,
        severity="warning",
        message_template="Flap extension at {ias:.0f} kt exceeds Vfe ({vfe:.0f} kt)",
    ),
    SafetyRule(
        name="flaps_full_at_cruise_speed",
        commands={"FLAPS_SET", "FLAPS_FULL"},
        condition=_flaps_full_at_cruise_speed,
        severity="warning",
        message_template="Full flaps at {ias:.0f} kt -- exceeds 150 kt structural advisory",
    ),
    SafetyRule(
        name="ap_disconnect_low",
        commands={"AP_MASTER"},
        condition=_ap_disconnect_low,
        severity="warning",
        message_template=(
            "Autopilot disconnect at {agl:.0f} ft AGL -- be ready for immediate manual control"
        ),
    ),
    SafetyRule(
        name="throttle_idle_on_approach",
        commands={"THROTTLE_SET"},
        condition=_throttle_idle_on_approach,
        severity="warning",
        message_template=(
            "Throttle to idle on approach at {agl:.0f} ft AGL -- maintain power until short final"
        ),
    ),
    # --- Gap 2 / CR-05: appended, so the seven above keep their order and their
    # --- evaluation semantics unchanged. See the block comment above the
    # --- conditions for why a phase with a "no new envelope rules" non-goal
    # --- nonetheless owns these six.
    SafetyRule(
        name="fuel_selector_off_in_flight",
        commands={"FUEL_SELECTOR_OFF"},
        condition=_fuel_selector_off_in_flight,
        severity="blocked",
        message_template=(
            "Fuel selector to OFF in flight at {agl:.0f} ft AGL starves the engine -- "
            "this is an in-flight shutdown, not a fuel management change"
        ),
    ),
    SafetyRule(
        name="fuel_selector_set_to_off_in_flight",
        commands={"FUEL_SELECTOR_SET"},
        condition=_fuel_selector_set_to_off_in_flight,
        severity="blocked",
        message_template=(
            "Fuel selector to index 0 -- the OFF position on the selectors this event "
            "drives -- in flight at {agl:.0f} ft AGL starves the engine"
        ),
    ),
    SafetyRule(
        name="mixture_cutoff_in_flight",
        commands={"MIXTURE_SET"},
        condition=_mixture_cutoff_in_flight,
        severity="blocked",
        message_template=(
            "Mixture to idle cut-off in flight at {agl:.0f} ft AGL shuts the engine down"
        ),
    ),
    SafetyRule(
        name="crossfeed_change_in_flight",
        commands={"CROSS_FEED_OPEN", "CROSS_FEED_OFF", "CROSS_FEED_TOGGLE"},
        condition=_crossfeed_change_in_flight,
        severity="warning",
        message_template=(
            "Crossfeed change in flight at {agl:.0f} ft AGL -- confirm tank quantities "
            "and pump configuration first"
        ),
    ),
    SafetyRule(
        name="parking_brake_on_the_roll",
        commands={"PARKING_BRAKES"},
        condition=_parking_brake_on_the_roll,
        severity="blocked",
        # The condition reads ground speed; the template can only report IAS, because
        # check() supplies five names and ground_speed is not one of them.
        message_template=(
            "Parking brake at {ias:.0f} kt on the ground -- the aircraft is still moving"
        ),
    ),
    SafetyRule(
        name="parking_brake_in_flight",
        commands={"PARKING_BRAKES"},
        condition=_parking_brake_in_flight,
        severity="warning",
        message_template=(
            "Parking brake toggled in flight at {agl:.0f} ft AGL -- a set brake locks "
            "the wheels on touchdown"
        ),
    ),
]


# ---------------------------------------------------------------------------
# Safety checker
# ---------------------------------------------------------------------------


class CommandSafetyCheck:
    """Pre-execution safety validation for aircraft commands.

    Evaluates a list of ``SafetyRule`` instances against the current sim state.
    The first ``blocked`` rule short-circuits; all ``warning`` rules accumulate.
    """

    def __init__(self, rules: list[SafetyRule] | None = None) -> None:
        self._rules = rules if rules is not None else list(DEFAULT_RULES)

    @property
    def rules(self) -> list[SafetyRule]:
        """Accessor for the active rule set (useful for inspection / testing)."""
        return self._rules

    def add_rule(self, rule: SafetyRule) -> None:
        """Append a custom rule to the active rule set."""
        self._rules.append(rule)

    def check(
        self,
        command: str,
        value: int,
        sim_state: SimState,
        aircraft_type: str = "",
    ) -> SafetyResult:
        """Check whether *command* is safe given current flight conditions.

        Returns a ``SafetyResult`` indicating whether the command should
        proceed, along with any warning or blocking reason.
        """
        limits = resolve_aircraft_type(aircraft_type) if aircraft_type else None

        # Collect all triggered warnings; first block is authoritative.
        warnings: list[str] = []

        for rule in self._rules:
            if command not in rule.commands:
                continue

            if not rule.condition(command, value, sim_state, limits):
                continue

            # Build the reason message with available context vars
            reason = rule.message_template.format(
                command=command,
                ias=sim_state.speeds.indicated_airspeed,
                agl=sim_state.position.altitude_agl,
                phase=sim_state.flight_phase.value,
                vfe=limits.vfe if limits else 0,
            )

            logger.info("Safety rule '%s' triggered: %s", rule.name, reason)

            if rule.severity == "blocked":
                return SafetyResult(
                    safe=False,
                    command=command,
                    reason=reason,
                    severity="blocked",
                )

            warnings.append(reason)

        if warnings:
            return SafetyResult(
                safe=True,
                command=command,
                reason="; ".join(warnings),
                severity="warning",
            )

        return SafetyResult(safe=True, command=command)
