"""Proactive aviation callout engine driven by telemetry state changes.

Monitors SimState telemetry and fires aviation callouts (V1, rotate,
altitude alerts, minimums, etc.) at the appropriate moments. Each callout
rule is bound to a flight phase and evaluated every telemetry tick.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from dataclasses import dataclass

from .sim_client import FlightPhase, SimState

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class Callout:
    """A triggered callout ready to be spoken by MERLIN."""

    name: str  # e.g., "V1", "ROTATE", "POSITIVE_RATE"
    message: str  # What MERLIN says
    priority: int = 0  # Higher = more urgent
    triggered: bool = False  # Only fire once per phase


@dataclass
class CalloutRule:
    """Defines when a callout should fire."""

    name: str
    phase: FlightPhase | None  # None = any phase
    condition: Callable[[SimState, SimState | None], bool]
    message: str | Callable[[SimState, SimState | None], str]
    priority: int = 0  # Higher = more urgent
    one_shot: bool = True  # Only trigger once per flight phase
    cooldown_secs: float = 0.0  # Min seconds between triggers


# ---------------------------------------------------------------------------
# Crossing-detection helpers
# ---------------------------------------------------------------------------


def _crossed_above(
    current: float,
    previous: float | None,
    threshold: float,
) -> bool:
    """True when value crosses *above* threshold between ticks."""
    if previous is None:
        return False
    return previous < threshold <= current


def _crossed_below(
    current: float,
    previous: float | None,
    threshold: float,
) -> bool:
    """True when value crosses *below* threshold between ticks."""
    if previous is None:
        return False
    return previous >= threshold > current


# ---------------------------------------------------------------------------
# Default callout rules
# ---------------------------------------------------------------------------


def _v1_condition(state: SimState, prev: SimState | None) -> bool:
    return _crossed_above(
        state.speeds.indicated_airspeed,
        prev.speeds.indicated_airspeed if prev else None,
        80.0,
    )


def _rotate_condition(state: SimState, prev: SimState | None) -> bool:
    return _crossed_above(
        state.speeds.indicated_airspeed,
        prev.speeds.indicated_airspeed if prev else None,
        85.0,
    )


def _positive_rate_condition(state: SimState, prev: SimState | None) -> bool:
    return state.speeds.vertical_speed > 100 and state.position.altitude_agl > 20


def _gear_up_condition(state: SimState, prev: SimState | None) -> bool:
    return state.speeds.vertical_speed > 300 and state.position.altitude_agl > 100


def _altitude_1000ft_condition(state: SimState, prev: SimState | None) -> bool:
    """Fires every 1000ft crossing during climb."""
    if prev is None:
        return False
    cur_thousands = int(state.position.altitude_msl / 1000)
    prev_thousands = int(prev.position.altitude_msl / 1000)
    return cur_thousands != prev_thousands and cur_thousands > prev_thousands


def _altitude_1000ft_message(state: SimState, _prev: SimState | None) -> str:
    alt = int(round(state.position.altitude_msl / 1000) * 1000)
    return f"Passing through {alt} feet"


def _level_off_condition(state: SimState, prev: SimState | None) -> bool:
    """Within 200ft of autopilot target altitude while climbing."""
    if not state.autopilot.master:
        return False
    target = state.autopilot.altitude
    if target <= 0:
        return False
    diff = abs(state.position.altitude_msl - target)
    return diff <= 200


def _approach_1000_condition(state: SimState, prev: SimState | None) -> bool:
    return (
        _crossed_below(
            state.position.altitude_agl,
            prev.position.altitude_agl if prev else None,
            1000.0,
        )
        and state.speeds.vertical_speed < 0
    )


def _approach_500_condition(state: SimState, prev: SimState | None) -> bool:
    return (
        _crossed_below(
            state.position.altitude_agl,
            prev.position.altitude_agl if prev else None,
            500.0,
        )
        and state.speeds.vertical_speed < 0
    )


def _minimums_condition(state: SimState, prev: SimState | None) -> bool:
    return (
        _crossed_below(
            state.position.altitude_agl,
            prev.position.altitude_agl if prev else None,
            200.0,
        )
        and state.speeds.vertical_speed < 0
    )


def _approach_100_condition(state: SimState, prev: SimState | None) -> bool:
    return (
        _crossed_below(
            state.position.altitude_agl,
            prev.position.altitude_agl if prev else None,
            100.0,
        )
        and state.speeds.vertical_speed < 0
    )


def _landing_50_condition(state: SimState, prev: SimState | None) -> bool:
    return _crossed_below(
        state.position.altitude_agl,
        prev.position.altitude_agl if prev else None,
        50.0,
    )


def _landing_30_condition(state: SimState, prev: SimState | None) -> bool:
    return _crossed_below(
        state.position.altitude_agl,
        prev.position.altitude_agl if prev else None,
        30.0,
    )


def _landing_10_condition(state: SimState, prev: SimState | None) -> bool:
    return _crossed_below(
        state.position.altitude_agl,
        prev.position.altitude_agl if prev else None,
        10.0,
    )


def _overspeed_condition(state: SimState, prev: SimState | None) -> bool:
    return state.speeds.indicated_airspeed > 250 and state.position.altitude_msl < 10000


def _bank_angle_condition(state: SimState, prev: SimState | None) -> bool:
    return abs(state.attitude.bank) > 45


def _sink_rate_condition(state: SimState, prev: SimState | None) -> bool:
    return state.speeds.vertical_speed < -2000 and state.position.altitude_agl < 2500


DEFAULT_CALLOUT_RULES: list[CalloutRule] = [
    # -- Takeoff phase --
    CalloutRule(
        name="V1",
        phase=FlightPhase.TAKEOFF,
        condition=_v1_condition,
        message="V1",
        priority=10,
    ),
    CalloutRule(
        name="ROTATE",
        phase=FlightPhase.TAKEOFF,
        condition=_rotate_condition,
        message="Rotate",
        priority=10,
    ),
    CalloutRule(
        name="POSITIVE_RATE",
        phase=FlightPhase.TAKEOFF,
        condition=_positive_rate_condition,
        message="Positive rate",
        priority=8,
    ),
    CalloutRule(
        name="GEAR_UP",
        phase=FlightPhase.TAKEOFF,
        condition=_gear_up_condition,
        message="Positive rate, gear up",
        priority=8,
    ),
    # -- Climb phase --
    CalloutRule(
        name="ALTITUDE_CALLOUT",
        phase=FlightPhase.CLIMB,
        condition=_altitude_1000ft_condition,
        message=_altitude_1000ft_message,
        one_shot=False,
        cooldown_secs=5.0,
    ),
    CalloutRule(
        name="LEVEL_OFF",
        phase=FlightPhase.CLIMB,
        condition=_level_off_condition,
        message="Approaching assigned altitude",
        priority=5,
    ),
    # -- Approach phase --
    CalloutRule(
        name="APPROACH_1000",
        phase=FlightPhase.APPROACH,
        condition=_approach_1000_condition,
        message="1000 feet",
        priority=7,
    ),
    CalloutRule(
        name="APPROACH_500",
        phase=FlightPhase.APPROACH,
        condition=_approach_500_condition,
        message="500 feet",
        priority=7,
    ),
    CalloutRule(
        name="MINIMUMS",
        phase=FlightPhase.APPROACH,
        condition=_minimums_condition,
        message="Minimums",
        priority=9,
    ),
    CalloutRule(
        name="APPROACH_100",
        phase=FlightPhase.APPROACH,
        condition=_approach_100_condition,
        message="100 feet",
        priority=8,
    ),
    # -- Landing phase --
    CalloutRule(
        name="LANDING_50",
        phase=FlightPhase.LANDING,
        condition=_landing_50_condition,
        message="50 feet",
        priority=8,
    ),
    CalloutRule(
        name="LANDING_30",
        phase=FlightPhase.LANDING,
        condition=_landing_30_condition,
        message="30 feet",
        priority=8,
    ),
    CalloutRule(
        name="LANDING_10",
        phase=FlightPhase.LANDING,
        condition=_landing_10_condition,
        message="10 feet",
        priority=8,
    ),
    # -- Any phase --
    CalloutRule(
        name="OVERSPEED",
        phase=None,
        condition=_overspeed_condition,
        message="Overspeed, overspeed",
        priority=10,
        one_shot=False,
        cooldown_secs=5.0,
    ),
    CalloutRule(
        name="BANK_ANGLE",
        phase=None,
        condition=_bank_angle_condition,
        message="Bank angle, bank angle",
        priority=10,
        one_shot=False,
        cooldown_secs=3.0,
    ),
    CalloutRule(
        name="SINK_RATE",
        phase=None,
        condition=_sink_rate_condition,
        message="Sink rate",
        priority=10,
        one_shot=False,
        cooldown_secs=3.0,
    ),
]


# ---------------------------------------------------------------------------
# Callout engine
# ---------------------------------------------------------------------------


class CalloutEngine:
    """Evaluates callout rules against telemetry and returns triggered callouts.

    Usage::

        engine = CalloutEngine()
        callouts = engine.update(current_state, previous_state)
        for c in callouts:
            speak(c.message)
    """

    def __init__(self, rules: list[CalloutRule] | None = None) -> None:
        self._rules: list[CalloutRule] = rules if rules is not None else list(DEFAULT_CALLOUT_RULES)
        self._triggered: set[str] = set()
        self._last_triggered: dict[str, float] = {}
        self._current_phase: FlightPhase = FlightPhase.PREFLIGHT

    @property
    def current_phase(self) -> FlightPhase:
        return self._current_phase

    @property
    def triggered_names(self) -> set[str]:
        """Names of callouts already triggered (useful for testing)."""
        return set(self._triggered)

    def on_phase_change(self, new_phase: FlightPhase) -> None:
        """Reset one-shot triggers when the flight phase changes."""
        if new_phase != self._current_phase:
            logger.info(
                "CalloutEngine phase change: %s -> %s",
                self._current_phase.value,
                new_phase.value,
            )
            self._current_phase = new_phase
            # Clear one-shot tracking so rules can fire again in the new phase
            self._triggered.clear()

    def update(
        self,
        state: SimState,
        prev_state: SimState | None = None,
    ) -> list[Callout]:
        """Evaluate all rules against current telemetry. Returns triggered callouts."""
        now = time.monotonic()
        results: list[Callout] = []

        for rule in self._rules:
            # Phase filter: None means any phase
            if rule.phase is not None and rule.phase != self._current_phase:
                continue

            # One-shot guard
            if rule.one_shot and rule.name in self._triggered:
                continue

            # Cooldown guard
            if rule.cooldown_secs > 0:
                last = self._last_triggered.get(rule.name, 0.0)
                if (now - last) < rule.cooldown_secs:
                    continue

            # Evaluate condition
            try:
                if not rule.condition(state, prev_state):
                    continue
            except Exception:
                logger.exception("Error evaluating callout rule %s", rule.name)
                continue

            # Build message
            if callable(rule.message) and not isinstance(rule.message, str):
                message = rule.message(state, prev_state)
            else:
                message = rule.message

            # Record trigger
            self._triggered.add(rule.name)
            self._last_triggered[rule.name] = now

            results.append(
                Callout(
                    name=rule.name,
                    message=message,
                    priority=rule.priority,
                    triggered=True,
                )
            )
            logger.info("Callout triggered: %s - %s", rule.name, message)

        # Sort by priority descending
        results.sort(key=lambda c: c.priority, reverse=True)
        return results
