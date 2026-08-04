"""Tests for orchestrator.procedures — multi-step procedure definitions and executor."""

from __future__ import annotations

import inspect
from pathlib import Path
from unittest.mock import AsyncMock

import pytest
from orchestrator.authority import AuthorityLevel, AuthorityState
from orchestrator.command_safety import CommandSafetyCheck, SafetyResult
from orchestrator.sim_client import SimState

#: A real checker with an empty rule set. Used where a test needs to isolate
#: something other than safety: since every procedure step now runs through
#: ``set_aircraft_control``, the default on-ground ``SimState()`` would otherwise
#: block ``GEAR_UP`` before the behaviour under test is reached. Subclassing is
#: unnecessary -- ``CommandSafetyCheck`` already takes its rules by injection, so
#: this stays type-honest.
_NO_RULES = CommandSafetyCheck(rules=[])

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

PROCEDURES_SOURCE = Path(inspect.getfile(ProcedureExecutor)).read_text()


class _WarnOnCommand(CommandSafetyCheck):
    """A checker that returns a ``warning`` verdict for exactly one command.

    Subclasses the real class rather than duck-typing so the ``safety_check=``
    parameter's declared type stays honest and the stub cannot drift from the
    real ``check()`` signature.
    """

    def __init__(self, command: str) -> None:
        super().__init__(rules=[])
        self._target = command

    def check(
        self,
        command: str,
        value: int,
        sim_state: SimState,
        aircraft_type: str = "",
    ) -> SafetyResult:
        if command == self._target:
            return SafetyResult(
                safe=True,
                command=command,
                reason="stub advisory condition",
                severity="warning",
            )
        return SafetyResult(safe=True, command=command)


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
        # Steps now route through set_aircraft_control, which reads live telemetry
        # for the safety check. A bare AsyncMock would hand it a mock in place of a
        # SimState and every step would fail on attribute access.
        client.get_state.return_value = SimState()
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
        client.get_state.return_value = SimState()

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
        """Go-around must send throttle 100%.

        Safety rules are stubbed out because go-around retracts the gear, and the
        default ``SimState()`` is on the ground -- the real checker would (rightly)
        block step 3. That interaction is covered by the re-route regression test;
        this one is about the throttle value.
        """
        client = self._make_client(success=True)
        executor = ProcedureExecutor(client, safety_check=_NO_RULES)
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


# ---------------------------------------------------------------------------
# D-06: a withheld step aborts the procedure
# ---------------------------------------------------------------------------


def _client(success: bool = True) -> AsyncMock:
    """A telemetry client double that satisfies the safety check's state read."""
    client = AsyncMock()
    client.send_command.return_value = {"success": success, "message": "ok"}
    client.get_state.return_value = SimState()
    return client


class TestAbortOnWithheld:
    """A step MERLIN declined to send stops the procedure (D-06)."""

    @pytest.mark.asyncio
    async def test_advisory_aborts_at_first_step(self) -> None:
        client = _client()
        executor = ProcedureExecutor(
            client,
            authority=AuthorityState(AuthorityLevel.ADVISORY),
        )
        proc = get_procedure("landing_config")
        assert proc is not None
        assert len(proc.steps) == 3

        result = await executor.execute(proc)

        assert result.steps_completed == 0
        assert result.success is False
        assert result.aborted is True
        assert result.step_results[0].withheld is True
        assert len(result.step_results) == 1, (
            "A withheld step must stop the procedure. Extra step results mean the "
            "loop continued past a command MERLIN had already declined to send."
        )
        client.send_command.assert_not_called()

    @pytest.mark.asyncio
    async def test_advisory_abort_is_visible_in_to_dict(self) -> None:
        client = _client()
        executor = ProcedureExecutor(
            client,
            authority=AuthorityState(AuthorityLevel.ADVISORY),
        )
        proc = get_procedure("landing_config")
        assert proc is not None

        d = (await executor.execute(proc)).to_dict()

        assert d["aborted"] is True
        assert d["abort_reason"]
        assert d["steps_completed"] == 0
        assert d["steps_total"] == 3
        assert d["steps"][0]["withheld"] is True
        assert d["steps"][0]["withheld_reason"]

    @pytest.mark.asyncio
    async def test_assisted_aborts_at_the_flagged_step(self) -> None:
        """Step 1 executes, step 2 is withheld, step 3 never runs."""
        client = _client()
        executor = ProcedureExecutor(
            client,
            safety_check=_WarnOnCommand("FLAPS_SET"),
            authority=AuthorityState(AuthorityLevel.ASSISTED),
        )
        proc = get_procedure("landing_config")
        assert proc is not None

        result = await executor.execute(proc)

        assert result.steps_completed == 1
        assert result.aborted is True
        assert result.success is False
        assert len(result.step_results) == 2
        assert result.step_results[0].success is True
        assert result.step_results[1].withheld is True
        # Only step 1 (GEAR_DOWN) reached the sim.
        assert client.send_command.call_count == 1
        assert client.send_command.call_args_list[0][0][0] == "GEAR_DOWN"

    @pytest.mark.asyncio
    async def test_assisted_abort_reports_reason_and_completed_count(self) -> None:
        client = _client()
        executor = ProcedureExecutor(
            client,
            safety_check=_WarnOnCommand("FLAPS_SET"),
            authority=AuthorityState(AuthorityLevel.ASSISTED),
        )
        proc = get_procedure("landing_config")
        assert proc is not None

        d = (await executor.execute(proc)).to_dict()

        assert d["aborted"] is True
        assert "stub advisory condition" in d["abort_reason"]
        assert d["steps_completed"] == 1
        assert d["steps_total"] == 3
        assert d["steps"][1]["withheld"] is True

    @pytest.mark.asyncio
    async def test_full_authority_runs_every_step(self) -> None:
        """The abort is authority-driven, not an unconditional new behaviour."""
        client = _client()
        executor = ProcedureExecutor(
            client,
            safety_check=_WarnOnCommand("FLAPS_SET"),
            authority=AuthorityState(AuthorityLevel.FULL),
        )
        proc = get_procedure("landing_config")
        assert proc is not None

        result = await executor.execute(proc)

        assert result.aborted is False
        assert result.steps_completed == 3
        assert client.send_command.call_count == 3


