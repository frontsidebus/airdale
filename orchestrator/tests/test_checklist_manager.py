"""Tests for orchestrator.checklist_manager — interactive checklist sessions."""

from __future__ import annotations

import time

from orchestrator.checklist_manager import (
    PHASE_CHECKLIST_MAP,
    ActiveChecklist,
    ChecklistItem,
    ChecklistManager,
    _format_item,
)
from orchestrator.sim_client import FlightPhase

# ---------------------------------------------------------------------------
# ChecklistItem dataclass
# ---------------------------------------------------------------------------


class TestChecklistItem:
    def test_defaults(self) -> None:
        ci = ChecklistItem(item="Fuel", setting="Full")
        assert ci.item == "Fuel"
        assert ci.setting == "Full"
        assert ci.remark == ""
        assert ci.completed is False

    def test_with_remark(self) -> None:
        ci = ChecklistItem(item="Oil", setting="6 qts", remark="Check dipstick")
        assert ci.remark == "Check dipstick"


# ---------------------------------------------------------------------------
# ActiveChecklist dataclass
# ---------------------------------------------------------------------------


class TestActiveChecklist:
    def _make(self, n: int = 3) -> ActiveChecklist:
        items = [ChecklistItem(item=f"Item {i}", setting=f"Set {i}") for i in range(n)]
        return ActiveChecklist(phase="PREFLIGHT", name="Preflight checklist", items=items)

    def test_current_item_returns_first(self) -> None:
        cl = self._make()
        assert cl.current_item is not None
        assert cl.current_item.item == "Item 0"

    def test_current_item_none_when_complete(self) -> None:
        cl = self._make(1)
        cl.current_index = 1
        assert cl.current_item is None

    def test_is_complete(self) -> None:
        cl = self._make(2)
        assert cl.is_complete is False
        cl.current_index = 2
        assert cl.is_complete is True

    def test_progress_string(self) -> None:
        cl = self._make(5)
        assert cl.progress == "0/5"
        cl.current_index = 3
        assert cl.progress == "3/5"

    def test_started_at_populated(self) -> None:
        before = time.time()
        cl = self._make()
        assert cl.started_at >= before


# ---------------------------------------------------------------------------
# _format_item helper
# ---------------------------------------------------------------------------


class TestFormatItem:
    def test_basic(self) -> None:
        ci = ChecklistItem(item="Fuel", setting="Full")
        result = _format_item(0, 5, ci)
        assert result == "[1/5] Item: Fuel — Full"

    def test_with_remark(self) -> None:
        ci = ChecklistItem(item="Oil", setting="6 qts", remark="Check dipstick")
        result = _format_item(2, 4, ci)
        assert result == "[3/4] Item: Oil — 6 qts (Check dipstick)"


# ---------------------------------------------------------------------------
# ChecklistManager.on_phase_change
# ---------------------------------------------------------------------------


class TestOnPhaseChange:
    def test_offers_checklist_for_mapped_phase(self) -> None:
        mgr = ChecklistManager()
        result = mgr.on_phase_change(FlightPhase.PREFLIGHT)
        assert result is not None
        assert "preflight" in result.lower()
        assert "Preflight checklist" in result

    def test_no_offer_for_unmapped_phase(self) -> None:
        mgr = ChecklistManager()
        # TAKEOFF, APPROACH, LANDING are not in the map
        assert mgr.on_phase_change(FlightPhase.TAKEOFF) is None
        assert mgr.on_phase_change(FlightPhase.APPROACH) is None
        assert mgr.on_phase_change(FlightPhase.LANDING) is None

    def test_no_offer_when_auto_offer_disabled(self) -> None:
        mgr = ChecklistManager()
        mgr.auto_offer = False
        assert mgr.on_phase_change(FlightPhase.PREFLIGHT) is None

    def test_no_offer_for_already_completed_phase(self) -> None:
        mgr = ChecklistManager()
        mgr._completed_phases.add("PREFLIGHT")
        assert mgr.on_phase_change(FlightPhase.PREFLIGHT) is None

    def test_all_mapped_phases_produce_offers(self) -> None:
        mgr = ChecklistManager()
        for phase in PHASE_CHECKLIST_MAP:
            result = mgr.on_phase_change(phase)
            assert result is not None, f"Expected offer for {phase}"


# ---------------------------------------------------------------------------
# ChecklistManager.start_checklist
# ---------------------------------------------------------------------------

SAMPLE_ITEMS = [
    {"item": "Fuel quantity", "setting": "Sufficient for flight + reserves", "remark": "Check it."},
    {"item": "Oil level", "setting": "Within limits"},
    {"item": "Flight controls", "setting": "Free and correct", "remark": ""},
]


