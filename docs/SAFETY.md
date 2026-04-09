# Safety Validation Layer

The safety validation layer protects against two categories of risk: **time-critical emergencies** where LLM latency is unacceptable, and **numerical hallucinations** where Claude might state an incorrect V-speed, altitude, or frequency. Both operate independently of the LLM inference pipeline.

The safety layer works in concert with the [Proactive Co-Pilot](PROACTIVE_COPILOT.md) system. Proactive monitoring (callouts, deviation alerts, checklist automation) provides continuous situational awareness, while the safety layer handles the most time-critical scenarios where LLM latency is unacceptable and numerical accuracy is non-negotiable.

Source files:
- `orchestrator/orchestrator/emergency.py` -- Emergency detection and fast-path responses
- `orchestrator/orchestrator/validation.py` -- Response validation and telemetry sanity checks
- `orchestrator/orchestrator/callouts.py` -- Proactive callout engine (warning callouts feed the safety layer)
- `orchestrator/orchestrator/deviation_monitor.py` -- Deviation monitoring (warning-severity alerts)

---

## Emergency Fast Paths

The `EmergencyDetector` monitors consecutive telemetry snapshots for sudden state transitions that indicate an emergency. When a condition is confirmed, it delivers a **pre-validated response** directly to TTS, bypassing Claude entirely for the initial callout. Claude is still engaged in parallel for situational reasoning (nearest airport, terrain, weather), but the pilot hears immediate actions within milliseconds instead of waiting for LLM inference.

### Supported Emergency Types

| Emergency | Trigger Condition | Flight Phases |
|---|---|---|
| `ENGINE_FAILURE_TAKEOFF` | RPM drops from healthy (>100) to below threshold | TAKEOFF, CLIMB |
| `ENGINE_FAILURE_CRUISE` | RPM drops from healthy (>100) to below threshold | CRUISE, DESCENT, APPROACH |
| `ENGINE_FIRE` | EGT exceeds 1500 deg with RPM still above minimum | Any |
| `ELECTRICAL_FIRE` | Electrical anomaly detection | Any |
| `RAPID_DECOMPRESSION` | Cabin altitude exceeds 10,000 ft | Any |

### Detection Pipeline

```
SimState(t-1) + SimState(t) --> EmergencyDetector.evaluate()
                                    |
                                    +--> _detect() checks all conditions
                                    |     against telemetry deltas
                                    |
                                    +--> Debounce: candidate must persist
                                    |     for min_detection_duration (0.5s)
                                    |
                                    +--> Confirmed: build_emergency_response()
                                          |
                                          +--> Spoken response --> TTS (immediate)
                                          +--> Context dict --> Claude (parallel)
```

### Debouncing

To prevent false positives from telemetry glitches, the detector requires a condition to persist for a configurable duration before confirming:

```python
class EmergencyThresholds:
    engine_rpm_min: float = 100.0      # RPM below this = engine dead
    egt_fire_threshold: float = 1500.0 # EGT above this = possible fire
    oil_pressure_min: float = 10.0     # psi
    cabin_alt_max: float = 10000.0     # feet
    min_detection_duration: float = 0.5 # seconds to confirm
```

The detector tracks a `_candidate` emergency type and a `_candidate_since` timestamp. If the same condition is detected on consecutive evaluations and the elapsed time exceeds `min_detection_duration`, the emergency is confirmed. If the condition disappears before the duration elapses, the candidate is cleared.

### Pre-Validated Responses

Each emergency type maps to a static procedure containing:
- **Title** -- Human-readable emergency name
- **Immediate actions** -- Numbered steps delivered via TTS immediately
- **Follow-up checklist** -- Additional items displayed in the UI
- **Assessment template** -- Formatted with live telemetry values (altitude, airspeed, EGT)
- **Squawk code** -- Always 7700

Example spoken output for engine failure during takeoff:

> "ENGINE FAILURE -- loss of power during takeoff. Step 1: Maintain wings level, do not turn back to the runway. Step 2: Pitch for best glide speed. Step 3: Identify a landing site ahead, within 30 degrees of current heading."

### State Management