class TestFailureStillContinues:
    """The continue-on-failure default that D-06 overrides *only* for withholds."""

    @pytest.mark.asyncio
    async def test_failed_step_does_not_abort(self) -> None:
        client = _client()
        client.send_command.side_effect = [
            {"success": False, "error": "Adapter rejected"},
            {"success": True, "message": "ok"},
            {"success": True, "message": "ok"},
        ]
        executor = ProcedureExecutor(client)
        proc = get_procedure("landing_config")
        assert proc is not None

        result = await executor.execute(proc)

        assert len(result.step_results) == 3
        assert result.steps_completed == 2
        assert result.success is False
        assert result.aborted is False, (
            "A failed step must not abort. Aborting mid-procedure could leave the "
            "aircraft in a worse configuration than completing it; only a withheld "
            "step aborts (D-06)."
        )
        assert result.step_results[0].withheld is False
        assert result.step_results[0].error == "Adapter rejected"


class TestReRouteThroughSafetyCheck:
    """The gap this plan closed: procedures reached the sim with no safety check."""

    @pytest.mark.asyncio
    async def test_gear_up_on_ground_is_blocked_in_a_procedure(self) -> None:
        client = _client()
        # A real checker with the real default rules, and the default on-ground state.
        executor = ProcedureExecutor(client, safety_check=CommandSafetyCheck())
        proc = PROCEDURES["cleanup_after_takeoff"]
        assert proc.steps[0].system == "gear"
        assert proc.steps[0].action == "up"

        result = await executor.execute(proc)

        first = result.step_results[0]
        assert first.success is False
        assert "gear" in first.error.lower()
        assert result.success is False
        # The whole point: GEAR_UP never reached the transport. Before this plan it did.
        sent = [call[0][0] for call in client.send_command.call_args_list]
        assert "GEAR_UP" not in sent, (
            "GEAR_UP reached the sim from inside a procedure while on the ground. "
            "Procedure steps must be safety-checked like any other command."
        )

    @pytest.mark.asyncio
    async def test_blocked_step_is_a_failure_not_a_withhold(self) -> None:
        """`blocked` is a safety verdict, so it keeps the continue-on-failure path."""
        client = _client()
        executor = ProcedureExecutor(client, safety_check=CommandSafetyCheck())

        result = await executor.execute(PROCEDURES["cleanup_after_takeoff"])

        assert result.step_results[0].withheld is False
        assert result.aborted is False
        assert len(result.step_results) == len(PROCEDURES["cleanup_after_takeoff"].steps)


class TestNoDirectTransportRegression:
    """Structural guards. The bypass this plan removed lasted months undetected."""

    def test_module_never_talks_to_the_transport_directly(self) -> None:
        assert "send_command" not in PROCEDURES_SOURCE, (
            "procedures.py must route every step through set_aircraft_control. The "
            "last time this module talked to the transport directly it bypassed "
            "command_safety entirely -- for months, undetected, on main."
        )

    def test_module_does_not_resolve_commands_itself(self) -> None:
        assert "_resolve_command" not in PROCEDURES_SOURCE, (
            "Resolving commands here is the first half of the bypass; the transport "
            "call is the second. Command resolution belongs to set_aircraft_control."
        )

    def test_constructor_accepts_authority(self) -> None:
        params = list(inspect.signature(ProcedureExecutor.__init__).parameters)
        assert "authority" in params, (
            "Dropping the authority parameter would silently ungate every procedure: "
            "steps would still be safety-checked but would execute at any authority "
            "level, which is exactly what D-06 forbids."
        )

    def test_constructor_accepts_the_full_collaborator_set(self) -> None:
        params = list(inspect.signature(ProcedureExecutor.__init__).parameters)
        for collaborator in ("verifier", "safety_check", "command_history"):
            assert collaborator in params, (
                f"{collaborator!r} must be forwardable to set_aircraft_control, or "
                "procedure steps lose verification, safety or undo support that a "
                "direct tool call has."
            )

    def test_collaborators_are_optional(self) -> None:
        """Existing construction sites (e.g. claude_client) pass sim_client only."""
        sig = inspect.signature(ProcedureExecutor.__init__)
        for name in ("verifier", "safety_check", "command_history", "authority"):
            assert sig.parameters[name].default is None
