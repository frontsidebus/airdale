"""Cross-language parity guard for the aircraft-control command surface.

Three sources of truth have to agree about what MERLIN can actually do to an
aircraft, and until this file existed nothing enforced the agreement:

* ``claude_client.TOOL_DEFINITIONS`` decides which systems Claude may name.
* ``tools._resolve_command`` turns a named system into a SimConnect event name.
* ``SimConnectManager.CommandMap`` in the C# adapter decides which of those
  event names actually reach ``TransmitClientEvent``.

They drifted. ``trim``, ``deice``, ``fuel_selector`` and ``crossfeed`` sat in
the tool enum and resolved to event names the adapter had never registered, so
``ExecuteCommand`` logged ``Unknown command`` and acked ``success:false`` while
MERLIN told the pilot the action was taken. That is the worst failure mode this
system has -- not a refusal, a false confirmation (CMD-07).

The guards below turn that drift into a CI failure. They read the adapter as
text rather than importing it, because the adapter is C# and lives behind the
SimConnect SDK.
"""

from __future__ import annotations

import inspect
import re
from pathlib import Path

import pytest
from orchestrator.claude_client import TOOL_DEFINITIONS
from orchestrator.tools import _resolve_command

# ---------------------------------------------------------------------------
# Locating the adapter source
# ---------------------------------------------------------------------------


def _find_repo_root() -> Path | None:
    """Walk up from this file to the directory holding both packages.

    Walking rather than assuming a fixed depth keeps this working when the
    orchestrator is checked out at a different nesting level, or run from a
    git worktree.
    """
    for candidate in Path(__file__).resolve().parents:
        if (candidate / "orchestrator").is_dir() and (candidate / "adapters").is_dir():
            return candidate
    return None


REPO_ROOT = _find_repo_root()
ADAPTER_SOURCE = (
    REPO_ROOT / "adapters" / "msfs" / "SimConnectManager.cs" if REPO_ROOT is not None else None
)

_ADAPTER_MISSING = ADAPTER_SOURCE is None or not ADAPTER_SOURCE.is_file()

requires_adapter = pytest.mark.skipif(
    _ADAPTER_MISSING,
    reason=(
        "adapters/msfs/SimConnectManager.cs not found -- the orchestrator package is "
        "installable and testable standalone, so the cross-language parity guards are "
        "skipped rather than failed when the adapter tree is absent"
    ),
)

# Matches a CommandMap entry: ["EVENT_NAME"] = SimEventId.Member
_COMMAND_MAP_ENTRY = re.compile(r'\["([A-Z0-9_]+)"\]\s*=\s*SimEventId\.\w+')

# Matches the event-name literals _resolve_command returns: return "EVENT_NAME", ...
_RESOLVER_LITERAL = re.compile(r'return "([A-Z0-9_]+)"')


def _registered_events() -> set[str]:
    """Every SimConnect event name the MSFS adapter has a handler for."""
    assert ADAPTER_SOURCE is not None
    return set(_COMMAND_MAP_ENTRY.findall(ADAPTER_SOURCE.read_text(encoding="utf-8")))


# ---------------------------------------------------------------------------
# The resolver branch table
# ---------------------------------------------------------------------------

