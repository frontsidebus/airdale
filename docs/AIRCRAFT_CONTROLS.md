# Aircraft Controls Reference

Reference for every system, action, and value MERLIN can control via the `set_aircraft_control` tool.

**14 systems are reachable. They resolve to 52 distinct SimConnect events, and the MSFS adapter registers a handler for every one of them.**

Reachable means all three of these agree:

1. the system appears in the `set_aircraft_control` `system` enum in `orchestrator/orchestrator/claude_client.py`, so Claude can name it;
2. `_resolve_command` in `orchestrator/orchestrator/tools.py` maps it to a SimConnect event name;
3. `CommandMap` in `adapters/msfs/SimConnectManager.cs` has an entry for that event name, so `ExecuteCommand` reaches `TransmitClientEvent`.

Six further systems satisfy (2) only — see [Deferred systems](#deferred-systems-cmd-09).

> **This document is pinned by tests.** `orchestrator/tests/test_command_coverage.py` fails
> in CI if any enum-exposed system resolves to an event the adapter cannot execute, or if a
> deferred system is registered early. `adapters/msfs/SimConnectBridge.Tests/CommandMapTests.cs`
> pins the adapter side of the same contract. The counts above were drifting fiction before
> those guards existed; do not update this file without them passing.

Voice command examples shown for each — MERLIN executes immediately on unambiguous direct orders.

---

## Flight Controls

### Flaps
| Action | Voice Example | SimConnect Event | Value |
|---|---|---|---|
| `up` / `retract` | "Flaps up" | FLAPS_SET | 0 |
| `full` / `down` | "Give me full flaps" | FLAPS_SET | 16383 |
| `1` / `10` | "Flaps one" | FLAPS_1 | — |
| `2` / `20` | "Flaps two" | FLAPS_2 | — |
| `3` / `30` | "Flaps three" | FLAPS_3 | — |
| `incr` / `increase` | "More flaps" | FLAPS_INCR | — |
| `decr` / `decrease` | "Less flaps" | FLAPS_DECR | — |
| `set` | "Set flaps to 25 percent" | FLAPS_SET | 0-100% or notch 0-4 |

> `up` and `full` deliberately resolve to `FLAPS_SET` at the rail rather than to `FLAPS_UP` /
> `FLAPS_FULL`. `FLAPS_FULL` is not honoured by every aircraft; `FLAPS_SET` is. Both discrete
> events remain registered in the adapter for compatibility but the resolver never emits them.

### Trim
| Action | Voice Example | SimConnect Event | Value |
|---|---|---|---|
| `set` | "Set trim to..." | ELEVATOR_TRIM_SET | int |
| `up` / `nose_up` | "Trim nose up" | ELEV_TRIM_UP | — |
| `down` / `nose_down` | "Trim nose down" | ELEV_TRIM_DN | — |
| `rudder_left` | "Rudder trim left" | RUDDER_TRIM_LEFT | — |
| `rudder_right` | "Rudder trim right" | RUDDER_TRIM_RIGHT | — |
| `rudder_set` | "Set rudder trim to..." | RUDDER_TRIM_SET | int |
| `aileron_left` | "Aileron trim left" | AILERON_TRIM_LEFT | — |
| `aileron_right` | "Aileron trim right" | AILERON_TRIM_RIGHT | — |
| `aileron_set` | "Set aileron trim to..." | AILERON_TRIM_SET | int |

### Spoilers
| Action | Voice Example | SimConnect Event | Value |
|---|---|---|---|
| `toggle` | "Spoilers" | SPOILERS_TOGGLE | — |
| `set` | "Set spoilers to 50 percent" | SPOILERS_SET | 0-100% |

---

## Landing Gear

| Action | Voice Example | SimConnect Event | Critical |
|---|---|---|---|
| `up` / `retract` | "Gear up" | GEAR_UP | **YES** |
| `down` / `extend` | "Gear down" | GEAR_DOWN | **YES** |
| `toggle` | "Toggle gear" | GEAR_TOGGLE | **YES** |

> Critical commands are flagged with a `safety_note` in the tool result.

---

## Engine Management

### Throttle
| Action | Voice Example | SimConnect Event | Value |
|---|---|---|---|
| `set` | "Throttle to 80 percent" | THROTTLE_SET | 0-100% |

> `THROTTLE1_SET` and `THROTTLE2_SET` are registered in the adapter for per-engine control but
> the resolver has no action that emits them; all throttle commands are currently all-engine.

### Mixture
| Action | Voice Example | SimConnect Event | Value |
|---|---|---|---|
| `set` | "Mixture rich" / "Set mixture to 100" | MIXTURE_SET | 0-100% |

### Propeller
| Action | Voice Example | SimConnect Event | Value |
|---|---|---|---|
| `set` | "Prop full forward" / "Set prop to 100" | PROP_PITCH_SET | 0-100% |

---

## Fuel System

### Fuel Selector
| Action | Voice Example | SimConnect Event |
|---|---|---|
| `off` | "Fuel off" | FUEL_SELECTOR_OFF |
| `all` / `both` | "Fuel selector both" | FUEL_SELECTOR_ALL |
| `left` | "Fuel selector left" | FUEL_SELECTOR_LEFT |
| `right` | "Fuel selector right" | FUEL_SELECTOR_RIGHT |
| `set` | "Set fuel selector to..." | FUEL_SELECTOR_SET |

### Crossfeed
| Action | Voice Example | SimConnect Event |
|---|---|---|
| `open` / `on` | "Open crossfeed" | CROSS_FEED_OPEN |
| `close` / `off` | "Close crossfeed" | CROSS_FEED_OFF |
| `toggle` | "Toggle crossfeed" | CROSS_FEED_TOGGLE |

---

## Autopilot

| Action | Voice Example | SimConnect Event | Value |
|---|---|---|---|
| `on` / `off` / `toggle` | "Autopilot on" | AP_MASTER | — |
| `heading_hold` | "Heading hold" | AP_HDG_HOLD | — |
| `heading` | "Set heading to 270" | HEADING_BUG_SET | 0-360° |
| `altitude_hold` | "Altitude hold" | AP_ALT_HOLD | — |
| `altitude` | "Climb to 5000 feet" | AP_ALT_VAR_SET_ENGLISH | feet |
| `vs_hold` | "VS hold" | AP_VS_HOLD | — |
| `vertical_speed` | "Set VS minus 500" | AP_VS_VAR_SET_ENGLISH | fpm |
| `speed_hold` | "Speed hold" | AP_AIRSPEED_HOLD | — |
| `speed` | "Set speed to 200 knots" | AP_SPD_VAR_SET | knots |
| `nav` | "NAV mode" | AP_NAV1_HOLD | — |
| `approach` | "Approach mode" | AP_APR_HOLD | — |

> AP_MASTER is a critical command.

---

## Radios

| Action | Voice Example | SimConnect Event | Value |
|---|---|---|---|
| `com1` | "Set COM1 to 121.5" | COM_RADIO_SET_HZ | MHz |
| `com2` | "Set COM2 to 122.8" | COM2_RADIO_SET_HZ | MHz |
| `nav1` | "Tune NAV1 to 110.3" | NAV1_RADIO_SET_HZ | MHz |
| `nav2` | "Tune NAV2 to 115.0" | NAV2_RADIO_SET_HZ | MHz |

> Values given in MHz are auto-converted to Hz for SimConnect.

---

## Environmental

### Deice / Anti-ice
| Action | Voice Example | SimConnect Event |
|---|---|---|
| `pitot` / `pitot_heat` | "Pitot heat on" | PITOT_HEAT_TOGGLE |
| `structural` / `airframe` | "Structural deice on" | TOGGLE_STRUCTURAL_DEICE |
| `windshield` | "Windshield deice" | WINDSHIELD_DEICE_TOGGLE |
| `props` / `prop_deice` | "Prop deice on" | TOGGLE_PROPELLER_DEICE |

### Barometer
| Action | Voice Example | SimConnect Event | Value |
|---|---|---|---|
| `set` | "Set altimeter to 29.92" | KOHLSMAN_SET | inHg |

---

## Other

### Parking Brake
| Action | Voice Example | SimConnect Event |
|---|---|---|
| *(any)* | "Parking brake" | PARKING_BRAKES |

---

## Deferred systems (CMD-09)

These six systems are **not reachable**. `_resolve_command` handles them, so the code below
looks live, but they are absent from the `set_aircraft_control` enum — Claude cannot name
them — and absent from the adapter's `CommandMap` — the adapter could not execute them if it
were asked. Both absences are deliberate and are asserted by tests in both languages.

| System | Actions | SimConnect Event | Status |
|---|---|---|---|
| `magnetos` | `off`, `right`, `left`, `both`, `start` | MAGNETO_SET | not exposed, not registered |
| `carb_heat` | `on`, `off`, `toggle` | ANTI_ICE_CARB_HEAT_TOGGLE | not exposed, not registered |
| `fuel_pump` | `on`, `off`, `toggle` | FUEL_PUMP_TOGGLE | not exposed, not registered |
| `starter` | `engage`, `start` | TOGGLE_STARTER1 | not exposed, not registered |
| `primer` | `prime`, `pump` | TOGGLE_PRIMER | not exposed, not registered |
| `lights` | `landing`, `taxi`, `nav`, `beacon`, `strobe`, `panel` | LANDING_LIGHTS_TOGGLE, TOGGLE_TAXI_LIGHTS, TOGGLE_NAV_LIGHTS, TOGGLE_BEACON_LIGHTS, STROBES_TOGGLE, PANEL_LIGHTS_TOGGLE | not exposed, not registered |

**Why they are held back.** `execute_procedure` bypasses the `set_aircraft_control` enum
entirely, and `PROCEDURES["shutdown"]` contains a `magnetos` step. Registering `MAGNETO_SET`
in the adapter before the authority gate and the procedure re-route are in place would turn a
named tool call into a working in-flight engine shutdown with nothing in front of it.

Two of them also carry a latent defect that becomes live the moment they are exposed:
`carb_heat` and `fuel_pump` map `on`, `off` and `toggle` to the *same* toggle event, so
"carb heat off" turns it **on** when it was already off. That needs state-aware resolution
against telemetry before either system ships.

---

## Value Conversions

The `_resolve_command` function in `tools.py` handles these conversions automatically:

| Input | Conversion | Example |
|---|---|---|
| Throttle/mixture/prop/spoilers % | `value * 16383 / 100` | 75% → 12287 |
| Flaps notch (0-4) | `value * 16383 / 4` | notch 2 → 8191 |
| Flaps % (>4) | `value * 16383 / 100` | 50% → 8191 |
| Radio MHz | `value * 1,000,000` | 121.5 → 121500000 |
| Barometer inHg | `value * 100` | 29.92 → 2992 |

---

## Critical Commands

These commands trigger a `safety_note` in the tool result:

- `GEAR_UP`, `GEAR_DOWN`, `GEAR_TOGGLE`
- `AP_MASTER`
- `PARKING_BRAKES`

Claude is instructed to execute direct orders immediately but may confirm ambiguous or phase-inappropriate commands (e.g., gear up at very low altitude).

> The `safety_note` list is separate from, and much narrower than, the pre-execution rules in
> `command_safety.py`. Neither currently covers `mixture` idle-cutoff, `fuel_selector: off`,
> `crossfeed`, or `deice` — the highest-severity commands in the reachable surface. Closing
> that gap is Phase 2 authority work, not part of this reference.
