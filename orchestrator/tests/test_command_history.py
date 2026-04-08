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
    Position,
    SimState,
    SurfaceState,
    TelemetryClient,
)
from orchestrator.tools import set_aircraft_control, undo_last_command

# ---------------------------------------------------------------------------
# Helper: airborne SimState (avoids safety blocks on gear commands)
# ---------------------------------------------------------------------------


def _airborne_state(**overrides) -> SimState:
    defaults = dict(
        position=Position(latitude=28.5, longitude=-81.3, altitude_msl=3000, altitude_agl=2900),
        surfaces=SurfaceState(gear_handle=True, flaps_percent=0, spoilers_percent=0),
    )
    defaults.update(overrides)
    return SimState(**defaults)


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


# ---------------------------------------------------------------------------
# Integration: set_aircraft_control records into history
# ---------------------------------------------------------------------------


class TestSetAircraftControlRecording:
    @pytest.mark.asyncio
    async def test_successful_command_recorded(self) -> None:
        mock_client = MagicMock(spec=TelemetryClient)
        mock_client.get_state = AsyncMock(
            return_value=SimState(autopilot=AutopilotState(heading=180))
        )
        mock_client.send_command = AsyncMock(return_value={"success": True, "message": ""})

        cmd_history = CommandHistory()
        await set_aircraft_control(
            mock_client, "autopilot", "heading", value=270, command_history=cmd_history
        )
        assert len(cmd_history) == 1
        assert cmd_history.last_command is not None
        assert cmd_history.last_command.command == "HEADING_BUG_SET"

    @pytest.mark.asyncio
    async def test_failed_command_not_recorded(self) -> None:
        mock_client = MagicMock(spec=TelemetryClient)
        mock_client.get_state = AsyncMock(return_value=SimState())
        mock_client.send_command = AsyncMock(return_value={"success": False, "message": "fail"})

        cmd_history = CommandHistory()
        await set_aircraft_control(
            mock_client, "autopilot", "heading", value=270, command_history=cmd_history
        )
        assert len(cmd_history) == 0

    @pytest.mark.asyncio
    async def test_no_history_when_none_passed(self) -> None:
        mock_client = MagicMock(spec=TelemetryClient)
        mock_client.get_state = AsyncMock(return_value=SimState())
        mock_client.send_command = AsyncMock(return_value={"success": True, "message": ""})

        result = await set_aircraft_control(mock_client, "autopilot", "heading", value=270)
        assert result["command"] == "HEADING_BUG_SET"


# ---------------------------------------------------------------------------
# Integration: undo_last_command
# ---------------------------------------------------------------------------


class TestUndoLastCommand:
    @pytest.mark.asyncio
    async def test_undo_gear_down(self) -> None:
        """Undo gear down by issuing gear up (using airborne state to avoid safety block)."""
        airborne = _airborne_state()
        mock_client = MagicMock(spec=TelemetryClient)
        mock_client.get_state = AsyncMock(return_value=airborne)
        mock_client.send_command = AsyncMock(return_value={"success": True, "message": ""})

        cmd_history = CommandHistory()
        cmd_history.record("GEAR_DOWN", 0, "gear", "down", airborne)

        result = await undo_last_command(mock_client, cmd_history)
        assert result["undone_command"] == "GEAR_DOWN"
        assert "gear" in result["undo_description"]
        mock_client.send_command.assert_awaited_once_with("GEAR_UP", 0)
        assert len(cmd_history) == 0

    @pytest.mark.asyncio
    async def test_undo_empty_history(self) -> None:
        mock_client = MagicMock(spec=TelemetryClient)
        cmd_history = CommandHistory()

        result = await undo_last_command(mock_client, cmd_history)
        assert "error" in result
        assert "No commands to undo" in result["error"]

    @pytest.mark.asyncio
    async def test_undo_non_reversible(self) -> None:
        mock_client = MagicMock(spec=TelemetryClient)
        cmd_history = CommandHistory()
        cmd_history.record("TOGGLE_STARTER1", 0, "starter", "engage", SimState())

        result = await undo_last_command(mock_client, cmd_history)
        assert "error" in result
        assert "not reversible" in result["error"]

    @pytest.mark.asyncio
    async def test_undo_heading_restores_previous_value(self) -> None:
        mock_client = MagicMock(spec=TelemetryClient)
        mock_client.get_state = AsyncMock(return_value=SimState())
        mock_client.send_command = AsyncMock(return_value={"success": True, "message": ""})

        cmd_history = CommandHistory()
        state_before = SimState(autopilot=AutopilotState(heading=270))
        cmd_history.record("HEADING_BUG_SET", 90, "autopilot", "heading", state_before)

        result = await undo_last_command(mock_client, cmd_history)
        assert result["undone_command"] == "HEADING_BUG_SET"
        call_args = mock_client.send_command.call_args
        assert call_args[0][0] == "HEADING_BUG_SET"
        assert call_args[0][1] == 270

    @pytest.mark.asyncio
    async def test_undo_toggle_retoggle(self) -> None:
        mock_client = MagicMock(spec=TelemetryClient)
        mock_client.get_state = AsyncMock(return_value=SimState())
        mock_client.send_command = AsyncMock(return_value={"success": True, "message": ""})

        cmd_history = CommandHistory()
        cmd_history.record("LANDING_LIGHTS_TOGGLE", 0, "lights", "landing", SimState())

        result = await undo_last_command(mock_client, cmd_history)
        assert result["undone_command"] == "LANDING_LIGHTS_TOGGLE"
        mock_client.send_command.assert_awaited_once_with("LANDING_LIGHTS_TOGGLE", 0)

    @pytest.mark.asyncio
    async def test_undo_does_not_record_itself(self) -> None:
        """The undo action itself should not be recorded in history."""
        mock_client = MagicMock(spec=TelemetryClient)
        mock_client.get_state = AsyncMock(return_value=SimState())
        mock_client.send_command = AsyncMock(return_value={"success": True, "message": ""})

        cmd_history = CommandHistory()
        cmd_history.record("LANDING_LIGHTS_TOGGLE", 0, "lights", "landing", SimState())

        await undo_last_command(mock_client, cmd_history)
        assert len(cmd_history) == 0
