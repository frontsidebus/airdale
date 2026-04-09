"""Monitors telemetry for deviations from expected parameters and generates alerts.

The DeviationMonitor checks a configurable set of rules against the current
SimState each update cycle.  Rules are phase-aware (only fire in relevant
flight phases) and cooldown-gated (won't nag within a configurable window).
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass

from .sim_client import FlightPhase, SimState

# ---------------------------------------------------------------------------
# Alert / Rule data classes
# ---------------------------------------------------------------------------


@dataclass
class DeviationAlert:
    """A single deviation detected by a rule."""

    name: str  # e.g., "altitude_bust", "speed_deviation"
    message: str  # What MERLIN says
    severity: str  # "caution" or "warning"
    value: float  # Current value
    expected: float  # Expected value
    deviation: float  # How far off


@dataclass
class DeviationRule:
    """A rule that checks one aspect of the sim state."""

    name: str
    check: Callable[[SimState], DeviationAlert | None]
    phases: set[FlightPhase]  # Which phases to check
    cooldown_secs: float = 30.0  # Don't repeat too often


# ---------------------------------------------------------------------------
# Individual rule check functions
# ---------------------------------------------------------------------------

ALL_AIRBORNE_PHASES: set[FlightPhase] = {
    FlightPhase.TAKEOFF,
    FlightPhase.CLIMB,
    FlightPhase.CRUISE,
    FlightPhase.DESCENT,
    FlightPhase.APPROACH,
    FlightPhase.LANDING,
}

ALL_PHASES: set[FlightPhase] = set(FlightPhase)


def _check_speed_high_approach(state: SimState) -> DeviationAlert | None:
    ias = state.speeds.indicated_airspeed
    if ias > 160:
        return DeviationAlert(
            name="speed_high_approach",
            message=f"Speed. You're {ias:.0f} knots, that's fast for approach",
            severity="caution",
            value=ias,
            expected=160.0,
            deviation=ias - 160.0,
        )
    return None


def _check_speed_low_approach(state: SimState) -> DeviationAlert | None:
    ias = state.speeds.indicated_airspeed
    if ias < 60:
        return DeviationAlert(
            name="speed_low_approach",
            message=f"Airspeed low. {ias:.0f} knots",
            severity="warning",
            value=ias,
            expected=60.0,
            deviation=60.0 - ias,
        )
    return None


def _check_overspeed_below_10k(state: SimState) -> DeviationAlert | None:
    ias = state.speeds.indicated_airspeed
    alt_msl = state.position.altitude_msl
    if ias > 250 and alt_msl < 10_000:
        return DeviationAlert(
            name="overspeed_below_10k",
            message="Overspeed below ten thousand",
            severity="warning",
            value=ias,
            expected=250.0,
            deviation=ias - 250.0,
        )
    return None


def _check_stall_warning(state: SimState) -> DeviationAlert | None:
    ias = state.speeds.indicated_airspeed
    if ias < 55 and not state.on_ground:
        return DeviationAlert(
            name="stall_warning",
            message=f"Stall warning, stall warning. Airspeed {ias:.0f} knots",
            severity="warning",
            value=ias,
            expected=55.0,
            deviation=55.0 - ias,
        )
    return None


def _check_altitude_bust(state: SimState) -> DeviationAlert | None:
    if not state.autopilot.master:
        return None
    diff = abs(state.position.altitude_msl - state.autopilot.altitude)
    if diff > 200:
        return DeviationAlert(
            name="altitude_bust",
            message=f"Altitude deviation. {diff:.0f} feet from assigned altitude",
            severity="caution",
            value=state.position.altitude_msl,
            expected=state.autopilot.altitude,
            deviation=diff,
        )
    return None


def _check_too_low_terrain(state: SimState) -> DeviationAlert | None:
    agl = state.position.altitude_agl
    if agl < 500:
        return DeviationAlert(
            name="too_low_terrain",
            message=f"Low altitude. {agl:.0f} feet AGL",
            severity="warning",
            value=agl,
            expected=500.0,
            deviation=500.0 - agl,
        )
    return None


def _check_gear_not_down_low(state: SimState) -> DeviationAlert | None:
    agl = state.position.altitude_agl
    if agl < 500 and not state.surfaces.gear_handle:
        return DeviationAlert(
            name="gear_not_down_low",
            message="Gear. Check gear down",
            severity="warning",
            value=agl,
            expected=500.0,
            deviation=500.0 - agl,
        )
    return None


def _check_flaps_not_set_approach(state: SimState) -> DeviationAlert | None:
    agl = state.position.altitude_agl
    flaps = state.surfaces.flaps_percent
    if agl < 1000 and flaps < 10:
        return DeviationAlert(
            name="flaps_not_set_approach",
            message="Flaps. Check flap setting",
            severity="caution",
            value=flaps,
            expected=10.0,
            deviation=10.0 - flaps,
        )
    return None


def _check_no_ap_high_workload(state: SimState) -> DeviationAlert | None:
    agl = state.position.altitude_agl
    if not state.autopilot.master and agl < 1000:
        return DeviationAlert(
            name="no_ap_high_workload",
            message="No autopilot. Consider engaging autopilot for approach",
            severity="caution",
            value=0.0,
            expected=1.0,
            deviation=1.0,
        )
    return None


def _check_excessive_bank(state: SimState) -> DeviationAlert | None:
    bank = abs(state.attitude.bank)
    if bank > 30:
        return DeviationAlert(
            name="excessive_bank",
            message="Bank angle",
            severity="warning",
            value=state.attitude.bank,
            expected=30.0,
            deviation=bank - 30.0,
        )
    return None


def _check_excessive_pitch_up(state: SimState) -> DeviationAlert | None:
    pitch = state.attitude.pitch
    if pitch > 15:
        return DeviationAlert(
            name="excessive_pitch_up",
            message="Pitch attitude",
            severity="caution",
            value=pitch,
            expected=15.0,
            deviation=pitch - 15.0,
        )
    return None


def _check_excessive_pitch_down(state: SimState) -> DeviationAlert | None:
    pitch = state.attitude.pitch
    if pitch < -10:
        return DeviationAlert(
            name="excessive_pitch_down",
            message="Pitch. Nose low",
            severity="warning",
            value=pitch,
            expected=-10.0,
            deviation=abs(pitch) - 10.0,
        )
    return None


# ---------------------------------------------------------------------------
# Default rule set
# ---------------------------------------------------------------------------

DEFAULT_DEVIATION_RULES: list[DeviationRule] = [
    # Speed deviations
    DeviationRule(
        name="speed_high_approach",
        check=_check_speed_high_approach,
        phases={FlightPhase.APPROACH},
    ),
    DeviationRule(
        name="speed_low_approach",
        check=_check_speed_low_approach,
        phases={FlightPhase.APPROACH},
    ),
    DeviationRule(
        name="overspeed_below_10k",
        check=_check_overspeed_below_10k,
        phases=ALL_AIRBORNE_PHASES,
    ),
    DeviationRule(
        name="stall_warning",
        check=_check_stall_warning,
        phases=ALL_AIRBORNE_PHASES,
    ),
    # Altitude deviations
    DeviationRule(
        name="altitude_bust",
        check=_check_altitude_bust,
        phases={FlightPhase.CLIMB, FlightPhase.CRUISE, FlightPhase.DESCENT},
    ),
    DeviationRule(
        name="too_low_terrain",
        check=_check_too_low_terrain,
        phases={FlightPhase.CRUISE, FlightPhase.CLIMB},
    ),
    # Configuration deviations
    DeviationRule(
        name="gear_not_down_low",
        check=_check_gear_not_down_low,
        phases={FlightPhase.APPROACH},
    ),
    DeviationRule(
        name="flaps_not_set_approach",
        check=_check_flaps_not_set_approach,
        phases={FlightPhase.APPROACH},
    ),
    DeviationRule(
        name="no_ap_high_workload",
        check=_check_no_ap_high_workload,
        phases={FlightPhase.APPROACH},
    ),
    # Attitude deviations
    DeviationRule(
        name="excessive_bank",
        check=_check_excessive_bank,
        phases={FlightPhase.APPROACH, FlightPhase.LANDING},
    ),
    DeviationRule(
        name="excessive_pitch_up",
        check=_check_excessive_pitch_up,
        phases=ALL_PHASES - {FlightPhase.TAKEOFF},
    ),
    DeviationRule(
        name="excessive_pitch_down",
        check=_check_excessive_pitch_down,
        phases=ALL_PHASES,
    ),
]


# ---------------------------------------------------------------------------
# Monitor
# ---------------------------------------------------------------------------


class DeviationMonitor:
    """Checks deviation rules against the current sim state.

    Rules are only evaluated when the current flight phase matches the rule's
    phase set.  A per-rule cooldown prevents repeated alerts within a
    configurable window (default 30 s).
    """

    def __init__(
        self,
        rules: list[DeviationRule] | None = None,
        time_fn: Callable[[], float] | None = None,
    ) -> None:
        self._rules: list[DeviationRule] = (
            rules if rules is not None else list(DEFAULT_DEVIATION_RULES)
        )
        self._last_alerted: dict[str, float] = {}
        self._time_fn = time_fn or time.monotonic

    def check(self, state: SimState) -> list[DeviationAlert]:
        """Check all deviation rules against current state.

        Returns a list of alerts for rules that fired and are not in cooldown.
        """
        now = self._time_fn()
        alerts: list[DeviationAlert] = []

        for rule in self._rules:
            # Phase gate
            if state.flight_phase not in rule.phases:
                continue

            # Cooldown gate
            last = self._last_alerted.get(rule.name)
            if last is not None and (now - last) < rule.cooldown_secs:
                continue

            alert = rule.check(state)
            if alert is not None:
                self._last_alerted[rule.name] = now
                alerts.append(alert)

        return alerts

    def reset(self) -> None:
        """Clear all cooldown timers."""
        self._last_alerted.clear()
