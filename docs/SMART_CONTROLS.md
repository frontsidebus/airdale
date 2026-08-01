# Smart Controls -- Phase 3

Phase 3 adds four capabilities to MERLIN's aircraft control pipeline: **command verification**, **safety interlocks**, **multi-step procedures**, and **command undo**. Together, these transform `set_aircraft_control` from a simple pass-through into a closed-loop control system that validates before execution, confirms after execution, chains compound actions, and allows the pilot to reverse mistakes.

Source files:
- `orchestrator/orchestrator/command_verifier.py` -- Post-execution telemetry verification
- `orchestrator/orchestrator/command_safety.py` -- Pre-execution safety interlocks
- `orchestrator/orchestrator/procedures.py` -- Multi-step procedure definitions and executor
- `orchestrator/orchestrator/command_history.py` -- Command history and undo logic
- `orchestrator/orchestrator/authority.py` -- Authority level and the reason it holds (see [Authority](#authority))

---

## Command Verification

After a SimConnect command is acknowledged by the adapter, MERLIN polls telemetry to confirm the aircraft actually changed state. SimConnect acknowledgments only mean the sim received the command -- they do not guarantee the aircraft responded. Gear will not extend above Vle, autopilot will not engage without a valid nav source, and throttle changes may not register if the engine is dead.

### How It Works

```
set_aircraft_control("gear", "down")
    |
    +--> Snapshot sim state (before)
    +--> Send command via telemetry service
    +--> SimConnect ACK received
    +--> CommandVerifier.verify_command() begins polling
    |       |
    |       +--> Sleep poll_interval (0.5s)
    |       +--> Read current sim state (after)
    |       +--> Run verification check: compare expected vs actual
    |       +--> If verified: return success
    |       +--> If not verified and timeout not reached: loop
    |       +--> If timeout reached: return failure
    |
    +--> Claude receives VerificationResult
    +--> Claude reports outcome to pilot
```

The `CommandVerifier` takes a `TelemetryClient`, a configurable timeout (default 3.0 seconds), and a poll interval (default 0.5 seconds). After sending a command, it repeatedly reads telemetry and runs the appropriate verification check until the state change is confirmed or the timeout expires.

### Verification Rules

Each verified command has a dedicated check function that compares pre-execution and post-execution sim state.

| Command | What Is Checked | Tolerance | Failure Message |
|---|---|---|---|
| `GEAR_DOWN` | `gear_handle == True` | Exact | "Gear failed to extend." |
| `GEAR_UP` | `gear_handle == False` | Exact | "Gear failed to retract." |
| `FLAPS_SET` | `flaps_percent` matches target | +/- 5% | "Flaps at X%, expected ~Y%." |
| `AP_MASTER` | `autopilot.master` toggled from previous | Exact | "Autopilot did not toggle." |
| `HEADING_BUG_SET` | `autopilot.heading` matches value | +/- 1 deg (wraps at 360) | "Heading bug at X, expected Y." |
| `AP_ALT_VAR_SET_ENGLISH` | `autopilot.altitude` matches value | +/- 50 ft | "Altitude selector at X, expected Y." |
| `THROTTLE_SET` | Engine RPM moved in the expected direction | +/- 50 RPM settling | "Throttle may not have responded." |

Commands without a registered verification check are assumed successful. This is by design -- we verify what we can measure and do not block commands we cannot confirm.

### Verification Failure Behavior

When verification fails, the `VerificationResult` is returned to Claude as part of the tool result. Claude then communicates the issue to the pilot in natural language. For example:

> "Gear down command sent, but the gear hasn't extended. Might be above Vle -- check your airspeed, currently showing 185 knots."

MERLIN does not automatically retry failed commands. The pilot decides what to do next.

### Timeout Behavior

- **Default timeout:** 3.0 seconds
- **Poll interval:** 0.5 seconds (up to 6 polls per verification)
- If the timeout expires without confirmation, the last check result is returned with a timeout message prepended
- If no telemetry is received during the entire timeout window (e.g., connection lost), a distinct "no telemetry available" result is returned

### Configuration

The timeout and poll interval are constructor parameters on `CommandVerifier`:

```python
verifier = CommandVerifier(
    sim_client=telemetry_client,
    timeout=5.0,        # Wait up to 5 seconds
    poll_interval=0.25,  # Poll every 250ms
)
```

---

## Safety Interlocks

Before any command reaches SimConnect, the `CommandSafetyCheck` evaluates it against the current flight state to prevent dangerous actions. Safety rules are data-driven -- each rule is a `SafetyRule` dataclass with a condition function, a severity level, and a message template.

### Severity Levels

| Severity | Behavior | Example |
|---|---|---|
| `blocked` | Command is **not sent** to SimConnect. Claude explains why. | Gear up while on the ground |
| `warning` | Command **proceeds** but Claude includes an advisory. | Gear extension at 190 kt |

Blocked rules short-circuit -- the first matching block stops evaluation. Warning rules accumulate -- all triggered warnings are joined and returned to Claude.

### Safety Rules Reference

| Rule | Commands | Condition | Severity |
|---|---|---|---|
| `gear_up_on_ground` | `GEAR_UP` | Aircraft is on the ground | **blocked** |
| `gear_up_too_low` | `GEAR_UP` | AGL < 200 ft and airborne | **blocked** |
| `gear_down_too_fast` | `GEAR_DOWN` | IAS > 180 kt | warning |
| `flaps_above_vfe` | `FLAPS_SET`, `FLAPS_1-3`, `FLAPS_FULL`, `FLAPS_INCR` | IAS > Vfe (aircraft-specific) | warning |
| `flaps_full_at_cruise_speed` | `FLAPS_SET`, `FLAPS_FULL` | Full flaps (value >= 16383) and IAS > 150 kt | warning |
| `ap_disconnect_low` | `AP_MASTER` | Autopilot is ON and AGL < 500 ft, airborne | warning |
| `throttle_idle_on_approach` | `THROTTLE_SET` | Throttle < 10% during approach phase, AGL > 100 ft | warning |

### Aircraft-Specific Limits

The `flaps_above_vfe` rule uses the `AircraftLimits` database (from `validation.py`) to look up the Vfe for the current aircraft type. When the aircraft type is known, the Vfe comes from the database. When unknown, the rule is skipped (Vfe defaults to 0, and the condition requires IAS > Vfe > 0).

Supported aircraft types: C172, C152, PA28, SR22, DA40, B738, A320.

### How Claude Communicates Safety Decisions

**Blocked commands** -- Claude explains the block and does not execute:

> "Negative on gear up -- we're still on the ground. I'll get the gear once we're airborne and have some altitude."

**Warning commands** -- Claude executes but adds an advisory:

> "Gear coming down, but heads up -- we're at 190 knots, above the 180 knot gear limit. Might want to bleed some speed first."

### Adding a Custom Safety Rule

Create a `SafetyRule` and add it to the checker at startup:

```python
from orchestrator.command_safety import CommandSafetyCheck, SafetyRule
from orchestrator.sim_client import SimState
from orchestrator.validation import AircraftLimits

def _flaps_in_icing(
    cmd: str, val: int, state: SimState, limits: AircraftLimits | None
) -> bool:
    """Block flap extension when icing conditions are detected."""
    return state.environment.oat < 5 and state.environment.in_cloud

custom_rule = SafetyRule(
    name="flaps_in_icing",
    commands={"FLAPS_SET", "FLAPS_1", "FLAPS_2", "FLAPS_3", "FLAPS_FULL", "FLAPS_INCR"},
    condition=_flaps_in_icing,
    severity="warning",
    message_template="Flap extension in possible icing conditions (OAT {oat}C, in cloud)",
)

checker = CommandSafetyCheck()
checker.add_rule(custom_rule)
```

The condition function signature is always `(command: str, value: int, state: SimState, limits: AircraftLimits | None) -> bool`. Return `True` when the unsafe condition is detected.

The `message_template` supports these format variables: `{command}`, `{ias}`, `{agl}`, `{phase}`, `{vfe}`.

---

## Authority

Safety interlocks answer *"is this command safe right now?"*. Authority answers a different question: *"may MERLIN act at all?"* The two compose. The safety check runs first and its verdict is an **input** to the authority decision, which is why the authority gate lives inside `set_aircraft_control` -- the one point where the resolved SimConnect event, live telemetry, and the `SafetyResult` all exist and nothing has been transmitted yet.

Enforcement is a code branch, never prompt text. MERLIN is not asked to respect the authority level; the tool refuses to transmit. A guard that lives in the system prompt is defeated by anything that reaches the conversation.

### Authority Levels

There are exactly three levels, set by `AUTHORITY_LEVEL` (default `full`, so upgrading changes no behaviour -- restriction is opt-in).

| Level | Clean verdict | `warning` verdict | `blocked` verdict |
|---|---|---|---|
| `full` | Executes | Executes, with the advisory attached | Refused |
| `assisted` | Executes | **Withheld** -- MERLIN defers to the pilot | Refused |
| `advisory` | **Dry run** -- describes the action, sends nothing | Dry run, describing the action and the concern | Refused |

Note the column for `blocked`: **`blocked` wins at every level.** The safety short-circuit runs before the authority gate, so a blocked command reports as blocked regardless of authority. Authority can only ever reduce what gets sent, never widen it.

The two restricted outcomes are reported to Claude as decisions, not failures:

- **Advisory dry run** -- `{"advisory": true, "would_execute": "GEAR_DOWN", ...}`. Carries no `error` key, because it is not an error; the aircraft is simply the pilot's.
- **Assisted withhold** -- `{"withheld": true, "command": "GEAR_DOWN", ...}`. Also carries no `error` key. The phrasing MERLIN relays makes clear it is deferring, not that the command failed.

### Why Authority Is Restricted -- the Four Reasons

A level travels with the reason it holds that value, because "MERLIN is only advising" means something different to a pilot depending on the cause.

| Reason | Meaning | How it clears |
|---|---|---|
| `config` | The level the operator asked for | Change `AUTHORITY_LEVEL` |
| `override` | The pilot moved a control themselves; MERLIN is standing off | Rolling cooldown (`AUTHORITY_OVERRIDE_COOLDOWN_S`) lapses |
| `watchdog` | The command path stopped acknowledging -- MERLIN cannot reach the sim | Latched; cleared out of band, e.g. on reconnect |
| `degraded` | The authority subsystem itself failed to start | Terminal for the process lifetime |

`degraded` is a **reason, not a level.** A composition root that cannot build a real authority state substitutes `AuthorityState.degraded_fallback(...)`, which is permanently advisory. Making it a fourth *level* would have threaded it through the gate, the transport floor, the status endpoint, the UI, and every test; as a reason it threads only through the display. That is also why the level set is deliberately three -- a fourth authority state was considered and rejected.

Anything that branches on the reason needs a `degraded` arm. A missing branch does not error, it renders a failed authority subsystem as a deliberate `advisory` configuration -- the pilot then reads a fault as a setting.

### Coverage Caveat -- `assisted` Is Weaker Than It Sounds

**`assisted` withholds only on a `warning`-severity safety verdict.** If no rule fires, there is nothing to withhold on, and the command executes exactly as it would at `full`.

`DEFAULT_RULES` contains **7 rules, covering 4 systems**: gear, flaps, autopilot, and throttle. `_resolve_command` handles **20** commandable systems. For the other **16** -- including `mixture` (idle cutoff), `fuel_selector` (`off` starves the engine), `crossfeed`, and `deice` -- no `warning` rule exists, so **`assisted` behaves identically to `full` for those systems.**

This follows correctly from an explicit non-goal: the authority phase deliberately added no new envelope rules, because authority and envelope protection are separate concerns and conflating them would have made both harder to reason about. It is not a defect in the authority layer -- the gate does exactly what it is specified to do. Closing the gap means adding safety rules for the remaining systems, which is tracked as a follow-on `SAFE-*` item.

Read plainly: **do not treat `assisted` as broad protection today.** It is real protection for gear, flaps, autopilot, and throttle, and it is a no-op everywhere else. Use `advisory` if you want MERLIN to touch nothing.

### Commands MERLIN Refuses Outright -- `carb_heat` and `fuel_pump`

Independent of authority level, `carb_heat` and `fuel_pump` refuse an absolute `on` or `off`:

```
set_aircraft_control("carb_heat", "off")
  -> {"error": "I cannot confirm the current position of the carb heat ...",
      "unresolvable": true}
```

**Why.** Both systems map `"on"`, `"off"` and `"toggle"` to the *same* SimConnect toggle event (`ANTI_ICE_CARB_HEAT_TOGGLE`, `FUEL_PUMP_TOGGLE`). Emitting a toggle in response to "carb heat off" turns carb heat **on** whenever it was already off -- the command does the opposite of what was asked, which in icing conditions is a real hazard.

The obvious fix -- emit the toggle only when the requested state differs from the current one -- is not implementable. There is no carb-heat or fuel-pump position anywhere in the telemetry chain: not in the SimConnect data definition, the adapter model, the universal schema, `SurfaceState`, or the mock adapter. There is nothing to read. Adding it is a four-layer change that is deliberately deferred.

**Workaround.** `action="toggle"` works normally and is unaffected. Tell MERLIN what the panel shows if you need a specific position:

> "Carb heat is currently off, toggle it on."

---

## Multi-Step Procedures

Multi-step procedures chain several `set_aircraft_control` commands into a single named action. When a pilot says "configure for landing," MERLIN executes gear down, flaps full, and landing lights on as a coordinated sequence rather than requiring three separate commands.

### Pre-Defined Procedures

#### `landing_config` -- Configure for Landing

| Step | System | Action | Delay |
|---|---|---|---|
| 1 | Gear | Down | 500 ms |
| 2 | Flaps | Full | 500 ms |
| 3 | Lights | Landing on | -- |

**Voice commands:** "Configure for landing", "Landing configuration", "Set up for landing"

#### `takeoff_config` -- Configure for Takeoff

| Step | System | Action | Delay |
|---|---|---|---|
| 1 | Flaps | 10 | 500 ms |
| 2 | Lights | Landing on | 500 ms |
| 3 | Fuel Pump | On | -- |

**Voice commands:** "Configure for takeoff", "Takeoff config"

#### `cleanup_after_takeoff` -- Post-Takeoff Cleanup

| Step | System | Action | Delay |
|---|---|---|---|
| 1 | Gear | Up | 500 ms |
| 2 | Flaps | Up | 500 ms |
| 3 | Lights | Landing off | -- |

**Voice commands:** "Clean up", "After takeoff cleanup", "Gear and flaps up"

#### `go_around` -- Go Around

| Step | System | Action | Delay |
|---|---|---|---|
| 1 | Throttle | 100% | 500 ms |
| 2 | Flaps | 10 | 500 ms |
| 3 | Gear | Up | 500 ms |
| 4 | Lights | Landing on | -- |

**Voice commands:** "Go around", "Going around", "Missed approach"

#### `shutdown` -- Engine Shutdown

| Step | System | Action | Delay |
|---|---|---|---|
| 1 | Throttle | Idle (0%) | 500 ms |
| 2 | Mixture | Cutoff (0%) | 500 ms |
| 3 | Magnetos | Off | 500 ms |
| 4 | Lights | Off | -- |

**Voice commands:** "Shut down", "Engine shutdown", "Shut it down"

#### `cruise_config` -- Configure for Cruise

| Step | System | Action | Delay |
|---|---|---|---|
| 1 | Flaps | Up | 500 ms |
| 2 | Lights | Landing off | -- |

**Voice commands:** "Cruise configuration", "Configure for cruise", "Clean configuration"

### How Procedures Execute

The `ProcedureExecutor` runs steps sequentially with configurable delays between them:

1. For each step, `_resolve_command()` translates the system/action/value into a SimConnect event and value
2. The command is sent to the sim via `TelemetryClient.send_command()`
3. If `delay_ms > 0` and more steps remain, the executor waits before continuing
4. Results for every step are collected into a `ProcedureResult`

### Error Handling

**Critically, a failed step does not abort the procedure.** Stopping mid-procedure could leave the aircraft in a worse configuration than completing the remaining steps. For example, if gear fails to extend during `landing_config`, MERLIN still sets flaps and landing lights -- those are needed regardless.

Each step's success or failure is recorded in the `ProcedureResult`. Claude receives the full results and reports the outcome:

> "Landing configuration set. Flaps full, landing lights on. Note: gear command was acknowledged but I'll verify it extended -- check your gear indicators."

If a step fails because the system/action cannot be resolved (unknown control), the error is logged and the procedure continues.

### Adding Custom Procedures

Add a new `Procedure` to the `PROCEDURES` dictionary in `procedures.py`:

```python
PROCEDURES["short_final"] = Procedure(
    name="short_final",
    description="Short final configuration: gear down, flaps full, lights on, speed brakes armed",
    steps=[
        ProcedureStep(system="gear", action="down", description="Gear down", delay_ms=500),
        ProcedureStep(system="flaps", action="full", description="Flaps full", delay_ms=500),
        ProcedureStep(system="lights", action="landing", description="Landing lights", delay_ms=500),
        ProcedureStep(system="spoilers", action="toggle", description="Speed brakes armed", delay_ms=0),
    ],
)
```

Each `ProcedureStep` has:

| Field | Type | Description |
|---|---|---|
| `system` | `str` | System name matching `_resolve_command()` (e.g., `"gear"`, `"flaps"`, `"throttle"`) |
| `action` | `str` | Action name (e.g., `"down"`, `"set"`, `"toggle"`) |
| `value` | `float \| None` | Optional value for `set` actions (percentage, degrees, etc.) |
| `delay_ms` | `int` | Milliseconds to wait before the next step (default 500) |
| `description` | `str` | Human-readable step label for logging and Claude's response |

### Procedure Discovery

Claude can list available procedures via the `list_procedures()` function, which returns a summary of all registered procedures. The pilot can also ask "what procedures do you have?" and MERLIN will enumerate them.

---

## Command Undo

The `CommandHistory` module tracks every command MERLIN executes and generates reverse actions for "cancel that" / "undo" requests. When a command is executed, a snapshot of the relevant sim state is captured *before* execution so the previous value can be restored.

### How Undo Works

```
1. Pilot: "Set heading to 270"
   --> CommandHistory.record(HEADING_BUG_SET, 270, state_before)
       state_before snapshot: {autopilot.heading: 180}

2. Pilot: "Cancel that"
   --> CommandHistory.get_undo_action()
       --> Finds HEADING_BUG_SET in state-restore commands
       --> Returns ("autopilot", "heading", 180.0)
   --> MERLIN executes set_aircraft_control("autopilot", "heading", 180)
   --> CommandHistory.pop_last()  # Remove the undone command
```

### Undo Strategies

The undo system uses four strategies depending on the command type:

| Strategy | How It Works | Examples |
|---|---|---|
| **Inverse pair** | Issues the opposite command | `GEAR_DOWN` undoes with `GEAR_UP`, and vice versa |
| **Toggle** | Re-issues the same command | Landing lights, parking brake, pitot heat, spoilers toggle |
| **State restore** | Restores the pre-command value from snapshot | Flaps, heading bug, altitude selector, throttle, trim, barometer |
| **AP_MASTER** | Special case -- re-toggles based on whether AP was on or off before | Autopilot on/off |

### Which Commands Are Undoable

**Undoable via inverse pair:**

| Command | Undo Action |
|---|---|
| `GEAR_DOWN` | Gear up |
| `GEAR_UP` | Gear down |
| `CROSS_FEED_OPEN` | Crossfeed close |
| `CROSS_FEED_OFF` | Crossfeed open |

**Undoable via toggle (re-issue same command):**

All toggle commands: `LANDING_LIGHTS_TOGGLE`, `TOGGLE_TAXI_LIGHTS`, `TOGGLE_NAV_LIGHTS`, `TOGGLE_BEACON_LIGHTS`, `STROBES_TOGGLE`, `PANEL_LIGHTS_TOGGLE`, `PITOT_HEAT_TOGGLE`, `TOGGLE_STRUCTURAL_DEICE`, `WINDSHIELD_DEICE_TOGGLE`, `TOGGLE_PROPELLER_DEICE`, `ANTI_ICE_CARB_HEAT_TOGGLE`, `FUEL_PUMP_TOGGLE`, `SPOILERS_TOGGLE`, `CROSS_FEED_TOGGLE`, `PARKING_BRAKES`, `GEAR_TOGGLE`.

**Undoable via state restore:**

| Command | Restores From |
|---|---|
| `FLAPS_SET` | `surfaces.flaps_percent` |
| `HEADING_BUG_SET` | `autopilot.heading` |
| `AP_ALT_VAR_SET_ENGLISH` | `autopilot.altitude` |
| `AP_VS_VAR_SET_ENGLISH` | `autopilot.vertical_speed` |
| `AP_SPD_VAR_SET` | `autopilot.airspeed` |
| `THROTTLE_SET` | Previous throttle position |
| `SPOILERS_SET` | `surfaces.spoilers_percent` |
| `ELEVATOR_TRIM_SET` | Previous trim value |
| `KOHLSMAN_SET` | `environment.barometer_inhg` |

**Not undoable:**

These commands are inherently non-reversible -- incremental actions with no absolute reference point:

`TOGGLE_STARTER1`, `TOGGLE_PRIMER`, `FLAPS_1`, `FLAPS_2`, `FLAPS_3`, `FLAPS_INCR`, `FLAPS_DECR`, `ELEV_TRIM_UP`, `ELEV_TRIM_DN`, `RUDDER_TRIM_LEFT`, `RUDDER_TRIM_RIGHT`, `AILERON_TRIM_LEFT`, `AILERON_TRIM_RIGHT`

When the pilot tries to undo a non-reversible command, Claude explains why:

> "Can't undo that one -- flaps increment doesn't have a fixed reference point to go back to. Tell me what flap setting you want and I'll set it directly."

### Voice Commands for Undo

| Voice Command | What Happens |
|---|---|
| "Cancel that" | Undoes the last command |
| "Undo" | Undoes the last command |
| "Put that back" | Undoes the last command |
| "Undo the last command" | Undoes the last command |
| "Never mind" | Undoes the last command |

### History Depth

The command history maintains a ring buffer of the **20 most recent** commands (configurable via `max_history`). Only the most recent command can be undone -- there is no multi-level undo stack. After an undo, the undone command is removed from history via `pop_last()`.

The `get_recent(n)` method returns the N most recent commands (newest first), which Claude can use to answer questions like "what did you just do?" or "what commands have you run?"

---

## Command Pipeline Overview

With all four features active, the full command execution pipeline is:

```
Pilot: "Gear up"
    |
    v
1. SAFETY CHECK (command_safety.py)
   +--> Evaluate all matching SafetyRules
   +--> If blocked: return error to Claude, command NOT sent
   +--> If warning: proceed with advisory message
    |
    v
2. AUTHORITY GATE (authority.py, enforced in tools.py)
   +--> advisory: return a dry-run description, command NOT sent
   +--> assisted + warning: withhold, command NOT sent
   +--> otherwise: proceed
    |
    v
3. STATE SNAPSHOT (command_history.py)
   +--> Capture relevant sim state before execution
    |
    v
4. EXECUTE (tools.py -> sim_client.py -> telemetry service -> adapter)
   +--> _resolve_command() translates to SimConnect event
   +--> Send via WebSocket to telemetry service
   +--> Adapter executes via SimConnect
   +--> ACK returned
    |
    v
5. RECORD (command_history.py)
   +--> Store command + pre-state snapshot in history ring buffer
    |
    v
6. VERIFY (command_verifier.py)
   +--> Poll telemetry for up to 3 seconds
   +--> Compare expected vs actual state
   +--> Return VerificationResult to Claude
    |
    v
7. REPORT
   +--> Claude reports outcome to pilot
   +--> Includes safety warnings, verification status, and any failures
```

For multi-step procedures, steps 1-6 execute for each step in sequence, with configurable delays between steps. The full `ProcedureResult` is returned to Claude after all steps complete.

For undo, the history is consulted, a reverse action is generated, and that action goes through the same pipeline (safety check, authority gate, execute, verify). An undo is a command like any other -- at `advisory` it is described, not sent.
