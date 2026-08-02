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
from orchestrator.command_safety import DEFAULT_RULES
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
    # parking_brake -- `toggle` is the ONLY resolvable action, deliberately.
    # "on", "off", "release", "set", "apply" and "engage" resolve to None and are
    # refused by UNCONFIRMABLE_REFUSED_ACTIONS in tools.py: no telemetry reports
    # brake position, so an absolute request cannot be turned into the right
    # direction and a toggle would set the brake on landing rollout (CR-04).
    # Adding a row here for any of them would re-assert the defect -- and would
    # fail, because _events_by_system() asserts every row resolves.
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


# ---------------------------------------------------------------------------
# Safety-rule coverage of the reachable command surface
# ---------------------------------------------------------------------------

# Reachable events that deliberately carry no SafetyRule. An entry here is a
# *classification*, not a shrug: it asserts that no telemetry-conditioned
# hazard exists for this event, so there is nothing a rule could usefully key
# on. Grouped by why.
SAFETY_EXEMPT_EVENTS: frozenset[str] = frozenset(
    {
        # Avionics tuning. A wrong frequency is a communications problem, not
        # an airframe one -- nothing about the flight envelope makes any value
        # unsafe, and validation.py already range-checks the numbers.
        "COM_RADIO_SET_HZ",
        "COM2_RADIO_SET_HZ",
        "NAV1_RADIO_SET_HZ",
        "NAV2_RADIO_SET_HZ",
        "KOHLSMAN_SET",
        "HEADING_BUG_SET",
        # Autopilot mode arming and target setting. AP_MASTER -- the one that
        # actually hands control over -- is ruled. These arm a mode or set a
        # target within an already-engaged autopilot; validation.py checks the
        # target values against per-aircraft limits.
        "AP_HDG_HOLD",
        "AP_ALT_HOLD",
        "AP_VS_HOLD",
        "AP_APR_HOLD",
        "AP_NAV1_HOLD",
        "AP_AIRSPEED_HOLD",
        "AP_ALT_VAR_SET_ENGLISH",
        "AP_VS_VAR_SET_ENGLISH",
        "AP_SPD_VAR_SET",
        # Trim. Incremental, continuously pilot-correctable, and no telemetry
        # threshold distinguishes a safe trim input from an unsafe one.
        "AILERON_TRIM_LEFT",
        "AILERON_TRIM_RIGHT",
        "AILERON_TRIM_SET",
        "ELEVATOR_TRIM_SET",
        "ELEV_TRIM_UP",
        "ELEV_TRIM_DN",
        "RUDDER_TRIM_LEFT",
        "RUDDER_TRIM_RIGHT",
        "RUDDER_TRIM_SET",
        # Ice protection. These are toggles whose *on* direction is the safe
        # one; switching them off during icing would be the hazard, but no
        # icing condition exists anywhere in the telemetry chain to key on.
        # Revisit if icing telemetry is ever added.
        "PITOT_HEAT_TOGGLE",
        "TOGGLE_PROPELLER_DEICE",
        "TOGGLE_STRUCTURAL_DEICE",
        "WINDSHIELD_DEICE_TOGGLE",
    }
)

# Reachable events that SHOULD have a rule and do not. This is a declared
# debt list, not an exemption list -- each entry names a real unguarded path.
# The guard below tolerates these so the suite stays green, but they are
# written down here rather than living as an unnoticed absence, which is
# exactly how Gap 2 happened (02-VERIFICATION.md): CMD-07 widened the
# reachable surface and DEFAULT_RULES was never widened to match.
#
# Each needs a threshold decision that is the owner's call, not a mechanical
# fix. Emptying this set is the goal.
UNGUARDED_KNOWN_GAPS: frozenset[str] = frozenset(
    {
        # Retracting flaps at low speed on approach is the hazard; FLAPS_INCR
        # is ruled for overspeed but its opposite has no floor.
        "FLAPS_DECR",
        # Spoiler deployment in flight. Needs a phase/altitude threshold.
        "SPOILERS_SET",
        "SPOILERS_TOGGLE",
        # Propeller feathering. Needs an airborne + RPM condition.
        "PROP_PITCH_SET",
        # Tank selection. FUEL_SELECTOR_OFF and _SET(0) are blocked airborne;
        # selecting a specific tank is far milder but still uncommanded fuel
        # system reconfiguration with nothing checking fuel quantity per tank.
        "FUEL_SELECTOR_ALL",
        "FUEL_SELECTOR_LEFT",
        "FUEL_SELECTOR_RIGHT",
    }
)


