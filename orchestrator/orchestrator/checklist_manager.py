"""Interactive checklist session manager driven by flight phase transitions."""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any

from .sim_client import FlightPhase

logger = logging.getLogger(__name__)

# Map flight phases to the checklist name MERLIN should offer.
PHASE_CHECKLIST_MAP: dict[FlightPhase, str] = {
    FlightPhase.PREFLIGHT: "Preflight checklist",
    FlightPhase.TAXI: "Before takeoff checklist",
    FlightPhase.CLIMB: "After takeoff checklist",
    FlightPhase.CRUISE: "Cruise checklist",
    FlightPhase.DESCENT: "Descent/approach checklist",
    FlightPhase.LANDED: "After landing checklist",
}


@dataclass
class ChecklistItem:
    """A single checklist entry."""

    item: str  # e.g. "Fuel quantity"
    setting: str  # e.g. "Sufficient for flight + reserves"
    remark: str = ""  # Optional MERLIN commentary
    completed: bool = False


@dataclass
class ActiveChecklist:
    """Tracks an in-progress checklist session."""

    phase: str
    name: str
    items: list[ChecklistItem]
    current_index: int = 0
    started_at: float = field(default_factory=time.time)

    @property
    def current_item(self) -> ChecklistItem | None:
        if self.current_index < len(self.items):
            return self.items[self.current_index]
        return None

    @property
    def is_complete(self) -> bool:
        return self.current_index >= len(self.items)

    @property
    def progress(self) -> str:
        return f"{self.current_index}/{len(self.items)}"


def _format_item(index: int, total: int, ci: ChecklistItem) -> str:
    """Format a single checklist item as a readable prompt string."""
    prompt = f"[{index + 1}/{total}] Item: {ci.item} — {ci.setting}"
    if ci.remark:
        prompt += f" ({ci.remark})"
    return prompt


class ChecklistManager:
    """Manages interactive checklist sessions driven by flight phase changes.

    The orchestrator calls ``on_phase_change`` whenever the flight phase
    detector transitions.  If a checklist is appropriate and hasn't been
    completed yet, the manager returns a prompt for MERLIN to offer it
    to the pilot.

    Individual items are advanced with ``next_item`` (mark complete) or
    ``skip_item`` (leave incomplete).
    """

    def __init__(self) -> None:
        self._active: ActiveChecklist | None = None
        self._completed_phases: set[str] = set()
        self._auto_offer: bool = True  # Auto-offer checklists on phase change

    # ------------------------------------------------------------------
    # Phase change hook
    # ------------------------------------------------------------------

    def on_phase_change(self, new_phase: FlightPhase) -> str | None:
        """Called when flight phase changes. Returns a prompt to offer checklist, or None."""
        if not self._auto_offer:
            return None

        checklist_name = PHASE_CHECKLIST_MAP.get(new_phase)
        if checklist_name is None:
            return None

        phase_key = new_phase.value
        if phase_key in self._completed_phases:
            return None

        logger.info("Phase %s — offering checklist: %s", phase_key, checklist_name)
        return (
            f"We've entered {phase_key.lower()} phase. "
            f"Ready to run the {checklist_name} when you are, Captain."
        )

    # ------------------------------------------------------------------
    # Session lifecycle
    # ------------------------------------------------------------------

    def start_checklist(self, phase: str, items: list[dict[str, Any]]) -> str:
        """Start a checklist session. Returns the first item prompt.

        *items* is a list of dicts with keys ``item``, ``setting``, and
        optionally ``remark`` — matching the YAML checklist format.
        """
        checklist_items = [
            ChecklistItem(
                item=entry.get("item", ""),
                setting=entry.get("setting", ""),
                remark=entry.get("remark") or "",
            )
            for entry in items
        ]

        if not checklist_items:
            return "No items in checklist."

        self._active = ActiveChecklist(
            phase=phase,
            name=f"{phase} checklist",
            items=checklist_items,
            started_at=time.time(),
        )
        logger.info("Started checklist for phase %s with %d items", phase, len(checklist_items))

        first = self._active.current_item
        assert first is not None  # guaranteed by non-empty check above
        return _format_item(0, len(checklist_items), first)

    def next_item(self) -> str | None:
        """Mark current item complete and advance. Returns next item prompt, or None."""
        if self._active is None or self._active.is_complete:
            return None

        current = self._active.current_item
        if current is not None:
            current.completed = True

        self._active.current_index += 1

        if self._active.is_complete:
            return None

        nxt = self._active.current_item
        assert nxt is not None
        return _format_item(
            self._active.current_index,
            len(self._active.items),
            nxt,
        )

    def skip_item(self) -> str | None:
        """Skip current item (leave incomplete) and advance. Returns next item prompt."""
        if self._active is None or self._active.is_complete:
            return None

        self._active.current_index += 1

        if self._active.is_complete:
            return None

        nxt = self._active.current_item
        assert nxt is not None
        return _format_item(
            self._active.current_index,
            len(self._active.items),
            nxt,
        )

    def complete_checklist(self) -> str:
        """Mark current checklist as complete. Returns summary."""
        if self._active is None:
            return "No active checklist."

        completed_count = sum(1 for i in self._active.items if i.completed)
        total = len(self._active.items)
        skipped = total - completed_count
        elapsed = time.time() - self._active.started_at

        phase = self._active.phase
        self._completed_phases.add(phase)

        summary = f"{self._active.name} complete. {completed_count}/{total} items checked"
        if skipped > 0:
            summary += f", {skipped} skipped"
        summary += f" ({elapsed:.0f}s elapsed)."

        logger.info("Checklist complete for phase %s: %s", phase, summary)
        self._active = None
        return summary

    # ------------------------------------------------------------------
    # Status / introspection
    # ------------------------------------------------------------------

    def get_status(self) -> dict[str, Any]:
        """Return current checklist state for Claude context."""
        status: dict[str, Any] = {
            "has_active_checklist": self._active is not None,
            "completed_phases": sorted(self._completed_phases),
            "auto_offer": self._auto_offer,
        }

        if self._active is not None:
            status["active"] = {
                "phase": self._active.phase,
                "name": self._active.name,
                "progress": self._active.progress,
                "current_item": (
                    {
                        "item": self._active.current_item.item,
                        "setting": self._active.current_item.setting,
                    }
                    if self._active.current_item
                    else None
                ),
                "is_complete": self._active.is_complete,
            }

        return status

    @property
    def auto_offer(self) -> bool:
        return self._auto_offer

    @auto_offer.setter
    def auto_offer(self, value: bool) -> None:
        self._auto_offer = value

    @property
    def active(self) -> ActiveChecklist | None:
        return self._active

    @property
    def completed_phases(self) -> set[str]:
        return self._completed_phases
