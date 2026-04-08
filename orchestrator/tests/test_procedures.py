"""Tests for orchestrator.procedures — multi-step procedure definitions and executor."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

procedures_mod = pytest.importorskip(
    "orchestrator.procedures",
    reason="orchestrator.procedures not implemented yet",
)
PROCEDURES = procedures_mod.PROCEDURES
Procedure = procedures_mod.Procedure
ProcedureExecutor = procedures_mod.ProcedureExecutor
ProcedureResult = procedures_mod.ProcedureResult
ProcedureStep = procedures_mod.ProcedureStep
StepResult = procedures_mod.StepResult
get_procedure = procedures_mod.get_procedure
list_procedures = procedures_mod.list_procedures


# ---------------------------------------------------------------------------
# ProcedureStep dataclass
# ---------------------------------------------------------------------------


class TestProcedureStepFields:
    def test_all_fields_present(self) -> None:
        step = ProcedureStep(
            system="gear",
            action="down",
            value=None,
            delay_ms=500,
            description="Gear down",
        )
        assert step.system == "gear"
        assert step.action == "down"
        assert step.value is None
        assert step.delay_ms == 500
        assert step.description == "Gear down"

    def test_default_values(self) -> None:
        step = ProcedureStep(system="flaps", action="full")
        assert step.value is None
        assert step.delay_ms == 500
        assert step.description == ""


# ---------------------------------------------------------------------------
# ProcedureResult / StepResult
# ---------------------------------------------------------------------------


class TestProcedureResultFields:
    def test_all_fields_present(self) -> None:
        result = ProcedureResult(
            procedure_name="test",
            success=True,
            steps_completed=3,
            steps_total=3,
        )
        assert result.procedure_name == "test"
        assert result.success is True
        assert result.steps_completed == 3
        assert result.steps_total == 3
        assert result.step_results == []

    def test_to_dict_tracks_success_and_failure(self) -> None:
        step_ok = StepResult(
            step=ProcedureStep(system="gear", action="down", description="Gear"),
            success=True,
            command="GEAR_DOWN",
        )
        step_fail = StepResult(
            step=ProcedureStep(system="flaps", action="full", description="Flaps"),
            success=False,
            error="Command failed",
        )
        result = ProcedureResult(
            procedure_name="test",
            success=False,
            steps_completed=1,
            steps_total=2,
            step_results=[step_ok, step_fail],
        )
        d = result.to_dict()
        assert d["steps"][0]["success"] is True
        assert d["steps"][1]["success"] is False
        assert d["steps"][1]["error"] == "Command failed"

    def test_to_dict_fallback_description(self) -> None:
        """If description is empty, to_dict should use system + action."""
        step = ProcedureStep(system="flaps", action="full")
        sr = StepResult(step=step, success=True, command="FLAPS_SET")
        result = ProcedureResult(
            procedure_name="t",
            success=True,
            steps_completed=1,
            steps_total=1,
            step_results=[sr],
        )
        d = result.to_dict()
        assert "flaps full" in d["steps"][0]["description"]


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

    def test_list_procedures_has_name_and_description(self) -> None:
        for p in list_procedures():
            assert "name" in p
            assert "description" in p

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

    def test_takeoff_config_steps(self) -> None:
        proc = PROCEDURES["takeoff_config"]
        systems = [s.system for s in proc.steps]
        assert "flaps" in systems
        assert len(proc.steps) >= 2

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
        client.send_command.assert_not_called()

    @pytest.mark.asyncio
    async def test_steps_execute_in_order(self) -> None:
        """Steps should be executed sequentially, in definition order."""
        execution_order: list[str] = []

        async def track_command(command: str, value: int) -> dict:
            execution_order.append(command)
            return {"success": True}

        client = AsyncMock()
        client.send_command = AsyncMock(side_effect=track_command)

        proc = Procedure(
            name="test_order",
            description="Test order",
            steps=[
                ProcedureStep(system="gear", action="down", delay_ms=0),
                ProcedureStep(system="flaps", action="full", delay_ms=0),
                ProcedureStep(system="lights", action="landing", delay_ms=0),
            ],
        )
        executor = ProcedureExecutor(client)
        await executor.execute(proc)

        assert execution_order == ["GEAR_DOWN", "FLAPS_SET", "LANDING_LIGHTS_TOGGLE"]

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
        first_call = client.send_command.call_args_list[0]
        assert first_call[0][0] == "THROTTLE_SET"
        assert first_call[0][1] == 16383

    @pytest.mark.asyncio
    async def test_empty_procedure_succeeds(self) -> None:
        client = self._make_client()
        executor = ProcedureExecutor(client)
        proc = Procedure(name="empty", description="Empty", steps=[])
        result = await executor.execute(proc)
        assert result.success is True
        assert result.steps_total == 0
