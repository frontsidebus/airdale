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
