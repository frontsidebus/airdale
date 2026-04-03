"""Emergency detection and fast-path response system.

Monitors telemetry for emergency conditions and provides immediate,
pre-validated responses that bypass LLM inference for time-critical
situations. Each emergency includes immediate actions, a follow-up
checklist, and a flag to also engage Claude for situational reasoning.

Usage:
    detector = EmergencyDetector()
    result = detector.evaluate(previous_state, current_state)
    if result:
        # Serve result.response immediately via TTS
        # Also send to Claude with result.context for reasoning
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from .sim_client import FlightPhase, SimState

logger = logging.getLogger(__name__)


class EmergencyType(StrEnum):
    ENGINE_FAILURE_TAKEOFF = "ENGINE_FAILURE_TAKEOFF"
    ENGINE_FAILURE_CRUISE = "ENGINE_FAILURE_CRUISE"
    ENGINE_FIRE = "ENGINE_FIRE"
    ELECTRICAL_FIRE = "ELECTRICAL_FIRE"
    RAPID_DECOMPRESSION = "RAPID_DECOMPRESSION"


@dataclass
class EmergencyThresholds:
    """Configurable thresholds for emergency detection."""

    engine_rpm_min: float = 100.0  # RPM below this = engine dead
    egt_fire_threshold: float = 1500.0  # EGT above this = possible fire
    oil_pressure_min: float = 10.0  # psi — low oil pressure
    cabin_alt_max: float = 10000.0  # feet — rapid decompression threshold
    min_detection_duration: float = 0.5  # seconds to confirm (debounce)


@dataclass
class EmergencyResponse:
    """A pre-validated emergency response ready for immediate delivery."""

    emergency_type: EmergencyType
    title: str
    immediate_actions: list[str]
    followup_checklist: list[str]
    assessment_template: str
    squawk: str = "7700"
    send_to_llm: bool = True  # Also engage Claude for situational reasoning
    detected_at: float = 0.0

    @property
    def spoken_response(self) -> str:
        """Format as speakable text for immediate TTS delivery."""
        lines = [f"{self.title}."]
        for i, action in enumerate(self.immediate_actions, 1):
            lines.append(f"Step {i}: {action}.")
        return " ".join(lines)

    @property
    def full_response(self) -> str:
        """Full formatted response including checklist."""
        lines = [self.title, ""]
        for i, action in enumerate(self.immediate_actions, 1):
            lines.append(f"Step {i}: {action}")
        if self.followup_checklist:
            lines.append("")
            lines.append("Follow-up:")
            for item in self.followup_checklist:
                lines.append(f"  - {item}")
        return "\n".join(lines)

    def build_context(self, state: SimState) -> dict[str, Any]:
        """Build context dict for injection into Claude's system prompt."""
        return {
            "emergency_type": self.emergency_type.value,
            "emergency_start_time": self.detected_at,
            "emergency_start_altitude": state.position.altitude_msl,
            "emergency_start_airspeed": state.speeds.indicated_airspeed,
            "immediate_actions_given": self.immediate_actions,
            "squawk": self.squawk,
        }


# ---------------------------------------------------------------------------
# Pre-validated emergency procedures
# ---------------------------------------------------------------------------

