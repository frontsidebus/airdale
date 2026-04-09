# Proactive Co-Pilot (Phase 4)

MERLIN does not just respond to questions -- it speaks first. Phase 4 adds proactive monitoring systems that generate callouts, alerts, deviation warnings, and checklist offers based on live telemetry. These systems run on every telemetry tick, independent of pilot interaction.

Source files:
- `orchestrator/orchestrator/callouts.py` -- Callout engine and default rules
- `orchestrator/orchestrator/deviation_monitor.py` -- Deviation detection and alerting
- `orchestrator/orchestrator/checklist_manager.py` -- Phase-driven interactive checklists
- `orchestrator/orchestrator/emergency.py` -- Emergency auto-response (see also [Safety](SAFETY.md))

---

## Callout System

The `CalloutEngine` evaluates a list of `CalloutRule` definitions against the current and previous `SimState` on every telemetry update. When a rule's condition is met, MERLIN speaks the callout via TTS. Callouts are sorted by priority before delivery -- higher-priority callouts are spoken first.

### Takeoff Callouts

During the takeoff roll, MERLIN calls out critical speed and climb milestones:

| Callout | Trigger Condition | Priority |
|---|---|---|
| **V1** | IAS crosses above 80 kt | 10 |
| **Rotate** | IAS crosses above 85 kt | 10 |
| **Positive Rate** | VS > 100 fpm and AGL > 20 ft | 8 |
| **Gear Up** | VS > 300 fpm and AGL > 100 ft | 8 |

### Altitude Callouts (Climb)

| Callout | Trigger Condition | Priority |
|---|---|---|
| **Passing [N] feet** | Crossing a 1000 ft interval during climb (MSL) | 0 |
| **Approaching assigned altitude** | Within 200 ft of autopilot altitude target while AP is engaged | 5 |

The altitude passing callout fires repeatedly (not one-shot) with a 5-second cooldown between triggers to avoid rapid-fire announcements during fast climbs.

### Approach Gate Callouts

As the aircraft descends through standard approach altitude gates, MERLIN announces each one:

| Callout | Trigger Condition | Priority |
|---|---|---|
| **1000 feet** | AGL crosses below 1000 ft while descending (VS < 0) | 7 |
| **500 feet** | AGL crosses below 500 ft while descending | 7 |
| **Minimums** | AGL crosses below 200 ft while descending | 9 |
| **100 feet** | AGL crosses below 100 ft while descending | 8 |

### Landing Callouts

| Callout | Trigger Condition | Priority |
|---|---|---|
| **50 feet** | AGL crosses below 50 ft | 8 |
| **30 feet** | AGL crosses below 30 ft | 8 |
| **10 feet** | AGL crosses below 10 ft | 8 |

### Warning Callouts (Any Phase)

These safety callouts fire in any flight phase and repeat after their cooldown expires:

| Callout | Trigger Condition | Priority | Cooldown |
|---|---|---|---|
| **Overspeed, overspeed** | IAS > 250 kt below 10,000 ft MSL | 10 | 5 s |
| **Bank angle, bank angle** | Bank exceeds 45 deg | 10 | 3 s |
| **Sink rate** | VS < -2000 fpm below 2500 ft AGL | 10 | 3 s |

### One-Shot Behavior

By default, callouts are one-shot: they fire once per flight phase and are suppressed until the phase changes. When the `CalloutEngine` detects a phase transition via `on_phase_change()`, it clears all one-shot tracking, allowing rules to fire again in the new phase.

Warning callouts (overspeed, bank angle, sink rate) are the exception. They set `one_shot=False` and instead use a cooldown timer to rate-limit repeated alerts.

### Crossing Detection

Takeoff speed callouts and approach altitude callouts use crossing detection rather than threshold comparison. A callout fires only when the value transitions across the threshold between consecutive telemetry ticks (e.g., IAS was below 80 kt on the previous tick and is at or above 80 kt on the current tick). This prevents false triggers if the sim loads directly into a state above the threshold.

---

## Deviation Monitoring

The `DeviationMonitor` runs a separate set of rules that detect when flight parameters drift outside expected envelopes. Unlike callouts (which fire at specific trigger points), deviations represent sustained abnormal conditions.

Each `DeviationAlert` includes:
- **name** -- Rule identifier
- **message** -- What MERLIN says
- **severity** -- `caution` or `warning`
- **value** -- Current measured value
- **expected** -- The threshold or expected value
- **deviation** -- How far the value is from expected

### Speed Deviations

| Rule | Condition | Phases | Severity |
|---|---|---|---|
| `speed_high_approach` | IAS > 160 kt | Approach | Caution |
| `speed_low_approach` | IAS < 60 kt | Approach | Warning |
| `overspeed_below_10k` | IAS > 250 kt below 10,000 ft MSL | All airborne | Warning |
| `stall_warning` | IAS < 55 kt while airborne | All airborne | Warning |