def _ruled_events() -> set[str]:
    """Every SimConnect event name some SafetyRule applies to."""
    ruled: set[str] = set()
    for rule in DEFAULT_RULES:
        ruled.update(rule.commands)
    return ruled


def _enum_reachable_events() -> set[str]:
    """Events Claude can actually cause, via an enum-exposed system."""
    by_system = _events_by_system()
    reachable: set[str] = set()
    for system in _exposed_systems():
        reachable |= by_system.get(system, set())
    return reachable


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


def test_every_reachable_command_is_ruled_or_classified() -> None:
    """Widening the command surface must force a safety decision.

    This is the guard Gap 2 did not have. Plan 02-02 (CMD-07) made ~20 dead
    events reachable, including ``FUEL_SELECTOR_OFF``; ``DEFAULT_RULES`` still
    covered only gear, flaps, autopilot and throttle. Both changes were correct
    in isolation, they landed in different waves, and nothing compared them --
    so at the default ``AUTHORITY_LEVEL=full`` an in-flight fuel cutoff had
    nothing in front of it.

    The fix is not "every event needs a rule" -- most genuinely do not. It is
    that every event must be *consciously* placed: ruled, exempt with a stated
    reason, or named as a known gap. Silence is the failure mode.
    """
    unclassified = sorted(
        _enum_reachable_events() - _ruled_events() - SAFETY_EXEMPT_EVENTS - UNGUARDED_KNOWN_GAPS
    )

    assert not unclassified, (
        f"these events are reachable through the set_aircraft_control enum but appear "
        f"in neither DEFAULT_RULES, SAFETY_EXEMPT_EVENTS, nor UNGUARDED_KNOWN_GAPS: "
        f"{unclassified}. At AUTHORITY_LEVEL=full a command with no rule can never be "
        "'blocked', so 'execute unless blocked' is vacuous for it. Either add a "
        "SafetyRule, or classify it in this file with the reason no rule is needed. "
        "Do not add it to UNGUARDED_KNOWN_GAPS without an owner decision -- that set "
        "is debt being paid down, not a parking space (Gap 2, 02-VERIFICATION.md)."
    )


def test_safety_classification_tables_are_not_stale() -> None:
    """Classification entries must still describe reality.

    Without this, an event that gained a rule would linger in the exempt set
    and an event that stopped being reachable would keep a stale justification
    -- the tables would slowly stop meaning anything, which is the failure mode
    they exist to prevent.
    """
    reachable = _enum_reachable_events()
    ruled = _ruled_events()

    unreachable = sorted((SAFETY_EXEMPT_EVENTS | UNGUARDED_KNOWN_GAPS) - reachable)
    assert not unreachable, (
        f"these events are classified in this file but are no longer reachable through "
        f"the enum: {unreachable}. Remove the entries -- a justification for something "
        "that cannot happen is noise that makes the real entries harder to trust."
    )

    now_ruled = sorted((SAFETY_EXEMPT_EVENTS | UNGUARDED_KNOWN_GAPS) & ruled)
    assert not now_ruled, (
        f"these events now have a SafetyRule but are still listed as exempt or as a "
        f"known gap: {now_ruled}. Remove them from the classification tables so the "
        "debt list reflects what is actually still unguarded."
    )
