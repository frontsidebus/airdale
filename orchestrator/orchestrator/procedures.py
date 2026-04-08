"""Multi-step procedure definitions and executor for compound aircraft commands."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Any

from .sim_client import TelemetryClient
from .tools import _resolve_command

logger = logging.getLogger(__name__)


@dataclass
class ProcedureStep:
    """A single action within a multi-step procedure."""

    system: str
    action: str
    value: float | None = None
    delay_ms: int = 500  # Delay before next step
    description: str = ""


@dataclass
class StepResult:
    """Outcome of executing a single procedure step."""

    step: ProcedureStep
    success: bool
    command: str = ""
    sim_value: int = 0
    error: str = ""


@dataclass
class ProcedureResult:
    """Outcome of executing a complete procedure."""

    procedure_name: str
    success: bool
    steps_completed: int = 0
    steps_total: int = 0
    step_results: list[StepResult] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Serialize to a dict suitable for Claude tool results."""
        return {
            "procedure": self.procedure_name,
            "success": self.success,
            "steps_completed": self.steps_completed,
            "steps_total": self.steps_total,
            "steps": [
                {
                    "description": sr.step.description or f"{sr.step.system} {sr.step.action}",
                    "command": sr.command,
                    "success": sr.success,
                    "error": sr.error,
                }
                for sr in self.step_results
            ],
        }


@dataclass
class Procedure:
    """A named sequence of aircraft control steps."""

    name: str
    description: str
    steps: list[ProcedureStep]


# ---------------------------------------------------------------------------
# Pre-defined procedures
# ---------------------------------------------------------------------------

PROCEDURES: dict[str, Procedure] = {
    "landing_config": Procedure(
        name="landing_config",
        description="Configure for landing: gear down, flaps full, landing lights on",
        steps=[
            ProcedureStep(system="gear", action="down", description="Gear down", delay_ms=500),
            ProcedureStep(system="flaps", action="full", description="Flaps full", delay_ms=500),
            ProcedureStep(
                system="lights",
                action="landing",
                description="Landing lights on",
                delay_ms=0,
            ),
        ],
    ),
    "takeoff_config": Procedure(
        name="takeoff_config",
        description="Configure for takeoff: flaps 10, landing lights on, fuel pump on",
        steps=[
            ProcedureStep(system="flaps", action="10", description="Flaps 10", delay_ms=500),
            ProcedureStep(
                system="lights",
                action="landing",
                description="Landing lights on",
                delay_ms=500,
            ),
            ProcedureStep(
                system="fuel_pump",
                action="on",
                description="Fuel pump on",
                delay_ms=0,
            ),
        ],
    ),
    "cleanup_after_takeoff": Procedure(
        name="cleanup_after_takeoff",
        description="Clean up after takeoff: gear up, flaps up, landing lights off",
        steps=[
            ProcedureStep(system="gear", action="up", description="Gear up", delay_ms=500),
            ProcedureStep(system="flaps", action="up", description="Flaps up", delay_ms=500),
            ProcedureStep(
                system="lights",
                action="landing",
                description="Landing lights off",
                delay_ms=0,
            ),
        ],
    ),
    "go_around": Procedure(
        name="go_around",
        description="Go around: throttle 100%, flaps 10, gear up, landing lights on",
        steps=[
            ProcedureStep(
                system="throttle",
                action="set",
                value=100,
                description="Throttle full",
                delay_ms=500,
            ),
            ProcedureStep(system="flaps", action="10", description="Flaps 10", delay_ms=500),
            ProcedureStep(system="gear", action="up", description="Gear up", delay_ms=500),
            ProcedureStep(
                system="lights",
                action="landing",
                description="Landing lights on",
                delay_ms=0,
            ),
        ],
    ),
    "shutdown": Procedure(
        name="shutdown",
        description="Engine shutdown: throttle idle, mixture cutoff, magnetos off, lights off",
        steps=[
            ProcedureStep(
                system="throttle",
                action="set",
                value=0,
                description="Throttle idle",
                delay_ms=500,
            ),
            ProcedureStep(
                system="mixture",
                action="set",
                value=0,
                description="Mixture cutoff",
                delay_ms=500,
            ),
            ProcedureStep(
                system="magnetos",
                action="off",
                description="Magnetos off",
                delay_ms=500,
            ),
            ProcedureStep(
                system="lights",
                action="landing",
                description="Lights off",
                delay_ms=0,
            ),
        ],
    ),
    "cruise_config": Procedure(
        name="cruise_config",
        description="Configure for cruise: flaps up, landing lights off",
        steps=[
            ProcedureStep(system="flaps", action="up", description="Flaps up", delay_ms=500),
            ProcedureStep(
                system="lights",
                action="landing",
                description="Landing lights off",
                delay_ms=0,
            ),
        ],
    ),
}


def get_procedure(name: str) -> Procedure | None:
    """Look up a procedure by name. Returns None if not found."""
    return PROCEDURES.get(name)


def list_procedures() -> list[dict[str, str]]:
    """Return a summary of all available procedures."""
    return [{"name": p.name, "description": p.description} for p in PROCEDURES.values()]


class ProcedureExecutor:
    """Executes multi-step aircraft procedures sequentially."""

    def __init__(self, sim_client: TelemetryClient) -> None:
        self._sim_client = sim_client

    async def execute(self, procedure: Procedure) -> ProcedureResult:
        """Execute all steps in a procedure, returning results for each.

        Steps are executed sequentially with configurable delays between them.
        If a step fails, the error is recorded but execution continues with
        the remaining steps -- aborting mid-procedure could leave the aircraft
        in a worse configuration than completing it.
        """
        result = ProcedureResult(
            procedure_name=procedure.name,
            success=True,
            steps_total=len(procedure.steps),
        )

        for i, step in enumerate(procedure.steps):
            step_result = await self._execute_step(step)
            result.step_results.append(step_result)

            if step_result.success:
                result.steps_completed += 1
                logger.info(
                    "Procedure %s step %d/%d OK: %s",
                    procedure.name,
                    i + 1,
                    len(procedure.steps),
                    step_result.command,
                )
            else:
                result.success = False
                logger.warning(
                    "Procedure %s step %d/%d FAILED: %s — %s",
                    procedure.name,
                    i + 1,
                    len(procedure.steps),
                    step.description or f"{step.system} {step.action}",
                    step_result.error,
                )

            # Delay before the next step (skip for the last step)
            if step.delay_ms > 0 and i < len(procedure.steps) - 1:
                await asyncio.sleep(step.delay_ms / 1000.0)

        return result

    async def _execute_step(self, step: ProcedureStep) -> StepResult:
        """Execute a single procedure step via the telemetry service."""
        command, sim_value = _resolve_command(step.system, step.action, step.value)

        if command is None:
            return StepResult(
                step=step,
                success=False,
                error=f"Unknown control: system={step.system}, action={step.action}",
            )

        try:
            cmd_result = await self._sim_client.send_command(command, sim_value)
        except Exception as exc:
            return StepResult(
                step=step,
                success=False,
                command=command,
                sim_value=sim_value,
                error=str(exc),
            )

        success = cmd_result.get("success", False)
        error = "" if success else cmd_result.get("error", "Command failed")

        return StepResult(
            step=step,
            success=success,
            command=command,
            sim_value=sim_value,
            error=error,
        )