class TestStartChecklist:
    def test_returns_first_item(self) -> None:
        mgr = ChecklistManager()
        result = mgr.start_checklist("PREFLIGHT", SAMPLE_ITEMS)
        assert "[1/3]" in result
        assert "Fuel quantity" in result
        assert "Sufficient for flight" in result
        assert "Check it." in result

    def test_active_checklist_set(self) -> None:
        mgr = ChecklistManager()
        mgr.start_checklist("PREFLIGHT", SAMPLE_ITEMS)
        assert mgr.active is not None
        assert mgr.active.phase == "PREFLIGHT"
        assert len(mgr.active.items) == 3

    def test_empty_items(self) -> None:
        mgr = ChecklistManager()
        result = mgr.start_checklist("PREFLIGHT", [])
        assert "No items" in result
        assert mgr.active is None

    def test_items_without_remark(self) -> None:
        mgr = ChecklistManager()
        result = mgr.start_checklist("CRUISE", [{"item": "Throttle", "setting": "Cruise power"}])
        assert "Throttle" in result
        assert "(" not in result  # no remark parenthetical

    def test_null_remark_treated_as_empty(self) -> None:
        mgr = ChecklistManager()
        result = mgr.start_checklist("CRUISE", [{"item": "X", "setting": "Y", "remark": None}])
        assert "(" not in result


# ---------------------------------------------------------------------------
# ChecklistManager.next_item
# ---------------------------------------------------------------------------


class TestNextItem:
    def test_advances_and_marks_complete(self) -> None:
        mgr = ChecklistManager()
        mgr.start_checklist("PREFLIGHT", SAMPLE_ITEMS)
        result = mgr.next_item()
        assert result is not None
        assert "[2/3]" in result
        assert "Oil level" in result
        # First item should be marked completed
        assert mgr.active is not None
        assert mgr.active.items[0].completed is True

    def test_returns_none_on_last_item(self) -> None:
        mgr = ChecklistManager()
        mgr.start_checklist("PREFLIGHT", [{"item": "A", "setting": "B"}])
        result = mgr.next_item()
        assert result is None

    def test_returns_none_when_no_active(self) -> None:
        mgr = ChecklistManager()
        assert mgr.next_item() is None

    def test_full_walkthrough(self) -> None:
        mgr = ChecklistManager()
        mgr.start_checklist("PREFLIGHT", SAMPLE_ITEMS)
        r1 = mgr.next_item()
        assert r1 is not None and "Oil level" in r1
        r2 = mgr.next_item()
        assert r2 is not None and "Flight controls" in r2
        r3 = mgr.next_item()
        assert r3 is None
        assert mgr.active is not None
        assert mgr.active.is_complete is True


# ---------------------------------------------------------------------------
# ChecklistManager.skip_item
# ---------------------------------------------------------------------------


class TestSkipItem:
    def test_skips_without_completing(self) -> None:
        mgr = ChecklistManager()
        mgr.start_checklist("PREFLIGHT", SAMPLE_ITEMS)
        result = mgr.skip_item()
        assert result is not None
        assert "Oil level" in result
        # First item NOT completed
        assert mgr.active is not None
        assert mgr.active.items[0].completed is False

    def test_returns_none_on_last_item(self) -> None:
        mgr = ChecklistManager()
        mgr.start_checklist("PREFLIGHT", [{"item": "A", "setting": "B"}])
        assert mgr.skip_item() is None

    def test_returns_none_when_no_active(self) -> None:
        mgr = ChecklistManager()
        assert mgr.skip_item() is None

    def test_mix_next_and_skip(self) -> None:
        mgr = ChecklistManager()
        mgr.start_checklist("PREFLIGHT", SAMPLE_ITEMS)
        mgr.next_item()  # complete item 0, go to 1
        mgr.skip_item()  # skip item 1, go to 2
        mgr.next_item()  # complete item 2, done
        assert mgr.active is not None
        assert mgr.active.items[0].completed is True
        assert mgr.active.items[1].completed is False
        assert mgr.active.items[2].completed is True


# ---------------------------------------------------------------------------
# ChecklistManager.complete_checklist
# ---------------------------------------------------------------------------