_EMERGENCY_PROCEDURES: dict[EmergencyType, dict[str, Any]] = {
    EmergencyType.ENGINE_FAILURE_TAKEOFF: {
        "title": "ENGINE FAILURE — loss of power during takeoff",
        "immediate_actions": [
            "Maintain wings level, do not turn back to the runway",
            "Pitch for best glide speed",
            "Identify a landing site ahead, within 30 degrees of current heading",
        ],
        "followup_checklist": [
            "Fuel selector — check ON / switch tanks",
            "Mixture — RICH",
            "Magnetos — check BOTH",
            "Carburetor heat — ON",
            "Primer — IN and LOCKED",
            "If no restart: forced landing checklist",
            "Squawk 7700",
            "Mayday call if able",
        ],
        "assessment_template": (
            "Engine failure detected during takeoff phase. "
            "Altitude {alt:.0f} feet AGL, airspeed {ias:.0f} knots."
        ),
    },
    EmergencyType.ENGINE_FAILURE_CRUISE: {
        "title": "ENGINE FAILURE — loss of power in flight",
        "immediate_actions": [
            "Pitch for best glide speed immediately",
            "Trim for glide",
            "Attempt engine restart: fuel, mixture, mags, carburetor heat",
        ],
        "followup_checklist": [
            "Fuel selector — switch tanks",
            "Mixture — RICH",
            "Magnetos — cycle BOTH / LEFT / RIGHT / BOTH",
            "Carburetor heat — ON",
            "Primer — IN and LOCKED",
            "If no restart: plan forced landing",
            "Squawk 7700",
            "Mayday call with position and intentions",
        ],
        "assessment_template": (
            "Engine failure detected in cruise. "
            "Altitude {alt:.0f} feet MSL, airspeed {ias:.0f} knots. "
            "Identifying nearest suitable runway."
        ),
    },
    EmergencyType.ENGINE_FIRE: {
        "title": "ENGINE FIRE — fire indication on engine",
        "immediate_actions": [
            "Mixture — IDLE CUTOFF",
            "Fuel selector — OFF",
            "Master switch for affected engine — OFF",
        ],
        "followup_checklist": [
            "Cabin heat and air — OFF",
            "Airspeed — increase to help extinguish",
            "If fire persists: execute forced landing immediately",
            "Squawk 7700",
            "Mayday call",
        ],
        "assessment_template": (
            "Engine fire indication detected. EGT {egt:.0f} degrees. "
            "Altitude {alt:.0f} feet, airspeed {ias:.0f} knots."
        ),
    },
    EmergencyType.ELECTRICAL_FIRE: {
        "title": "ELECTRICAL FIRE — smoke or electrical burning detected",
        "immediate_actions": [
            "Master switch — OFF",
            "All electrical switches — OFF",
            "Vents — OPEN to clear smoke",
        ],
        "followup_checklist": [
            "If fire extinguishes: master ON",
            "Switches on one at a time to isolate faulty circuit",
            "Land as soon as practicable",
            "Squawk 7700",
        ],
        "assessment_template": (
            "Electrical anomaly detected. Altitude {alt:.0f} feet, airspeed {ias:.0f} knots."
        ),
    },
    EmergencyType.RAPID_DECOMPRESSION: {
        "title": "RAPID DECOMPRESSION — loss of cabin pressure",
        "immediate_actions": [
            "Oxygen masks — ON, both crew",
            "Thrust — IDLE",
            "Speedbrake — EXTEND",
        ],
        "followup_checklist": [
            "Bank 45 degrees or as required for terrain",
            "Emergency descent to 10,000 feet or MEA, whichever is higher",
            "Squawk 7700",
            "Declare emergency with ATC",
            "Level off at safe altitude",
            "Assess damage and plan diversion",
        ],
        "assessment_template": (
            "Rapid decompression detected. Cabin altitude exceeding limits. "
            "Current altitude {alt:.0f} feet. Initiating emergency descent."
        ),
    },
}


def build_emergency_response(
    etype: EmergencyType,
    state: SimState,
) -> EmergencyResponse:
    """Build a pre-validated emergency response from the procedure database."""
    proc = _EMERGENCY_PROCEDURES[etype]
    assessment = proc["assessment_template"].format(
        alt=state.position.altitude_msl,
        ias=state.speeds.indicated_airspeed,
        egt=max((e.egt for e in state.engines.active_engines), default=0),
    )
    return EmergencyResponse(
        emergency_type=etype,
        title=proc["title"],
        immediate_actions=proc["immediate_actions"],
        followup_checklist=proc["followup_checklist"],
        assessment_template=assessment,
        detected_at=time.monotonic(),
    )


