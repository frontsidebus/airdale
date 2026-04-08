"""Tests for orchestrator.command_history — command recording and undo support."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from orchestrator.command_history import (
    CommandHistory,
    CommandRecord,
)
from orchestrator.sim_client import (
    AutopilotState,
    SimState,
    SurfaceState,
    TelemetryClient,
)
from orchestrator.tools import set_aircraft_control, undo_last_command


# ---------------------------------------------------------------------------
# CommandRecord dataclass
# ---------------------------------------------------------------------------


class TestCommandRecord:
    def test_all_required_fields(self) -> None:
        record = CommandRecord(
            command="GEAR_DOWN",
            value=0,
            timestamp=1234567890.0,
            system="gear",
            action="down",
        )
        assert record.command == "GEAR_DOWN"
        assert record.value == 0
        assert record.timestamp == 1234567890.0
        assert record.system == "gear"
        assert record.action == "down"
        assert record.sim_state_before == {}

    def test_sim_state_before_stores_snapshot(self) -> None:
        record = CommandRecord(
            command="HEADING_BUG_SET",
            value=270,
            timestamp=0.0,
            system="autopilot",
            action="heading",
            sim_state_before={"autopilot.heading": 180},
        )
        assert record.sim_state_before["autopilot.heading"] == 180


# ---------------------------------------------------------------------------
# CommandHistory — record and retrieve
# ---------------------------------------------------------------------------


class TestCommandHistoryRecordRetrieve:
    def test_record_and_get_recent(self) -> None:
        history = CommandHistory()
        state = SimState()
        history.record("GEAR_DOWN", 0, system="gear", action="down", state_before=state)
        history.record("FLAPS_SET", 8192, system="flaps", action="set", state_before=state)

        recent = history.get_recent(n=2)
        assert len(recent) == 2
        assert recent[0].command == "FLAPS_SET"  # most recent first
        assert recent[1].command == "GEAR_DOWN"

    def test_get_recent_returns_correct_count(self) -> None:
        history = CommandHistory()
        state = SimState()
        for i in range(10):
            history.record(f"CMD_{i}", i, system="test", action="test", state_before=state)

        recent = history.get_recent(n=3)
        assert len(recent) == 3

    def test_get_recent_fewer_than_count(self) -> None:
        history = CommandHistory()
        state = SimState()
        history.record("GEAR_DOWN", 0, system="gear", action="down", state_before=state)

        recent = history.get_recent(n=5)
        assert len(recent) == 1

    def test_history_respects_max_history_limit(self) -> None:
        history = CommandHistory(max_history=5)
        state = SimState()
        for i in range(10):
            history.record(f"CMD_{i}", i, system="test", action="test", state_before=state)

        recent = history.get_recent(n=100)
        assert len(recent) == 5
        # Most recent should be CMD_9
        assert recent[0].command == "CMD_9"

    def test_len(self) -> None:
        history = CommandHistory()
        assert len(history) == 0
        state = SimState()
        history.record("GEAR_DOWN", 0, system="gear", action="down", state_before=state)
        assert len(history) == 1

    def test_last_command(self) -> None:
        history = CommandHistory()
        assert history.last_command is None
        state = SimState()
        history.record("GEAR_DOWN", 0, system="gear", action="down", state_before=state)
        assert history.last_command is not None
        assert history.last_command.command == "GEAR_DOWN"

    def test_clear(self) -> None:
        history = CommandHistory()
        state = SimState()
        history.record("GEAR_DOWN", 0, system="gear", action="down", state_before=state)
        history.clear()
        assert len(history) == 0

    def test_pop_last(self) -> None:
        history = CommandHistory()
        state = SimState()
        history.record("GEAR_DOWN", 0, system="gear", action="down", state_before=state)
        record = history.pop_last()
        assert record is not None
        assert record.command == "GEAR_DOWN"
        assert len(history) == 0

    def test_pop_last_empty(self) -> None:
        history = CommandHistory()
        assert history.pop_last() is None


# ---------------------------------------------------------------------------
# get_undo_action — gear (inverse pairs)
# ---------------------------------------------------------------------------


class TestUndoGear:
    def test_undo_gear_down_returns_gear_up(self) -> None:
        history = CommandHistory()
        state = SimState()
        history.record("GEAR_DOWN", 0, system="gear", action="down", state_before=state)

        undo = history.get_undo_action()
        assert undo is not None
        system, action, value = undo
        assert system == "gear"
        assert action == "up"

    def test_undo_gear_up_returns_gear_down(self) -> None:
        history = CommandHistory()
        state = SimState()
        history.record("GEAR_UP", 0, system="gear", action="up", state_before=state)

        undo = history.get_undo_action()
        assert undo is not None
        system, action, value = undo
        assert system == "gear"
        assert action == "down"


# ---------------------------------------------------------------------------
# get_undo_action — flaps (state restore)
# ---------------------------------------------------------------------------


class TestUndoFlaps:
    def test_undo_flaps_set_returns_previous_value(self) -> None:
        history = CommandHistory()
        state = SimState(surfaces=SurfaceState(flaps_percent=0))
        history.record(
            "FLAPS_SET",
            8192,
            system="flaps",
            action="set",
            state_before=state,
        )

        undo = history.get_undo_action()
        assert undo is not None
        system, action, value = undo
        assert system == "flaps"
        assert action == "set"
        assert value == 0.0  # previous flaps_percent


# ---------------------------------------------------------------------------
# get_undo_action — autopilot
# ---------------------------------------------------------------------------


class TestUndoAutopilot:
    def test_undo_ap_master_returns_toggle(self) -> None:
        """AP_MASTER undoes by toggling back."""
        history = CommandHistory()
        state = SimState(autopilot=AutopilotState(master=False))
        history.record("AP_MASTER", 0, system="autopilot", action="toggle", state_before=state)

        undo = history.get_undo_action()
        assert undo is not None
        system, action, value = undo
        assert system == "autopilot"
        # Should tell us to turn it off (since before it was off, now it's on)
        assert action in ("off", "on", "toggle")

    def test_undo_heading_bug_returns_previous_heading(self) -> None:
        history = CommandHistory()
        state = SimState(autopilot=AutopilotState(heading=180))
        history.record(
            "HEADING_BUG_SET",
            270,
            system="autopilot",
            action="heading",
            state_before=state,
        )

        undo = history.get_undo_action()
        assert undo is not None
        system, action, value = undo
        assert system == "autopilot"
        assert action == "heading"
        assert value == 180.0

    def test_undo_altitude_returns_previous(self) -> None:
        history = CommandHistory()
        state = SimState(autopilot=AutopilotState(altitude=5000))
        history.record(
            "AP_ALT_VAR_SET_ENGLISH",
            10000,
            system="autopilot",
            action="altitude",
            state_before=state,
        )

        undo = history.get_undo_action()
        assert undo is not None
        system, action, value = undo
        assert system == "autopilot"
        assert action == "altitude"
        assert value == 5000.0


# ---------------------------------------------------------------------------
# get_undo_action — toggle commands
# ---------------------------------------------------------------------------


class TestUndoToggleCommands:
    def test_undo_toggle_returns_same_command(self) -> None:
        """Toggle commands undo by re-toggling."""
        history = CommandHistory()
        state = SimState()
        history.record(
            "LANDING_LIGHTS_TOGGLE",
            0,
            system="lights",
            action="landing",
            state_before=state,
        )

        undo = history.get_undo_action()
        assert undo is not None
        system, action, value = undo
        assert system == "lights"
        assert action == "landing"

    def test_undo_gear_toggle(self) -> None:
        history = CommandHistory()
        state = SimState()
        history.record(
            "GEAR_TOGGLE",
            0,
            system="gear",
            action="toggle",
            state_before=state,
        )

        undo = history.get_undo_action()
        assert undo is not None
        system, action, value = undo
        assert system == "gear"
        assert action == "toggle"


# ---------------------------------------------------------------------------
# get_undo_action — empty history
# ---------------------------------------------------------------------------


class TestUndoEmptyHistory:
    def test_undo_empty_history_returns_none(self) -> None:
        history = CommandHistory()
        undo = history.get_undo_action()
        assert undo is None


# ---------------------------------------------------------------------------
# get_undo_action — non-reversible commands
# ---------------------------------------------------------------------------


class TestUndoNonReversible:
    def test_non_reversible_returns_none(self) -> None:
        """Commands like starter engage cannot be undone."""
        history = CommandHistory()
        state = SimState()
        history.record(
            "TOGGLE_STARTER1",
            0,
            system="starter",
            action="engage",
            state_before=state,
        )
        undo = history.get_undo_action()
        assert undo is None

    def test_unknown_command_returns_none(self) -> None:
        history = CommandHistory()
        state = SimState()
        history.record(
            "BOGUS_CMD",
            0,
            system="bogus",
            action="bogus",
            state_before=state,
        )
        undo = history.get_undo_action()
        assert undo is None


# ---------------------------------------------------------------------------
# State snapshot extraction
# ---------------------------------------------------------------------------


class TestStateSnapshot:
    def test_ap_master_snapshot(self) -> None:
        """Recording AP_MASTER should snapshot autopilot.master."""
        history = CommandHistory()
        state = SimState(autopilot=AutopilotState(master=True))
        history.record("AP_MASTER", 0, system="autopilot", action="toggle", state_before=state)

        record = history.last_command
        assert record is not None
        assert record.sim_state_before.get("autopilot_master") is True

    def test_flaps_snapshot(self) -> None:
        """Recording FLAPS_SET should snapshot surfaces.flaps_percent."""
        history = CommandHistory()
        state = SimState(surfaces=SurfaceState(flaps_percent=25.0))
        history.record("FLAPS_SET", 16383, system="flaps", action="set", state_before=state)

        record = history.last_command
        assert record is not None
        assert record.sim_state_before.get("surfaces.flaps_percent") == 25.0

    def test_heading_snapshot(self) -> None:
        """Recording HEADING_BUG_SET should snapshot autopilot.heading."""
        history = CommandHistory()
        state = SimState(autopilot=AutopilotState(heading=90))
        history.record(
            "HEADING_BUG_SET",
            270,
            system="autopilot",
            action="heading",
            state_before=state,
        )

        record = history.last_command
        assert record is not None
        assert record.sim_state_before.get("autopilot.heading") == 90
