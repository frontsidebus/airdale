"""Tests for orchestrator.procedures — multi-step procedure execution."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest
from orchestrator.procedures import (
    PROCEDURES,
    Procedure,
    ProcedureExecutor,
    ProcedureStep,
    get_procedure,
    list_procedures,
)

# ---------------------------------------------------------------------------
# Registry helpers
# ---------------------------------------------------------------------------


class TestProcedureRegistry:
    """Tests for procedure lookup and listing."""

    def test_get_known_procedure(self) -> None:
        proc = get_procedure("landing_config")
        assert proc is not None
        assert proc.name == "landing_config"

    def test_get_unknown_procedure_returns_none(self) -> None:
        assert get_procedure("barrel_roll") is None

    def test_all_predefined_procedures_exist(self) -> None:
        expected = {
            "landing_config",
            "takeoff_config",
            "cleanup_after_takeoff",
            "go_around",
            "shutdown",
            "cruise_config",
        }
        assert set(PROCEDURES.keys()) == expected

    def test_list_procedures_returns_all(self) -> None:
        result = list_procedures()
        assert len(result) == len(PROCEDURES)
        names = {p["name"] for p in result}
        assert names == set(PROCEDURES.keys())

    def test_every_procedure_has_steps(self) -> None:
        for name, proc in PROCEDURES.items():
            assert len(proc.steps) > 0, f"Procedure {name} has no steps"

    def test_every_procedure_has_description(self) -> None:
        for name, proc in PROCEDURES.items():
            assert proc.description, f"Procedure {name} has no description"

    def test_landing_config_contains_gear_flaps_lights(self) -> None:
        proc = PROCEDURES["landing_config"]
        systems = [s.system for s in proc.steps]
        actions = [s.action for s in proc.steps]
        assert "gear" in systems
        assert "flaps" in systems
        assert "lights" in systems
        assert "down" in actions

    def test_go_around_contains_throttle_flaps_gear(self) -> None:
        proc = PROCEDURES["go_around"]
        systems = [s.system for s in proc.steps]
        assert "throttle" in systems
        assert "flaps" in systems
        assert "gear" in systems

    def test_shutdown_contains_throttle_magnetos(self) -> None:
        proc = PROCEDURES["shutdown"]
        systems = [s.system for s in proc.steps]
        assert "throttle" in systems
        assert "magnetos" in systems

    def test_every_step_resolves_to_valid_command(self) -> None:
        """Every step in every predefined procedure must resolve to a SimConnect event."""
        from orchestrator.tools import _resolve_command

        for proc_name, proc in PROCEDURES.items():
            for i, step in enumerate(proc.steps):
                command, _ = _resolve_command(step.system, step.action, step.value)
                assert command is not None, (
                    f"Procedure {proc_name} step {i} ({step.system}/{step.action}) does not resolve"
                )


# ---------------------------------------------------------------------------
# Executor
# ---------------------------------------------------------------------------


class TestProcedureExecutor:
    """Tests for ProcedureExecutor."""

    def _make_client(self, success: bool = True) -> AsyncMock:
        client = AsyncMock()
        client.send_command.return_value = {"success": success, "message": "ok"}
        return client

    @pytest.mark.asyncio
    async def test_execute_all_steps_success(self) -> None:
        client = self._make_client(success=True)
        executor = ProcedureExecutor(client)
        proc = get_procedure("landing_config")
        assert proc is not None

        result = await executor.execute(proc)

        assert result.success is True
        assert result.steps_completed == len(proc.steps)
        assert result.steps_total == len(proc.steps)
        assert client.send_command.call_count == len(proc.steps)

    @pytest.mark.asyncio
    async def test_execute_continues_after_failure(self) -> None:
        """A failed step should not abort the remaining steps."""
        client = self._make_client(success=True)
        # Make the second call fail
        client.send_command.side_effect = [
            {"success": True, "message": "ok"},
            {"success": False, "error": "Adapter rejected"},
            {"success": True, "message": "ok"},
        ]
        executor = ProcedureExecutor(client)
        proc = get_procedure("landing_config")
        assert proc is not None

        result = await executor.execute(proc)

        assert result.success is False
        assert result.steps_completed == 2  # first and third succeeded
        assert result.steps_total == 3
        assert client.send_command.call_count == 3

    @pytest.mark.asyncio
    async def test_execute_handles_exception_in_send(self) -> None:
        client = self._make_client()
        client.send_command.side_effect = ConnectionError("Lost connection")
        executor = ProcedureExecutor(client)
        proc = Procedure(
            name="test",
            description="test",
            steps=[ProcedureStep(system="gear", action="down", delay_ms=0)],
        )

        result = await executor.execute(proc)

        assert result.success is False
        assert result.steps_completed == 0
        assert result.step_results[0].error == "Lost connection"

    @pytest.mark.asyncio
    async def test_execute_unknown_command_reports_error(self) -> None:
        client = self._make_client()
        executor = ProcedureExecutor(client)
        proc = Procedure(
            name="bad",
            description="bad",
            steps=[ProcedureStep(system="warp_drive", action="engage", delay_ms=0)],
        )

        result = await executor.execute(proc)

        assert result.success is False
        assert "Unknown control" in result.step_results[0].error
        # send_command should never have been called
        client.send_command.assert_not_called()

    @pytest.mark.asyncio
    async def test_to_dict_serialization(self) -> None:
        client = self._make_client(success=True)
        executor = ProcedureExecutor(client)
        proc = get_procedure("cruise_config")
        assert proc is not None

        result = await executor.execute(proc)
        d = result.to_dict()

        assert d["procedure"] == "cruise_config"
        assert d["success"] is True
        assert d["steps_completed"] == d["steps_total"]
        assert len(d["steps"]) == len(proc.steps)
        for step_dict in d["steps"]:
            assert "description" in step_dict
            assert "command" in step_dict
            assert "success" in step_dict

    @pytest.mark.asyncio
    async def test_go_around_sends_throttle_value(self) -> None:
        """Go-around must send throttle 100%."""
        client = self._make_client(success=True)
        executor = ProcedureExecutor(client)
        proc = get_procedure("go_around")
        assert proc is not None

        result = await executor.execute(proc)

        assert result.success is True
        # First call should be THROTTLE_SET with value = 16383 (100%)
        first_call = client.send_command.call_args_list[0]
        assert first_call[0][0] == "THROTTLE_SET"
        assert first_call[0][1] == 16383
