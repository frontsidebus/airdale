# Aircraft Controls Reference

Complete reference for every system, action, and value MERLIN can control via the `set_aircraft_control` tool. **20 systems, 72+ actions.**

Voice command examples shown for each — MERLIN executes immediately on unambiguous direct orders.

---

## Flight Controls

### Flaps
| Action | Voice Example | SimConnect Event | Value |
|---|---|---|---|
| `up` / `retract` | "Flaps up" | FLAPS_UP | — |
| `full` / `down` | "Give me full flaps" | FLAPS_FULL | — |
| `1` / `10` | "Flaps one" | FLAPS_1 | — |
| `2` / `20` | "Flaps two" | FLAPS_2 | — |
| `3` / `30` | "Flaps three" | FLAPS_3 | — |
| `incr` / `increase` | "More flaps" | FLAPS_INCR | — |
| `decr` / `decrease` | "Less flaps" | FLAPS_DECR | — |
| `set` | "Set flaps to 25 percent" | FLAPS_SET | 0-100% or notch 0-4 |

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

### Mixture
| Action | Voice Example | SimConnect Event | Value |
|---|---|---|---|
| `set` | "Mixture rich" / "Set mixture to 100" | MIXTURE_SET | 0-100% |

### Propeller
| Action | Voice Example | SimConnect Event | Value |
|---|---|---|---|
| `set` | "Prop full forward" / "Set prop to 100" | PROP_PITCH_SET | 0-100% |

### Magnetos
| Action | Voice Example | SimConnect Event | Value |
|---|---|---|---|
| `off` | "Magnetos off" | MAGNETO_SET | 0 |
| `right` | "Magnetos right" | MAGNETO_SET | 1 |
| `left` | "Magnetos left" | MAGNETO_SET | 2 |
| `both` | "Magnetos both" | MAGNETO_SET | 3 |
| `start` | "Magnetos start" | MAGNETO_SET | 4 |

### Carburetor Heat
| Action | Voice Example | SimConnect Event |
|---|---|---|
| `on` / `off` / `toggle` | "Carb heat on" | ANTI_ICE_CARB_HEAT_TOGGLE |

### Fuel Pump
| Action | Voice Example | SimConnect Event |
|---|---|---|
| `on` / `off` / `toggle` | "Fuel pump on" | FUEL_PUMP_TOGGLE |

### Starter
| Action | Voice Example | SimConnect Event |
|---|---|---|
| `engage` / `start` | "Engage starter" | TOGGLE_STARTER1 |

### Primer
| Action | Voice Example | SimConnect Event |
|---|---|---|
| `prime` / `pump` | "Prime the engine" | TOGGLE_PRIMER |

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

## Lights

| Action | Voice Example | SimConnect Event |
|---|---|---|
| `landing` | "Landing lights on" | LANDING_LIGHTS_TOGGLE |
| `taxi` | "Taxi lights on" | TOGGLE_TAXI_LIGHTS |
| `nav` / `navigation` | "Nav lights on" | TOGGLE_NAV_LIGHTS |
| `beacon` | "Beacon on" | TOGGLE_BEACON_LIGHTS |
| `strobe` | "Strobes on" | STROBES_TOGGLE |
| `panel` | "Panel lights" | PANEL_LIGHTS_TOGGLE |

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