- Only one emergency can be active at a time. Once confirmed, `_active_emergency` is set and no further emergencies are evaluated until `clear()` is called.
- `clear()` is called after landing or when the pilot explicitly resolves the emergency.
- The `build_context()` method on `EmergencyResponse` produces a dict injected into Claude's system prompt, giving it awareness of the emergency start altitude, airspeed, and actions already delivered.

---

## Response Validation

The `ResponseValidator` scans Claude's text output for aviation-critical numbers and cross-references them against a structured aircraft database. This catches LLM hallucinations before they reach the pilot.

### Aircraft Database

Seven aircraft types are pre-populated with V-speeds and operating limits:

| Type Code | Aircraft | Aliases |
|---|---|---|
| `C172` | Cessna 172 Skyhawk | C172S, 172SP |
| `C152` | Cessna 152 | -- |
| `PA28` | Piper Cherokee/Warrior | PA-28, PA28-161 |
| `SR22` | Cirrus SR22 | SR22T |
| `DA40` | Diamond DA40 | DA40NG |
| `B738` | Boeing 737-800 | 737-800, 738, B737 |
| `A320` | Airbus A320 | A320neo, A320-200 |

Each entry contains:
- **V-speeds**: Vs0, Vs1, Vfe, Vno, Vne, Vr, Vx, Vy, Vglide
- **Operating limits**: max altitude (service ceiling), max gross weight, fuel capacity

### V-Speed Cross-Referencing

The validator uses regex patterns to extract V-speed mentions from Claude's response text:

```
"Vx is 62 knots" --> extracts Vx = 62, checks against C172 database (62 kt) --> OK
"Vne is 180 knots" --> extracts Vne = 180, checks against C172 database (163 kt) --> CRITICAL
```

Tolerance is configurable (default 10%). V-speeds for structural limits (`Vfe`, `Vne`, `Vs0`) are flagged as **critical** severity; others are flagged as **warning**.

Critical warnings trigger automatic correction text appended to the response:

```
[CORRECTION: VNE stated as 180 kt but database shows 163 kt]
```

### Frequency Validation

All numbers matching the pattern `\d{3}\.\d{1,3}` are checked against valid aviation frequency bands:
- **Comm band**: 118.000 -- 136.975 MHz
- **Nav band**: 108.0 -- 117.95 MHz
- **Military UHF**: 200.0 -- 400.0 MHz

Frequencies outside these ranges are flagged as warnings.

### Standard Frequencies

A reference table of standard frequencies is maintained for cross-checking:

| Name | Frequency |
|---|---|
| Emergency / Guard | 121.5 MHz |
| Universal Unicom | 122.8 MHz |
| Multicom | 122.9 MHz |
| CTAF Default | 122.7 MHz |
| Flight Service | 122.2 MHz |

---

## Telemetry Sanity Checks

The `check_telemetry_sanity()` function validates incoming SimConnect data against physical constraints. This protects against garbage data that occasionally appears during sim pauses, scenery loads, or SimConnect reconnections.

### Checks Performed

| Field | Condition | Threshold |
|---|---|---|
| `altitude_msl` | Below Dead Sea | < -1,500 ft |
| `altitude_agl` | Underground | < -100 ft |
| `mach` | Supersonic GA | > Mach 2.0 with IAS < 500 kt |
| `indicated_airspeed` | Negative | < -10 kt |
| `indicated_airspeed` | Hypersonic | > 800 kt |
| `latitude` | Out of range | < -90 or > 90 (when non-zero) |
| `longitude` | Out of range | < -180 or > 180 (when non-zero) |
| `engine_rpm` | Negative | < -1 |
| `engine_oil_temp` | Impossible | > 500 deg |

Each failed check produces a `TelemetrySanityWarning` with field name, value, and human-readable message. Warnings are logged at WARNING level. The orchestrator can use these to suppress telemetry updates that would confuse the flight phase detector or trigger false emergency detections.

---

## Tool Timeouts

All external API calls in the aviation tools use `httpx.AsyncClient` with a default timeout of **10 seconds** (`_DEFAULT_TIMEOUT = 10.0`). This prevents a single slow API from blocking the entire response pipeline. If a tool times out, it returns an error dict rather than raising an exception, allowing Claude to continue its response without the tool result.