# Every (system, action, value) the resolver understands, written out by hand
# rather than derived from source. Adding a branch to _resolve_command without
# adding a row here breaks test_resolver_branch_table_is_exhaustive, which is
# the point: a new branch must be consciously classified as enum-exposed or
# deferred, not absorbed silently.
RESOLVER_BRANCH_TABLE: tuple[tuple[str, str, float | None], ...] = (
    # flaps
    ("flaps", "set", 2),
    ("flaps", "set", 50),
    ("flaps", "up", None),
    ("flaps", "retract", None),
    ("flaps", "full", None),
    ("flaps", "down", None),
    ("flaps", "1", None),
    ("flaps", "10", None),
    ("flaps", "2", None),
    ("flaps", "20", None),
    ("flaps", "3", None),
    ("flaps", "30", None),
    ("flaps", "incr", None),
    ("flaps", "increase", None),
    ("flaps", "decr", None),
    ("flaps", "decrease", None),
    # gear
    ("gear", "up", None),
    ("gear", "retract", None),
    ("gear", "down", None),
    ("gear", "extend", None),
    ("gear", "toggle", None),
    # autopilot
    ("autopilot", "on", None),
    ("autopilot", "off", None),
    ("autopilot", "toggle", None),
    ("autopilot", "heading", 270),
    ("autopilot", "heading_hold", None),
    ("autopilot", "altitude", 5000),
    ("autopilot", "altitude_hold", None),
    ("autopilot", "vertical_speed", -500),
    ("autopilot", "vs_hold", None),
    ("autopilot", "speed", 200),
    ("autopilot", "speed_hold", None),
    ("autopilot", "nav", None),
    ("autopilot", "approach", None),
    # throttle
    ("throttle", "set", 80),
    # radio
    ("radio", "com1", 121.5),
    ("radio", "com2", 122.8),
    ("radio", "nav1", 110.3),
    ("radio", "nav2", 115.0),
    # barometer
    ("barometer", "set", 29.92),
    # trim
    ("trim", "set", 100),
    ("trim", "up", None),
    ("trim", "nose_up", None),
    ("trim", "down", None),
    ("trim", "nose_down", None),
    ("trim", "rudder_left", None),
    ("trim", "rudder_right", None),
    ("trim", "rudder_set", 50),
    ("trim", "aileron_left", None),
    ("trim", "aileron_right", None),
    ("trim", "aileron_set", 50),
    # deice
    ("deice", "pitot", None),
    ("deice", "pitot_heat", None),
    ("deice", "structural", None),
    ("deice", "airframe", None),
    ("deice", "windshield", None),
    ("deice", "props", None),
    ("deice", "prop_deice", None),
    # parking_brake
    ("parking_brake", "toggle", None),
    # spoilers
    ("spoilers", "toggle", None),
    ("spoilers", "set", 50),
    # mixture / propeller
    ("mixture", "set", 100),
    ("propeller", "set", 100),
    # fuel_selector
    ("fuel_selector", "off", None),
    ("fuel_selector", "all", None),
    ("fuel_selector", "both", None),
    ("fuel_selector", "left", None),
    ("fuel_selector", "right", None),
    ("fuel_selector", "set", 1),
    # crossfeed
    ("crossfeed", "open", None),
    ("crossfeed", "on", None),
    ("crossfeed", "close", None),
    ("crossfeed", "off", None),
    ("crossfeed", "toggle", None),
    # --- deferred to CMD-09: resolvable but not exposed in the tool enum ---
    ("magnetos", "off", None),
    ("magnetos", "right", None),
    ("magnetos", "left", None),
    ("magnetos", "both", None),
    ("magnetos", "start", None),
    ("carb_heat", "on", None),
    ("carb_heat", "off", None),
    ("carb_heat", "toggle", None),
    ("fuel_pump", "on", None),
    ("fuel_pump", "off", None),
    ("fuel_pump", "toggle", None),
    ("starter", "engage", None),
    ("starter", "start", None),
    ("primer", "prime", None),
    ("primer", "pump", None),
    ("lights", "landing", None),
    ("lights", "landing_on", None),
    ("lights", "taxi", None),
    ("lights", "taxi_on", None),
    ("lights", "nav", None),
    ("lights", "navigation", None),
    ("lights", "beacon", None),
    ("lights", "strobe", None),
    ("lights", "panel", None),
)

# The six systems held back from the tool enum until the authority gate
# (plan 02-04) and the procedure re-route (plan 02-07) land -- see D-01.
CMD09_EVENTS = frozenset(
    {
        "MAGNETO_SET",
        "ANTI_ICE_CARB_HEAT_TOGGLE",
        "FUEL_PUMP_TOGGLE",
        "TOGGLE_STARTER1",
        "TOGGLE_PRIMER",
        "LANDING_LIGHTS_TOGGLE",
        "TOGGLE_TAXI_LIGHTS",
        "TOGGLE_NAV_LIGHTS",
        "TOGGLE_BEACON_LIGHTS",
        "STROBES_TOGGLE",
        "PANEL_LIGHTS_TOGGLE",
    }
)