# ---------------------------------------------------------------------------
# Emergency detector
# ---------------------------------------------------------------------------


class EmergencyDetector:
    """Monitors telemetry state transitions for emergency conditions.

    Compares consecutive SimState snapshots to detect sudden failures.
    Uses debouncing to avoid false positives from telemetry glitches.
    """

    def __init__(self, thresholds: EmergencyThresholds | None = None) -> None:
        self._thresholds = thresholds or EmergencyThresholds()
        self._active_emergency: EmergencyType | None = None
        self._candidate: EmergencyType | None = None
        self._candidate_since: float = 0.0

    @property
    def active_emergency(self) -> EmergencyType | None:
        return self._active_emergency

    def clear(self) -> None:
        """Clear the active emergency (e.g., after landing)."""
        self._active_emergency = None
        self._candidate = None

    def evaluate(
        self,
        prev_state: SimState,
        curr_state: SimState,
    ) -> EmergencyResponse | None:
        """Evaluate telemetry for emergency conditions.

        Returns an EmergencyResponse if a new emergency is confirmed,
        None otherwise.
        """
        if self._active_emergency is not None:
            return None  # Already handling an emergency

        detected = self._detect(prev_state, curr_state)
        if detected is None:
            self._candidate = None
            return None

        etype, triggered, _context = detected
        if not triggered:
            self._candidate = None
            return None

        now = time.monotonic()

        # Debounce: require sustained detection
        if etype != self._candidate:
            self._candidate = etype
            self._candidate_since = now
            # If no debounce delay, confirm immediately
            if self._thresholds.min_detection_duration <= 0:
                pass  # Fall through to confirmation
            else:
                return None
        else:
            elapsed = now - self._candidate_since
            if elapsed < self._thresholds.min_detection_duration:
                return None

        # Confirmed emergency
        self._active_emergency = etype
        self._candidate = None
        logger.critical("EMERGENCY DETECTED: %s", etype.value)
        return build_emergency_response(etype, curr_state)

    def _detect(
        self,
        prev: SimState,
        curr: SimState,
    ) -> tuple[EmergencyType, bool, dict[str, Any]] | None:
        """Check all emergency conditions against telemetry delta."""
        t = self._thresholds
        phase = curr.flight_phase

        # --- Engine failure during takeoff ---
        if phase in (FlightPhase.TAKEOFF, FlightPhase.CLIMB):
            result = self._check_engine_failure(prev, curr, t)
            if result:
                return EmergencyType.ENGINE_FAILURE_TAKEOFF, True, result

        # --- Engine failure in cruise/descent ---
        if phase in (FlightPhase.CRUISE, FlightPhase.DESCENT, FlightPhase.APPROACH):
            result = self._check_engine_failure(prev, curr, t)
            if result:
                return EmergencyType.ENGINE_FAILURE_CRUISE, True, result

        # --- Engine fire (any phase) ---
        for engine in curr.engines.active_engines:
            if engine.egt > t.egt_fire_threshold and engine.rpm > t.engine_rpm_min:
                return EmergencyType.ENGINE_FIRE, True, {"egt": engine.egt}

        return None

    def _check_engine_failure(
        self,
        prev: SimState,
        curr: SimState,
        t: EmergencyThresholds,
    ) -> dict[str, Any] | None:
        """Detect engine failure: RPM drops from healthy to below threshold."""
        prev_engines = prev.engines.active_engines
        curr_engines = curr.engines.active_engines

        if not prev_engines or not curr_engines:
            return None

        # Use strict=False: engine counts can differ briefly during sim loading
        for i, (prev_eng, curr_eng) in enumerate(zip(prev_engines, curr_engines, strict=False)):
            if prev_eng.rpm > t.engine_rpm_min and curr_eng.rpm <= t.engine_rpm_min:
                return {"engine_index": i, "prev_rpm": prev_eng.rpm, "curr_rpm": curr_eng.rpm}
        return None