### Altitude Deviations

| Rule | Condition | Phases | Severity |
|---|---|---|---|
| `altitude_bust` | More than 200 ft from AP target altitude (AP must be engaged) | Climb, Cruise, Descent | Caution |
| `too_low_terrain` | AGL < 500 ft | Cruise, Climb | Warning |

### Configuration Deviations

| Rule | Condition | Phases | Severity |
|---|---|---|---|
| `gear_not_down_low` | Gear handle up below 500 ft AGL | Approach | Warning |
| `flaps_not_set_approach` | Flaps < 10% below 1000 ft AGL | Approach | Caution |
| `no_ap_high_workload` | Autopilot off below 1000 ft AGL | Approach | Caution |

### Attitude Deviations

| Rule | Condition | Phases | Severity |
|---|---|---|---|
| `excessive_bank` | Bank > 30 deg | Approach, Landing | Warning |
| `excessive_pitch_up` | Pitch > 15 deg nose up | All except Takeoff | Caution |
| `excessive_pitch_down` | Pitch < -10 deg nose down | All phases | Warning |

### Cooldown

All deviation rules have a default cooldown of **30 seconds**. After a rule fires, it will not fire again until the cooldown expires, regardless of whether the condition persists. This prevents MERLIN from nagging the pilot repeatedly about the same issue. The cooldown is configurable per-rule via the `cooldown_secs` field on `DeviationRule`.

Calling `monitor.reset()` clears all cooldown timers (useful on flight reset or sim reload).

---

## Checklist Automation

The `ChecklistManager` offers checklists automatically when the flight phase changes and manages an interactive read-and-respond session between MERLIN and the pilot.

### Phase-to-Checklist Mapping

When the flight phase detector transitions to a new phase, the checklist manager checks whether a checklist is appropriate:

| Flight Phase | Checklist Offered |
|---|---|
| PREFLIGHT | Preflight checklist |
| TAXI | Before takeoff checklist |
| CLIMB | After takeoff checklist |
| CRUISE | Cruise checklist |
| DESCENT | Descent/approach checklist |
| LANDED | After landing checklist |

Phases not listed (TAKEOFF, APPROACH, LANDING) do not auto-offer checklists because pilot workload during those phases is too high.

### Auto-Offer Behavior

When a phase transition occurs and a matching checklist exists:
1. The manager checks whether that phase's checklist has already been completed this flight.
2. If not, it returns a prompt string: *"We've entered [phase] phase. Ready to run the [checklist] when you are, Captain."*
3. MERLIN speaks this offer via TTS. The pilot can accept or ignore it.

Auto-offer can be disabled by setting `manager.auto_offer = False`.

### Interactive Session

Once a checklist is started (via `start_checklist()`), MERLIN reads items one at a time. Each item includes:
- **Item** -- The action to perform (e.g., "Fuel quantity")
- **Setting** -- The expected state (e.g., "Sufficient for flight + reserves")
- **Remark** -- Optional MERLIN commentary

The pilot advances through the checklist using voice commands:

| Voice Command | Action |
|---|---|
| "Next" / "Check" | Mark current item complete, advance to next |
| "Skip" | Leave current item incomplete, advance to next |
| "Complete checklist" | End the session, get a summary |

### Session Summary

When the checklist is complete (all items read or the pilot says "complete checklist"), MERLIN reports:
- How many items were checked vs total
- How many were skipped
- Elapsed time

Example: *"Before takeoff checklist complete. 8/10 items checked, 2 skipped (45s elapsed)."*

The phase is then marked as completed, so the same checklist will not be offered again during the same flight.

### Checklist Status

The `get_status()` method returns a dict suitable for injection into Claude's context, containing:
- Whether a checklist is active
- Which phases have been completed
- Current item and progress (e.g., "4/10")

---

## Emergency Auto-Response

The `EmergencyDetector` monitors telemetry for catastrophic conditions and delivers pre-validated responses directly to TTS, bypassing the LLM entirely for the initial callout. See [Safety Validation Layer](SAFETY.md) for full details.

### Telemetry-Triggered Detection

| Emergency | Trigger | Flight Phases |
|---|---|---|
| Engine failure (takeoff) | RPM drops below 100 from healthy state | Takeoff, Climb |
| Engine failure (cruise) | RPM drops below 100 from healthy state | Cruise, Descent, Approach |
| Engine fire | EGT > 1500 deg with RPM > minimum | Any |
| Electrical fire | Electrical anomaly detection | Any |
| Rapid decompression | Cabin altitude > 10,000 ft | Any |

### Behavior