def _events_by_system() -> dict[str, set[str]]:
    """Run the branch table through the resolver, grouped by system."""
    events: dict[str, set[str]] = {}
    for system, action, value in RESOLVER_BRANCH_TABLE:
        event, _ = _resolve_command(system, action, value)
        assert event is not None, (
            f"_resolve_command({system!r}, {action!r}, {value!r}) resolved to None. "
            "The branch table in this file no longer matches tools.py."
        )
        events.setdefault(system, set()).add(event)
    return events


def _exposed_systems() -> set[str]:
    """The `system` enum from the set_aircraft_control tool definition."""
    for tool in TOOL_DEFINITIONS:
        if tool["name"] == "set_aircraft_control":
            return set(tool["input_schema"]["properties"]["system"]["enum"])
    raise AssertionError(
        "TOOL_DEFINITIONS no longer defines set_aircraft_control. If the tool was "
        "renamed, this guard must be updated -- it is the only thing checking that "
        "what Claude can name is what the adapter can execute."
    )


# ---------------------------------------------------------------------------
# Guards
# ---------------------------------------------------------------------------


@requires_adapter
def test_every_enum_exposed_event_has_an_adapter_handler() -> None:
    """Anything Claude can name must be something the adapter can execute."""
    registered = _registered_events()
    by_system = _events_by_system()

    missing: dict[str, set[str]] = {}
    for system in sorted(_exposed_systems()):
        assert system in by_system, (
            f"the set_aircraft_control enum exposes {system!r} but the branch table "
            "in this file has no rows for it, so its events are unchecked"
        )
        gaps = by_system[system] - registered
        if gaps:
            missing[system] = gaps

    assert not missing, (
        "these systems are exposed in the set_aircraft_control enum but resolve to "
        "SimConnect events the MSFS adapter has no CommandMap entry for: "
        + "; ".join(f"{system} -> {sorted(events)}" for system, events in sorted(missing.items()))
        + ". ExecuteCommand will log 'Unknown command' and ack success:false, but "
        "MERLIN reports the action as taken -- the pilot is told de-ice is on when "
        "it is not. Register them in adapters/msfs/SimConnectManager.cs (CMD-07)."
    )


@requires_adapter
def test_cmd09_systems_are_not_registered() -> None:
    """The deferred systems must stay out of the adapter's write surface."""
    registered = _registered_events()
    leaked = sorted(CMD09_EVENTS & registered)

    assert not leaked, (
        f"the MSFS adapter registers CMD-09 events that must stay deferred: {leaked}. "
        "execute_procedure bypasses the set_aircraft_control enum entirely and "
        'PROCEDURES["shutdown"] contains a magnetos step, so registering MAGNETO_SET '
        "before the authority gate (plan 02-04) and the procedure re-route "
        "(plan 02-07) land turns a named tool call into a working in-flight engine "
        "shutdown with nothing in front of it (D-01)."
    )


def test_resolver_branch_table_is_exhaustive() -> None:
    """No resolver branch may hide from the table above.

    Without this, adding an event to ``_resolve_command`` and forgetting a table
    row would leave the new event unchecked by the parity guard -- exactly the
    silence that let CMD-07 happen.
    """
    from_table = {event for events in _events_by_system().values() for event in events}
    from_source = set(_RESOLVER_LITERAL.findall(inspect.getsource(_resolve_command)))

    unexercised = sorted(from_source - from_table)
    assert not unexercised, (
        f"_resolve_command can return {unexercised} but no row in "
        "RESOLVER_BRANCH_TABLE produces them, so the parity guard never checks "
        "whether the adapter can execute them. Add a (system, action, value) row."
    )

    stale = sorted(from_table - from_source)
    assert not stale, (
        f"RESOLVER_BRANCH_TABLE produces {stale}, which no longer appears as a "
        "literal in _resolve_command. Either the regex needs updating or the table "
        "is stale."
    )