class TestCompleteChecklist:
    def test_summary_content(self) -> None:
        mgr = ChecklistManager()
        mgr.start_checklist("PREFLIGHT", SAMPLE_ITEMS)
        mgr.next_item()  # complete item 0
        mgr.next_item()  # complete item 1
        # Item 2 not completed
        summary = mgr.complete_checklist()
        assert "PREFLIGHT checklist complete" in summary
        assert "2/3 items checked" in summary
        assert "1 skipped" in summary

    def test_all_completed(self) -> None:
        mgr = ChecklistManager()
        mgr.start_checklist("CRUISE", SAMPLE_ITEMS)
        mgr.next_item()
        mgr.next_item()
        mgr.next_item()
        summary = mgr.complete_checklist()
        assert "3/3 items checked" in summary
        assert "skipped" not in summary

    def test_phase_marked_completed(self) -> None:
        mgr = ChecklistManager()
        mgr.start_checklist("PREFLIGHT", SAMPLE_ITEMS)
        mgr.complete_checklist()
        assert "PREFLIGHT" in mgr.completed_phases

    def test_active_cleared(self) -> None:
        mgr = ChecklistManager()
        mgr.start_checklist("PREFLIGHT", SAMPLE_ITEMS)
        mgr.complete_checklist()
        assert mgr.active is None

    def test_no_active_checklist(self) -> None:
        mgr = ChecklistManager()
        result = mgr.complete_checklist()
        assert "No active checklist" in result

    def test_elapsed_time_in_summary(self) -> None:
        mgr = ChecklistManager()
        mgr.start_checklist("PREFLIGHT", SAMPLE_ITEMS)
        # Manually set started_at to the past
        assert mgr.active is not None
        mgr.active.started_at = time.time() - 42
        summary = mgr.complete_checklist()
        assert "42s" in summary or "43s" in summary  # allow for rounding


# ---------------------------------------------------------------------------
# ChecklistManager.get_status
# ---------------------------------------------------------------------------


class TestGetStatus:
    def test_no_active(self) -> None:
        mgr = ChecklistManager()
        status = mgr.get_status()
        assert status["has_active_checklist"] is False
        assert "active" not in status
        assert status["completed_phases"] == []
        assert status["auto_offer"] is True

    def test_with_active(self) -> None:
        mgr = ChecklistManager()
        mgr.start_checklist("DESCENT", SAMPLE_ITEMS)
        status = mgr.get_status()
        assert status["has_active_checklist"] is True
        active = status["active"]
        assert active["phase"] == "DESCENT"
        assert active["progress"] == "0/3"
        assert active["current_item"]["item"] == "Fuel quantity"
        assert active["is_complete"] is False

    def test_completed_phases_sorted(self) -> None:
        mgr = ChecklistManager()
        mgr._completed_phases = {"CRUISE", "PREFLIGHT", "DESCENT"}
        status = mgr.get_status()
        assert status["completed_phases"] == ["CRUISE", "DESCENT", "PREFLIGHT"]

    def test_active_complete_shows_no_current_item(self) -> None:
        mgr = ChecklistManager()
        mgr.start_checklist("CRUISE", [{"item": "A", "setting": "B"}])
        mgr.next_item()  # advances past the only item
        status = mgr.get_status()
        assert status["active"]["current_item"] is None
        assert status["active"]["is_complete"] is True


# ---------------------------------------------------------------------------
# Auto-offer property
# ---------------------------------------------------------------------------


class TestAutoOffer:
    def test_default_true(self) -> None:
        mgr = ChecklistManager()
        assert mgr.auto_offer is True

    def test_toggle(self) -> None:
        mgr = ChecklistManager()
        mgr.auto_offer = False
        assert mgr.auto_offer is False
        mgr.auto_offer = True
        assert mgr.auto_offer is True


# ---------------------------------------------------------------------------
# Integration: phase change -> start -> walk through -> complete -> re-offer
# ---------------------------------------------------------------------------


class TestEndToEnd:
    def test_full_lifecycle(self) -> None:
        mgr = ChecklistManager()

        # Phase change triggers offer
        offer = mgr.on_phase_change(FlightPhase.PREFLIGHT)
        assert offer is not None

        # Start checklist
        first = mgr.start_checklist("PREFLIGHT", SAMPLE_ITEMS)
        assert "[1/3]" in first

        # Walk through
        second = mgr.next_item()
        assert second is not None
        third = mgr.next_item()
        assert third is not None
        done = mgr.next_item()
        assert done is None

        # Complete
        summary = mgr.complete_checklist()
        assert "3/3" in summary

        # Re-offer should NOT happen for same phase
        assert mgr.on_phase_change(FlightPhase.PREFLIGHT) is None

        # But different phase should offer
        offer2 = mgr.on_phase_change(FlightPhase.CRUISE)
        assert offer2 is not None
        assert "Cruise checklist" in offer2

    def test_replace_active_checklist(self) -> None:
        """Starting a new checklist replaces any active one without completing it."""
        mgr = ChecklistManager()
        mgr.start_checklist("PREFLIGHT", SAMPLE_ITEMS)
        mgr.next_item()
        # Start a different checklist before completing
        result = mgr.start_checklist("CRUISE", [{"item": "Power", "setting": "Set"}])
        assert "Power" in result
        assert mgr.active is not None
        assert mgr.active.phase == "CRUISE"
        # PREFLIGHT was NOT marked completed (never called complete_checklist)
        assert "PREFLIGHT" not in mgr.completed_phases