- Emergency events are the highest priority (priority 3) and interrupt any in-progress TTS playback.
- The detector uses a **0.5-second debounce** to prevent false positives from telemetry glitches.
- Pre-validated responses include numbered immediate actions, a follow-up checklist, and squawk 7700.
- Claude is engaged in parallel for situational reasoning (nearest airport, terrain, weather) but the pilot hears immediate actions without waiting for LLM inference.
- Only one emergency can be active at a time. The emergency must be explicitly cleared before another can be detected.

---

## Event Priority System

All proactive events are assigned a priority level that determines delivery order and interruption behavior:

| Priority | Level | Examples | Behavior |
|---|---|---|---|
| 0 | Info | Altitude passing callouts, checklist offers | Queued, delivered in order |
| 1 | Caution | Speed high on approach, flaps not set, pitch attitude | Delivered promptly, does not interrupt TTS |
| 2 | Warning | Stall warning, gear not down, excessive bank, altitude bust | Delivered promptly, may interrupt low-priority TTS |
| 3 | Emergency | Engine failure, fire, decompression | Immediate delivery, interrupts all TTS |

Within a priority level, events are delivered in the order they were generated. Higher-priority events always take precedence. Priority 3 (emergency) events cancel any in-progress TTS playback and deliver the emergency response immediately.

### Priority Mapping

The callout and deviation systems use numeric priorities that map to these levels:

- **Callout priorities 0-4** correspond to info (altitude passing, level-off).
- **Callout priorities 5-8** correspond to caution/warning depending on context (approach gates, positive rate).
- **Callout priorities 9-10** correspond to warning (minimums, overspeed, bank angle, sink rate).
- **Deviation severity "caution"** maps to priority 1.
- **Deviation severity "warning"** maps to priority 2.
- **Emergency responses** are always priority 3.

---

## Configuration

### Tuning Callout Thresholds

Callout thresholds are defined as constants in the condition functions within `callouts.py`. To change a threshold, modify the value passed to `_crossed_above()` or `_crossed_below()`:

```python
# Example: change V1 callout from 80 kt to 75 kt
def _v1_condition(state: SimState, prev: SimState | None) -> bool:
    return _crossed_above(
        state.speeds.indicated_airspeed,
        prev.speeds.indicated_airspeed if prev else None,
        75.0,  # was 80.0
    )
```

### Adding a Custom Callout

Create a new `CalloutRule` and append it to the rules list:

```python
from orchestrator.callouts import CalloutEngine, CalloutRule
from orchestrator.sim_client import FlightPhase, SimState

def _my_condition(state: SimState, prev: SimState | None) -> bool:
    return state.speeds.indicated_airspeed > 200

engine = CalloutEngine(
    rules=DEFAULT_CALLOUT_RULES + [
        CalloutRule(
            name="SPEED_200",
            phase=FlightPhase.CLIMB,
            condition=_my_condition,
            message="200 knots",
            priority=5,
        ),
    ]
)
```

Alternatively, pass a callable as the `message` parameter to generate dynamic text based on the current state.

### Adding a Custom Deviation Rule

```python
from orchestrator.deviation_monitor import DeviationMonitor, DeviationRule, DeviationAlert
from orchestrator.sim_client import FlightPhase, SimState

def _check_fuel_low(state: SimState) -> DeviationAlert | None:
    if state.fuel.total_gallons < 10:
        return DeviationAlert(
            name="fuel_low",
            message=f"Low fuel. {state.fuel.total_gallons:.1f} gallons remaining",
            severity="warning",
            value=state.fuel.total_gallons,
            expected=10.0,
            deviation=10.0 - state.fuel.total_gallons,
        )
    return None

monitor = DeviationMonitor(
    rules=DEFAULT_DEVIATION_RULES + [
        DeviationRule(
            name="fuel_low",
            check=_check_fuel_low,
            phases=ALL_AIRBORNE_PHASES,
            cooldown_secs=60.0,  # only remind once per minute
        ),
    ]
)
```

### Disabling Specific Alerts

Filter out unwanted rules when constructing the engine or monitor:

```python
# Disable the "no autopilot" nag
filtered_rules = [r for r in DEFAULT_DEVIATION_RULES if r.name != "no_ap_high_workload"]
monitor = DeviationMonitor(rules=filtered_rules)
```

### Disabling Checklist Auto-Offer

```python
manager = ChecklistManager()
manager.auto_offer = False  # checklists only start when explicitly requested
```

### Deviation Cooldown

The default cooldown for all deviation rules is 30 seconds. Adjust per-rule:

```python
# Make stall warning more aggressive (10-second cooldown)
for rule in DEFAULT_DEVIATION_RULES:
    if rule.name == "stall_warning":
        rule.cooldown_secs = 10.0
```
