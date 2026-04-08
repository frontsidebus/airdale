"""Tracks recent aircraft control commands and generates undo actions."""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any

from .sim_client import SimState

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Toggle commands — undo by re-issuing the same command
# ---------------------------------------------------------------------------

_TOGGLE_COMMANDS: set[str] = {
    "GEAR_TOGGLE",
    "LANDING_LIGHTS_TOGGLE",
    "TOGGLE_TAXI_LIGHTS",
    "TOGGLE_NAV_LIGHTS",
    "TOGGLE_BEACON_LIGHTS",
    "STROBES_TOGGLE",
    "PANEL_LIGHTS_TOGGLE",
    "PITOT_HEAT_TOGGLE",
    "TOGGLE_STRUCTURAL_DEICE",
    "WINDSHIELD_DEICE_TOGGLE",
    "TOGGLE_PROPELLER_DEICE",
    "ANTI_ICE_CARB_HEAT_TOGGLE",
    "FUEL_PUMP_TOGGLE",
    "SPOILERS_TOGGLE",
    "CROSS_FEED_TOGGLE",
    "PARKING_BRAKES",
}

# ---------------------------------------------------------------------------
# Explicit inverse pairs — undo by issuing the opposite command
# ---------------------------------------------------------------------------

_INVERSE_PAIRS: dict[str, tuple[str, str, str]] = {
    # command -> (system, action, description)
    "GEAR_DOWN": ("gear", "up", "Gear up"),
    "GEAR_UP": ("gear", "down", "Gear down"),
    "CROSS_FEED_OPEN": ("crossfeed", "close", "Crossfeed closed"),
    "CROSS_FEED_OFF": ("crossfeed", "open", "Crossfeed open"),
}

# ---------------------------------------------------------------------------
# Commands that restore a previous value from state snapshot
# ---------------------------------------------------------------------------

_STATE_RESTORE_COMMANDS: dict[str, tuple[str, str, str]] = {
    # command -> (system, action, state_field_path)
    "FLAPS_SET": ("flaps", "set", "surfaces.flaps_percent"),
    "HEADING_BUG_SET": ("autopilot", "heading", "autopilot.heading"),
    "AP_ALT_VAR_SET_ENGLISH": ("autopilot", "altitude", "autopilot.altitude"),
    "AP_VS_VAR_SET_ENGLISH": ("autopilot", "vertical_speed", "autopilot.vertical_speed"),
    "AP_SPD_VAR_SET": ("autopilot", "speed", "autopilot.airspeed"),
    "THROTTLE_SET": ("throttle", "set", ""),
    "SPOILERS_SET": ("spoilers", "set", "surfaces.spoilers_percent"),
    "ELEVATOR_TRIM_SET": ("trim", "set", ""),
    "KOHLSMAN_SET": ("barometer", "set", "environment.barometer_inhg"),
}

# ---------------------------------------------------------------------------
# Non-reversible commands
# ---------------------------------------------------------------------------

_NON_REVERSIBLE: set[str] = {
    "TOGGLE_STARTER1",
    "TOGGLE_PRIMER",
    "FLAPS_1",
    "FLAPS_2",
    "FLAPS_3",
    "FLAPS_INCR",
    "FLAPS_DECR",
    "ELEV_TRIM_UP",
    "ELEV_TRIM_DN",
    "RUDDER_TRIM_LEFT",
    "RUDDER_TRIM_RIGHT",
    "AILERON_TRIM_LEFT",
    "AILERON_TRIM_RIGHT",
}


def _get_nested_attr(obj: Any, path: str) -> Any:
    """Resolve a dotted attribute path on an object."""
    for part in path.split("."):
        obj = getattr(obj, part)
    return obj


@dataclass
class CommandRecord:
    """A single command execution with pre-state snapshot."""

    command: str
    value: int
    system: str
    action: str
    timestamp: float
    sim_state_before: dict[str, Any] = field(default_factory=dict)


class CommandHistory:
    """Tracks recent commands and generates undo actions.

    Maintains a bounded ring buffer of recent commands. Each record captures
    the SimConnect event name, the human-friendly system/action, and a snapshot
    of relevant sim state *before* the command was executed so we can restore
    previous values.
    """

    def __init__(self, max_history: int = 20) -> None:
        self._history: list[CommandRecord] = []
        self._max_history = max_history

    def record(
        self,
        command: str,
        value: int,
        system: str,
        action: str,
        state_before: SimState,
    ) -> None:
        """Record a command execution with pre-state snapshot."""
        snapshot = _extract_relevant_state(command, state_before)
        record = CommandRecord(
            command=command,
            value=value,
            system=system,
            action=action,
            timestamp=time.monotonic(),
            sim_state_before=snapshot,
        )
        self._history.append(record)
        if len(self._history) > self._max_history:
            self._history = self._history[-self._max_history :]
        logger.debug("Recorded command: %s (value=%d)", command, value)

    def get_undo_action(self) -> tuple[str, str, float | None] | None:
        """Return (system, action, value) to reverse the last command, or None.

        Returns None if there is nothing to undo or the last command is not
        reversible.
        """
        if not self._history:
            return None

        last = self._history[-1]
        cmd = last.command

        # 1. Explicit inverse pairs (gear up/down, crossfeed open/close)
        if cmd in _INVERSE_PAIRS:
            system, action, _desc = _INVERSE_PAIRS[cmd]
            return system, action, None

        # 2. Toggle commands — re-issue the same command
        if cmd in _TOGGLE_COMMANDS:
            return last.system, last.action, None

        # 3. AP_MASTER — toggle back (it's always a toggle in SimConnect)
        if cmd == "AP_MASTER":
            ap_was_on = last.sim_state_before.get("autopilot_master", False)
            if ap_was_on:
                return "autopilot", "on", None
            return "autopilot", "off", None

        # 4. Value-restore commands (flaps, heading, altitude, etc.)
        if cmd in _STATE_RESTORE_COMMANDS:
            system, action, state_path = _STATE_RESTORE_COMMANDS[cmd]
            prev_value = last.sim_state_before.get(state_path)
            if prev_value is not None:
                return system, action, float(prev_value)
            return None

        # 5. Non-reversible commands
        if cmd in _NON_REVERSIBLE:
            return None

        # 6. Unknown command — not reversible
        logger.debug("No undo mapping for command: %s", cmd)
        return None

    def pop_last(self) -> CommandRecord | None:
        """Remove and return the last command record, or None if empty."""
        if self._history:
            return self._history.pop()
        return None

    def get_recent(self, n: int = 5) -> list[CommandRecord]:
        """Return the N most recent commands, newest first."""
        return list(reversed(self._history[-n:]))

    def clear(self) -> None:
        """Clear all command history."""
        self._history.clear()

    @property
    def last_command(self) -> CommandRecord | None:
        """The most recently recorded command, or None."""
        return self._history[-1] if self._history else None

    def __len__(self) -> int:
        return len(self._history)


def _extract_relevant_state(command: str, state: SimState) -> dict[str, Any]:
    """Extract the subset of state needed to undo a specific command."""
    snapshot: dict[str, Any] = {}

    if command == "AP_MASTER":
        snapshot["autopilot_master"] = state.autopilot.master

    if command in _STATE_RESTORE_COMMANDS:
        _sys, _act, state_path = _STATE_RESTORE_COMMANDS[command]
        if state_path:
            try:
                snapshot[state_path] = _get_nested_attr(state, state_path)
            except AttributeError:
                logger.debug("Could not extract state path %s for undo", state_path)

    return snapshot
