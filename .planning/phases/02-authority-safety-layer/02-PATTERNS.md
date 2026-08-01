# Phase 2: Authority & Safety Layer - Pattern Map

**Mapped:** 2026-07-31
**Files analyzed:** 34 (7 new, 27 modified)
**Analogs found:** 31 / 34 (3 partial, 0 with none)

**Polyglot note:** this phase spans four tiers. Analogs are matched *within tier* —
C# files map to `adapters/msfs/`, browser files to `web/static/`, web-server files
to `web/`, orchestrator files to `orchestrator/orchestrator/`. Do not copy a Python
pattern into the C# adapter.

---

## File Classification

### New files

| New file | Role | Data Flow | Closest Analog | Match |
|---|---|---|---|---|
| `orchestrator/orchestrator/authority.py` | model + state machine | in-process event-driven (clock + counter) | `orchestrator/orchestrator/sim_client.py` (`ConnectionState` StrEnum L42-48, `HealthMonitor` L206-243) + `flight_phase.py` (`PhaseThresholds` L13-23, counter/hysteresis L34-58) | role-match |
| `orchestrator/orchestrator/override_detector.py` | service (telemetry subscriber) | event-driven, level-triggered stream | `orchestrator/orchestrator/proactive_monitor.py` (`ProactiveMonitor.on_telemetry_update` L145-168) | exact |
| `orchestrator/tests/test_authority.py` | test | unit, clock-injected | `orchestrator/tests/test_command_verifier.py` (shrunk-timeout style) + `test_turn_detection.py` `_settings()` L25-28 | exact |
| `orchestrator/tests/test_override_detector.py` | test | unit, state-fixture | `orchestrator/tests/test_proactive_monitor.py` `_make_state` L29-45 + `test_command_history.py:45` literal timestamps | exact |
| `orchestrator/tests/test_command_coverage.py` | test (structural/cross-language guard) | file-I/O + regex parse | `orchestrator/tests/test_voice.py` L1-91 (source-text regression guards) | partial |
| `web/tests/test_turn_probe.py` (or extend `test_rest.py`) | test | request-response, ASGI in-process | `web/tests/test_rest.py` L22-100 (`ASGITransport` + `mock_app_state`) | exact |
| `adapters/msfs/SimConnectBridge.Tests/CommandMapTests.cs` | test (C#) | table assertion | `adapters/msfs/SimConnectBridge.Tests/SimDataStructTests.cs` L13-70 | exact |

### Modified — orchestrator (Python)

| File | Role | Data Flow | Closest Analog | Match |
|---|---|---|---|---|
| `orchestrator/orchestrator/tools.py` (gate at L264, CMD-08 refusal at L184-190) | controller (tool handler) | request-response | itself — the `blocked` short-circuit at L256-263 is the shape the gate copies | exact (self) |
| `orchestrator/orchestrator/procedures.py` (`_execute_step` L257-288, `__init__` L210) | service | batch / sequential | `tools.py:set_aircraft_control` L217-308 (the collaborator-injection signature to mirror) | exact |
| `orchestrator/orchestrator/sim_client.py` (`send_command` L359-396, `connect` L314-327, `_reconnect` L434-472) | client / transport | request-response + reconnect | itself — `HealthMonitor` L206-243 for the counter-holder shape | exact (self) |
| `orchestrator/orchestrator/command_verifier.py` (new `VERIFICATION_CHECKS` entries) | service | poll / transform | `_check_alt_set` L113-126 + table L167-175 | exact |
| `orchestrator/orchestrator/claude_client.py` (`__init__` L459-495, `_TOOL_TIMEOUTS` L707-717, `_dispatch_tool` L760-768, enum L355-373) | controller (dispatch) | request-response | itself — `verifier`/`command_history` thread-through at L494, L766-767 | exact (self) |
| `orchestrator/orchestrator/config.py` (7 new fields) | config | n/a | `config.py` turn-detection block L111-140 (`Field(default=, gt=, description=)`) | exact |
| `orchestrator/orchestrator/main.py` (wire authority + `command_path` health + subscriber) | entry point | wiring | `main.py` L83-88 (health register) + L102 (`subscribe`) | exact |
| `orchestrator/orchestrator/audio_processing.py` (new no-preprocess decode helper) | utility | file-I/O / subprocess | `convert_webm_to_wav_normalized` L327-373 | exact |

### Modified — web server (Python)

| File | Role | Data Flow | Closest Analog | Match |
|---|---|---|---|---|
| `web/server.py` — `AppState` (L99-115), `lifespan` (L176-284) | provider / DI container | startup wiring | itself — `state.phase_detector` wiring L201-212 | exact (self) |
| `web/server.py` — `/api/status` (L343-385) | route (GET) | request-response | itself — the flat dict return at L364-385 | exact (self) |
| `web/server.py` — new `POST /api/turn-probe` | route (POST, binary upload) | file-I/O → transform → response | `POST /api/transcribe` L388-424 (`UploadFile`, `await file.read()`, dict return) | exact |
| `web/server.py` — `_on_tool_result` (L1086-1104) | callback / adapter | event → queue | itself | exact (self) |
| `web/requirements.txt` | config | n/a | — (declaration only; see RESEARCH §Environment availability) | n/a |

### Modified — browser

| File | Role | Data Flow | Closest Analog | Match |
|---|---|---|---|---|
| `web/static/app.js` — VAD constants + `pollVAD` (L1433-1435, L1495-1561) | component (audio loop) | streaming / rAF poll | itself; probe upload has no in-repo analog — closest is the WS blob send at L1531-1536 and `pollStatus` fetch at L1944-1966 | partial |
| `web/static/app.js` — `command_status` case (L846-849) + `showCommandStatus` (L479-496) | component (render) | event-driven | itself — add a `command_advisory` sibling | exact (self) |
| `web/static/app.js` — `pollStatus` (L1944-1966) + `setLed` | component (status poll) | request-response | itself | exact (self) |
| `web/static/index.html` (L33-49 status LED group) | template | n/a | itself — `status-indicator` div pattern | exact (self) |
| `web/static/style.css` | style | n/a | existing `.status-indicator` / `.command-toast` classes | exact (self) |

### Modified — MSFS adapter (C#)

| File | Role | Data Flow | Closest Analog | Match |
|---|---|---|---|---|
| `adapters/msfs/Models/SimDataStructs.cs` — `SimEventId` (L31-83) | model (enum) | n/a | itself — the existing grouped-with-comment members L41-82 | exact (self) |
| `adapters/msfs/SimConnectManager.cs` — `CommandMap` (L245-290) | config table | lookup | itself — `RegisterClientEvents` L296-308 iterates it, so **no other change is required** | exact (self) |

### Modified — tests

| File | Why it changes |
|---|---|
| `orchestrator/tests/test_tools.py` (`TestSetAircraftControl` L679-783) | `set_aircraft_control` gains `authority=`; existing 8 tests pass none ⇒ must still behave as `full` |
| `orchestrator/tests/test_procedures.py` (8 × `ProcedureExecutor(client)` at L209, 229, 244, 260, 294, 302, 322, 336) | constructor gains collaborators |
| `orchestrator/tests/test_sim_client.py` (`TestHealthMonitor` L577-627) | floor + watchdog on `send_command`; `command_path` subsystem |
| `orchestrator/tests/test_config.py` | new fields + bounds |
| `orchestrator/tests/test_claude_client.py` | `__init__` authority param; `_TOOL_TIMEOUTS` change |
| `orchestrator/tests/test_command_verifier.py` | additive `VERIFICATION_CHECKS` entries |
| `web/tests/test_rest.py` (L22-50) | `/api/status` new fields — **extend, don't replace** |
| `web/tests/test_chat_ws.py` (`fake_chat(text, sim_state=None, on_tool_result=None)` L110, 135, 162, 207) | advisory branch in `_on_tool_result` |

### Modified — docs / config surface

`.env.example`, `docs/CONFIGURATION.md`, `docs/SMART_CONTROLS.md`,
`docs/AIRCRAFT_CONTROLS.md`, `CLAUDE.md`. Pattern: `.env.example` uses
`# --- Section ---` headers with a prose comment above each `KEY=value`
(see L36-51). **`.env.example` currently has no turn-detection section at all** —
`TURN_DETECTOR`, `TURN_THRESHOLD`, `TURN_PROBE_SILENCE_MS`, `VAD_SILENCE_MS` are
undocumented there. Adding the authority block is a chance to close that too.

---

## Pattern Assignments

### `orchestrator/orchestrator/authority.py` (new — model + state machine)

**Hard constraint (RESEARCH §Module Placement):** this module must import **nothing**
from the orchestrator package. `sim_client.py` L9-20 imports only stdlib, `websockets`,
`pydantic` — it is the base of the dependency graph, and D-05 makes it a consumer of
`AuthorityState`. Import `SimState` here and you create a cycle.

**Analog A — closed enum, `StrEnum`** (`sim_client.py:42-48`):

```python
class ConnectionState(StrEnum):
    """WebSocket connection lifecycle states."""

    DISCONNECTED = "DISCONNECTED"
    CONNECTING = "CONNECTING"
    CONNECTED = "CONNECTED"
    RECONNECTING = "RECONNECTING"
```

Copy this exactly for `AuthorityLevel` (`ADVISORY` / `ASSISTED` / `FULL`) and
`AuthorityReason` (`CONFIG` / `OVERRIDE` / `WATCHDOG`). `FlightPhase`
(`sim_client.py:25-34`) is the second instance of the same pattern, so it is the
established convention, not a one-off. Add a
`SUPPORTED_AUTHORITY_LEVELS: tuple[str, ...]` alongside — same role as
`SUPPORTED_DETECTORS` (`turn/__init__.py:39`), for the CLAUDE.md missing-branch hazard.

**Analog B — tunables as a frozen-ish dataclass, not literals** (`flight_phase.py:13-23`):

```python
@dataclass
class PhaseThresholds:
    taxi_ground_speed: float = 5.0  # knots - moving on ground
    takeoff_speed: float = 40.0  # knots - committed to takeoff roll
    ...


class FlightPhaseDetector:
    def __init__(self, thresholds: PhaseThresholds | None = None) -> None:
        self._thresholds = thresholds or PhaseThresholds()
```

`AuthorityState.__init__` follows: seeded values arrive as constructor args
(from `Settings`), never read from a global.

**Analog C — counter + threshold + reset, held on the object** (`flight_phase.py:34-58`):

```python
    def __init__(self, thresholds: PhaseThresholds | None = None) -> None:
        self._current_phase = FlightPhase.PREFLIGHT
        self._phase_hold_count: int = 0
        self._hold_required: int = 3  # consecutive detections before transition

    def update(self, state: SimState) -> FlightPhase:
        candidate = self._detect_phase(state)
        if candidate != self._current_phase:
            self._phase_hold_count += 1
            if self._phase_hold_count >= self._hold_required:
                previous = self._current_phase
                self._current_phase = candidate
                self._phase_hold_count = 0
                logger.info("Flight phase: %s -> %s", previous.value, candidate.value)
        else:
            self._phase_hold_count = 0
        return self._current_phase
```

This is the watchdog circuit-breaker in miniature: consecutive-count, trip at N,
reset on the non-matching case, log the transition with old → new. Copy the shape
(`_consecutive_timeouts`, `_max_timeouts`, `record_timeout()`, `record_success()`).

**Analog D — a summary dict for JSON, built by the state holder** (`sim_client.py:234-243`):

```python
    def summary(self) -> dict[str, dict[str, Any]]:
        """Return a summary dict suitable for JSON serialization."""
        return {
            name: {
                "healthy": sub.healthy,
                "age_seconds": round(sub.age_seconds, 1),
                "message": sub.message,
            }
            for name, sub in self._subsystems.items()
        }
```

Give `AuthorityState` the same affordance (`summary()` → `{"level": ..., "reason": ...,
"until": ...}`) so `/api/status` and the CLI both render from one place rather than
each formatting the enum themselves.

**Clock injection** — new to this repo, mandated by RESEARCH §Test Strategy (there is no
freezegun / time-machine in any extra, `orchestrator/pyproject.toml:24-39`):

```python
class AuthorityState:
    def __init__(self, level: AuthorityLevel, *, clock: Callable[[], float] = time.monotonic) -> None:
        self._clock = clock
```

Consistent with the repo's DI habit (`safety_check`, `verifier`, `command_history` are
all injected at `tools.py:222-224`).

---

### `orchestrator/orchestrator/override_detector.py` (new — telemetry subscriber)

**Analog A — the per-update loop, level-triggered with a prev guard**
(`proactive_monitor.py:145-168`):

```python
    async def on_telemetry_update(self, state: SimState) -> None:
        """Called on each telemetry update.  Evaluates all proactive systems."""
        prev = self._prev_state

        # 1. Emergency conditions (priority 3)
        if prev is not None:
            self._check_emergencies(prev, state)
        ...
        self._prev_state = state
```

Note `prev is not None` is the guard that F6 (startup burst) needs — copy it, and note
that `_check_deviations` at L154 *omits* it, which is the bug not to reproduce.

**Analog B — the announcement channel** (`proactive_monitor.py:37-58`, queue at L126,
drain at L170-175). Do **not** invent a notification path:

```python
@dataclass(order=True)
class ProactiveEvent:
    _sort_key: int = field(init=False, repr=False)

    type: str = field(compare=False)  # "callout", "deviation", "emergency", "checklist_offer"
    priority: int = field(compare=False)  # 0=info, 1=caution, 2=warning, 3=emergency
    message: str = field(compare=False)  # What MERLIN should say
    tts_override: bool = field(default=False, compare=False)
    data: dict[str, Any] = field(default_factory=dict, compare=False)

    def __post_init__(self) -> None:
        self._sort_key = -self.priority
```

AUTH-06's drop and restore announcements are `ProactiveEvent(type="authority",
priority=1|0, ...)`. **Caveat (B5):** `ProactiveMonitor` is never constructed, so the
detector must own its own `asyncio.PriorityQueue` (same construction as
`proactive_monitor.py:126`) or accept one, and the web server must drain it — reusing
the event *type*, not the dormant host.

**Analog C — the watched-fields data table** (`command_history.py:53-64` — this is the
table shape to copy; `_extract_relevant_state` at L209-224 is **not** reusable, see B4):

```python
_STATE_RESTORE_COMMANDS: dict[str, tuple[str, str, str]] = {
    # command -> (system, action, state_field_path)
    "FLAPS_SET": ("flaps", "set", "surfaces.flaps_percent"),
    "HEADING_BUG_SET": ("autopilot", "heading", "autopilot.heading"),
    "AP_ALT_VAR_SET_ENGLISH": ("autopilot", "altitude", "autopilot.altitude"),
    ...
}
```

New table: `COMMAND_WATCHED_FIELDS: dict[str, tuple[str, ...]]` mapping command →
dotted `SimState` paths. Resolve with the existing walker, do not write a second one
(`command_history.py:87-91`):

```python
def _get_nested_attr(obj: Any, path: str) -> Any:
    """Resolve a dotted attribute path on an object."""
    for part in path.split("."):
        obj = getattr(obj, part)
    return obj
```

**Analog D — per-field epsilon tolerances** (F3). Reuse the verifier's numbers verbatim
so the two layers agree: flaps ±5 % (`command_verifier.py:67`), heading ±1°
(`:99`), altitude ±50 ft (`:119`), RPM ±50 (`:145-147`). Per B6, exclude throttle/RPM
from the watched set entirely.

**Hosting (B5 / D-11 amendment):** subscribe directly via `TelemetryClient.subscribe`
(`sim_client.py:352-353`), whose callback type is already declared:

```python
StateCallback = Callable[[SimState], Coroutine[Any, Any, None]]
```

Registration analog — CLI `main.py:102` (`self._sim_client.subscribe(self._on_state_update)`)
and web `server.py:205-212`:

```python
    if state.sim_connected and state.sim_client is not None:

        async def _on_state(sim_state: SimState) -> None:
            assert state.phase_detector is not None
            detected = state.phase_detector.update(sim_state)
            sim_state.flight_phase = detected

        state.sim_client.subscribe(_on_state)
```

---

### `orchestrator/orchestrator/tools.py` (modified — the gate, D-03/D-07; CMD-08 refusal)

**Signature to extend** (`tools.py:217-225`) — add `authority: AuthorityState | None = None`
as a trailing keyword:

```python
async def set_aircraft_control(
    sim_client: TelemetryClient,
    system: str,
    action: str,
    value: float | None = None,
    verifier: CommandVerifier | None = None,
    safety_check: CommandSafetyCheck | None = None,
    command_history: CommandHistory | None = None,
) -> dict[str, Any]:
```

**Anti-pattern present in the same function** — do not copy this for authority
(`tools.py:20`, `tools.py:245`):

```python
_safety_check = CommandSafetyCheck()          # L20: module-level mutable singleton
...
checker = safety_check or _safety_check       # L245: silent global fallback
```

D-09 rejects this shape explicitly. `authority is None` ⇒ behave as `FULL`
(preserves every existing test at `test_tools.py:679-783`), with the `send_command`
floor as the real backstop. State it in the docstring.

**Gate insertion point** (`tools.py:239-271`) — the gate goes between the `blocked`
short-circuit and `send_command`, where both `sim_state` and `safety_result` exist:

```python
    command, sim_value = _resolve_command(system, action, value)

    if command is None:
        return {"error": f"Unknown control: system={system}, action={action}"}

    # --- Pre-execution safety check ---
    checker = safety_check or _safety_check
    safety_result = None
    try:
        sim_state = await sim_client.get_state()
    except ConnectionError:
        sim_state = None

    if sim_state is not None:
        aircraft_type = sim_state.aircraft or ""
        safety_result = checker.check(command, sim_value, sim_state, aircraft_type)

        if safety_result.severity == "blocked":
            logger.warning("Command %s BLOCKED: %s", command, safety_result.reason)
            return {
                "error": safety_result.reason,
                "command": command,
                "blocked": True,
                "severity": "blocked",
            }

    # <<< AUTHORITY GATE (D-03) — sim_state + safety_result available, nothing sent >>>

    state_before = sim_state
    ...
    result = await sim_client.send_command(command, sim_value)   # L271
```

**Early-return dict shape to copy** — the `blocked` return above is the template for the
advisory dry run and the assisted withhold: a flat `dict[str, Any]` carrying `command`,
a boolean marker, and a human-readable reason. Per D-07 the advisory result is
`{"advisory": True, "would_execute": command, "safety": <verdict>}` — note it must
**not** contain an `"error"` key or B8 mis-renders it; see the `web/server.py` entry.

**Result-decoration pattern to follow** (`tools.py:273-306`) — every optional concern
appends a key rather than restructuring the dict:

```python
    result["command"] = command
    result["sim_value"] = sim_value

    if safety_result is not None and safety_result.severity == "warning":
        result["safety_warning"] = safety_result.reason
    ...
    if command in CRITICAL_COMMANDS:
        result["safety_note"] = "Critical system change executed"
```

**CMD-08 refusal site** (`tools.py:184-190`) — the branches to change:

```python
    elif system == "carb_heat":
        if action in ("on", "off", "toggle"):
            return "ANTI_ICE_CARB_HEAT_TOGGLE", 0

    elif system == "fuel_pump":
        if action in ("on", "off", "toggle"):
            return "FUEL_PUMP_TOGGLE", 0
```

`_resolve_command` returns `tuple[str | None, int]` and has exactly one failure channel
(`return None, 0` at L214, rendered as an error at L241-242). Refusing `"on"`/`"off"`
with a *distinct* message therefore needs either (a) the refusal to live in
`set_aircraft_control` after resolution, or (b) a widened return. Prefer (a) — it keeps
`_resolve_command` a pure lookup and `procedures.py` shares the check via D-04's re-route.

**Also touched:** `undo_last_command` (`tools.py:590-634`) calls `set_aircraft_control`
with `command_history=None` (L626) so the undo is never recorded — F7 says that makes
the undo's own state change unattributed. Thread `authority` through here too.

---

### `orchestrator/orchestrator/procedures.py` (modified — D-04 re-route, D-06 abort)

**The bypass to close** (`procedures.py:257-288`) — verbatim, this is the second write path:

```python
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
            ...
```

**Constructor to extend** (`procedures.py:210-211`) — mirror `set_aircraft_control`'s
collaborator list:

```python
    def __init__(self, sim_client: TelemetryClient) -> None:
        self._sim_client = sim_client
```

**Loop to modify for D-06** (`procedures.py:227-255`) — the documented continue-on-failure
default lives in the `execute` docstring (L214-219) and the `else` branch:

```python
        for i, step in enumerate(procedure.steps):
            step_result = await self._execute_step(step)
            result.step_results.append(step_result)

            if step_result.success:
                result.steps_completed += 1
                logger.info("Procedure %s step %d/%d OK: %s", ...)
            else:
                result.success = False
                logger.warning("Procedure %s step %d/%d FAILED: %s — %s", ...)

            if step.delay_ms > 0 and i < len(procedure.steps) - 1:
                await asyncio.sleep(step.delay_ms / 1000.0)
```

D-06 needs a *third* outcome distinct from failure (withheld ⇒ `break`). `StepResult`
(L27-36) gains a field; `ProcedureResult.to_dict()` (L48-64) is the serialization
surface Claude sees, so the withheld reason must appear there:

```python
                {
                    "description": sr.step.description or f"{sr.step.system} {sr.step.action}",
                    "command": sr.command,
                    "success": sr.success,
                    "error": sr.error,
                }
```

**Structural guard to add** (Pitfall 1): assert `procedures.py` no longer calls
`send_command` directly. Pattern in `test_voice.py` — see the test section below.

---

### `orchestrator/orchestrator/sim_client.py` (modified — D-05 floor, D-16 watchdog, D-18 clear)

**The function to modify** (`sim_client.py:359-396`), verbatim:

```python
    async def send_command(
        self,
        command: str,
        value: int = 0,
        adapter_id: str = "msfs-adapter",
        timeout: float = 5.0,
    ) -> dict[str, Any]:
        """Send a control command to a sim adapter and wait for acknowledgment."""
        if self._ws is None or self._connection_state != ConnectionState.CONNECTED:
            return {"success": False, "error": "Not connected to telemetry service"}

        command_id = str(uuid.uuid4())
        loop = asyncio.get_running_loop()
        future: asyncio.Future[dict[str, Any]] = loop.create_future()
        self._pending_commands[command_id] = future
        ...
        try:
            await self._ws.send(msg)
        except Exception as exc:
            self._pending_commands.pop(command_id, None)
            return {"success": False, "error": f"Failed to send command: {exc}"}

        try:
            result = await asyncio.wait_for(future, timeout=timeout)
            return result
        except TimeoutError:
            self._pending_commands.pop(command_id, None)
            return {"success": False, "error": "Command timed out"}
```

Three edits, in this order (the ordering is a correctness requirement, RESEARCH §Watchdog):
1. **Floor** — an early `return {"success": False, "error": ...}` mirroring the
   not-connected guard at L367-368. It must run **before** any counter increment.
2. **Watchdog increment** — inside the `except TimeoutError` at L394-396 and the send-exception
   at L387-389; **reset** at the successful-`wait_for` return (L392-393), regardless of
   `result["success"]` (an adapter ack with `success: False` proves the path is alive).
3. **`timeout` default** — promote `5.0` (L364) to a `Settings` field.

**Constructor state** (`sim_client.py:269-286`) — the counter and latch live beside
`_pending_commands`:

```python
        self._last_state_json: str = ""  # for delta detection
        self._pending_commands: dict[str, asyncio.Future[dict[str, Any]]] = {}
```

**Class-level tunables convention** (`sim_client.py:260-267`) — precedent for constants
on the class rather than module globals:

```python
    # Reconnection parameters
    RECONNECT_BASE_DELAY: float = 1.0  # seconds
    RECONNECT_MAX_DELAY: float = 30.0  # seconds
    RECONNECT_BACKOFF_FACTOR: float = 2.0
```

**D-18 clear points** — there is **no** on-reconnect callback list today (only
`_subscribers` for state). The two places that set `CONNECTED` are `connect()`
(`sim_client.py:320`) and `_reconnect()` (`:452`):

```python
            self._ws = await websockets.connect(self._url)
            self._connection_state = ConnectionState.CONNECTED
            self._last_message_time = time.monotonic()
```

Clear the latch inline at both, or add a small `on_reconnect` hook — either way, both
sites must be touched or the CLI and web paths diverge.

**Ack resolution site** (`sim_client.py:520-529`) — where a successful ack lands, if the
counter reset is placed on the receive side instead:

```python
                        elif data.get("type") == "command_ack":
                            cmd_id = data.get("command_id", "")
                            future = self._pending_commands.pop(cmd_id, None)
                            if future and not future.done():
                                future.set_result(
                                    {
                                        "success": data.get("success", False),
                                        "message": data.get("message", ""),
                                    }
                                )
```

**Health registration** (`main.py:83-88`) — the exact call shape for the `command_path`
subsystem (D-17):

```python
        self._health = HealthMonitor()
        self._health.register("simconnect_bridge")
        self._health.register("chromadb")
        self._health.register("whisper")
        self._health.register("claude_api")
        # add: self._health.register("command_path")
```

Update with `self._health.update("command_path", healthy, message)` (`sim_client.py:216-224`).

---

### `orchestrator/orchestrator/command_verifier.py` (modified — close F2)

**Add-a-row pattern** (`command_verifier.py:167-175`):

```python
VERIFICATION_CHECKS: dict[str, VerificationCheck] = {
    "GEAR_DOWN": _check_gear_down,
    "GEAR_UP": _check_gear_up,
    "FLAPS_SET": _check_flaps_set,
    "AP_MASTER": _check_ap_master,
    "HEADING_BUG_SET": _check_heading_bug,
    "AP_ALT_VAR_SET_ENGLISH": _check_alt_set,
    "THROTTLE_SET": _check_throttle,
}
```

**Check template to copy** (`command_verifier.py:113-126`) — ~12 lines each for
`SPOILERS_SET`, `AP_SPD_VAR_SET`, `AP_VS_VAR_SET_ENGLISH`, `KOHLSMAN_SET`, radio sets:

```python
def _check_alt_set(before: SimState, after: SimState, value: int) -> VerificationResult:
    actual = round(after.autopilot.altitude)
    within_tolerance = abs(actual - value) <= 50
    return VerificationResult(
        verified=within_tolerance,
        command="AP_ALT_VAR_SET_ENGLISH",
        expected=f"altitude~={value}ft",
        actual=f"altitude={actual}ft",
        message=(
            f"Altitude selector set to {actual}ft."
            if within_tolerance
            else f"Altitude selector at {actual}ft, expected {value}ft."
        ),
    )
```

The `check is None` early return (`:202-210`) is what makes 60 of 67 commands "verify"
instantly. Whatever D-13's watch trigger becomes, it must distinguish this
`expected="no verification rule"` result from a real one — the string is already there
to key off.

**Constructor timeouts to promote to config** (`command_verifier.py:181-189`):

```python
    def __init__(
        self,
        sim_client: TelemetryClient,
        timeout: float = 3.0,
        poll_interval: float = 0.5,
    ) -> None:
```

---

### `orchestrator/orchestrator/claude_client.py` (modified — thread-through, B3 timeout)

**Collaborator construction** (`claude_client.py:493-495`) — where `AuthorityState` is
accepted (as an `__init__` param, per D-09) rather than constructed:

```python
        self._command_history = CommandHistory()
        self._command_verifier = CommandVerifier(sim_client)
        self._procedure_executor = ProcedureExecutor(sim_client)
```

**Dispatch site** (`claude_client.py:760-768`) — note it does **not** pass `safety_check`,
so production runs on the module singleton today:

```python
        elif name == "set_aircraft_control":
            return await set_aircraft_control(
                self._sim_client,
                args["system"],
                args["action"],
                value=args.get("value"),
                verifier=self._command_verifier,
                command_history=self._command_history,
            )
```

**Timeout table (B3)** (`claude_client.py:707-717`):

```python
    _TOOL_TIMEOUTS: dict[str, float] = {
        "get_sim_state": 2.0,
        ...
        "set_aircraft_control": 5.0,
        "undo_last_command": 5.0,
        "execute_procedure": 30.0,
    }
    _DEFAULT_TOOL_TIMEOUT: float = 5.0
```

Must become `> send_command_timeout + verifier_timeout` (≥ 12.0), or the outer
`asyncio.wait_for` at L723-726 pre-empts the ack timeout and the watchdog never sees it.

**Do not touch** (`claude_client.py:506-510`) — D-07 exists to protect this:

```python
        static_block: dict[str, Any] = {
            "type": "text",
            "text": static_text,
            "cache_control": {"type": "ephemeral"},
        }
```

**Enum** (`claude_client.py:355-373`) — 14 systems today; CMD-09 (deferred) would extend it.
Phase 2 does not change this list.

---

### `orchestrator/orchestrator/config.py` (modified — 7 new fields)

**Field pattern with bounds** (`config.py:119-140`) — the closest precedent:

```python
    turn_threshold: float = Field(
        default=0.5,
        gt=0.0,
        lt=1.0,
        description=(
            "Probability above which the semantic detector calls the turn complete. "
            "Raise it to make MERLIN more willing to wait through a pause."
        ),
    )
    turn_probe_silence_ms: int = Field(
        default=150,
        gt=0,
        description=(
            "Silence observed before consulting the semantic detector. Lower than "
            "vad_silence_ms because the model decides on content, not duration."
        ),
    )
```

Note the description carries the *rationale*, not just the units — match that register.
The D-08a "assisted is a near-no-op for 16 of 20 systems" caveat belongs in the
`authority_level` description.

**Branching-property hazard** (`config.py:232-247`) — the cautionary tale CLAUDE.md
names. If any property or status field branches on `authority_level`, every level needs
a branch:

```python
    @property
    def tts_configured(self) -> bool:
        """Whether TTS is configured for the *selected* backend.

        Each backend is checked against its own credentials -- never another
        backend's. Adding a backend to ``tts/__init__.py`` requires a branch
        here too, or the new backend silently reports itself unconfigured.
        """
        backend = self.tts_backend.lower().strip()
        if backend == "local":
            return bool(self.tts_local_url)
        ...
        return False
```

**Derived-value validator** (`config.py:223-230`) if any authority field needs
cross-field validation (e.g. tool timeout ≥ command + verify):

```python
    @model_validator(mode="after")
    def _build_derived(self) -> Settings:
        if not self.telemetry_service_url:
            self.telemetry_service_url = (
                f"ws://{self.telemetry_service_host}:{self.telemetry_service_port}/ws/telemetry"
            )
        return self
```

---

### `orchestrator/orchestrator/audio_processing.py` (modified — probe decode helper)

**Analog to fork, not reuse** (`audio_processing.py:327-373`). Copy the subprocess block
verbatim; **drop the `preprocess_audio` call at L367** (B7: its silence trimming destroys
the signal Smart Turn judges) and return float32 samples directly instead of re-wrapping
as WAV:

```python
    proc = await asyncio.create_subprocess_exec(
        "ffmpeg",
        "-y",
        "-i",
        "pipe:0",
        "-ar",
        str(TARGET_SAMPLE_RATE),
        "-ac",
        "1",
        "-f",
        "s16le",
        "-acodec",
        "pcm_s16le",
        "pipe:1",
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await proc.communicate(input=webm_bytes)

    if proc.returncode != 0:
        logger.error("ffmpeg conversion failed: %s", stderr.decode(errors="replace")[:300])
        return webm_bytes

    samples = np.frombuffer(stdout, dtype=np.int16).astype(np.float32) / 32768.0
    samples = preprocess_audio(samples, TARGET_SAMPLE_RATE)   # <<< OMIT for the probe path
```

`-ar 16000` is load-bearing: `log_mel_spectrogram` raises on any other rate
(`turn/features.py:136-139`). The int16 → float32 conversion idiom also appears at
`audio_processing.py:320`.

---

### `web/server.py` (modified — AUTH-08, B8, VARC-06 endpoint)

**AppState fields** (`web/server.py:99-115`) — add `authority: AuthorityState | None`,
`health: HealthMonitor | None`, `turn_detector: TurnDetector | None`:

```python
@dataclass
class AppState:
    """Mutable shared state for the MERLIN web server."""

    settings: Any  # Settings from orchestrator.config
    sim_client: TelemetryClient | None = None
    claude_client: ClaudeClient | None = None
    context_store: ContextStore | None = None
    phase_detector: FlightPhaseDetector | None = None
    ...
    sim_connected: bool = False
    bridge_last_seen: float = 0.0
    bridge_connected: bool = False
```

Every field is `X | None = None` and populated in `lifespan`. `web/tests/conftest.py:29`
constructs `AppState(settings=MagicMock())` positionally, so new fields **must** keep
defaults or every web test breaks.

**Startup construction with graceful degradation** (`web/server.py:214-225`) — the model for
building the turn detector once at startup rather than per-probe (Pattern 4):

```python
    stt_backend = getattr(settings, "stt_backend", "whisper")
    if stt_backend == "deepgram" and getattr(settings, "deepgram_api_key", ""):
        state.deepgram_client = DeepgramSTTClient(...)
        logger.info("STT backend: Deepgram Nova-3 (streaming)")
    else:
        state.whisper_client = WhisperClient(base_url=settings.whisper_url)
        logger.info("STT backend: Whisper (local batch)")
```

Prefer `create_turn_detector(settings)` (`turn/__init__.py:42-75`) over constructing
`SmartTurnDetector` directly — it already resolves the fallback at startup and logs the
`fetch_turn_model.py` hint.

**`/api/status` return** (`web/server.py:364-385`) — a flat dict literal; extend it,
`web/tests/test_rest.py:22-38` asserts the existing keys:

```python
    return {
        "sim_connected": bridge_ok,
        "chromadb_available": chromadb_ok,
        "chromadb_documents": (state.context_store.document_count if state.context_store else 0),
        "stt_backend": stt_backend,
        "stt_available": (...),
        "tts_backend": tts_backend,
        "tts_available": (...),
        # Legacy fields for backward compat
        "whisper_available": whisper_ok,
        "elevenlabs_configured": bool(...),
        "claude_model": state.settings.claude_model,
        "telemetry_service_url": state.settings.telemetry_service_url,
    }
```

Add `authority_level`, `authority_reason`, `turn_probe_available`, and the browser's
threshold values (RESEARCH: one call answers AUTH-08 and D-21). Note the defensive
`getattr(state.settings, "x", default)` idiom used at L361-362 — the tests pass a
`MagicMock()` settings object.

**New POST endpoint — analog** (`web/server.py:388-424`):

```python
@app.post("/api/transcribe")
async def transcribe_audio(file: UploadFile, state: AppState = Depends(get_app_state)):
    """Transcribe uploaded audio. ..."""
    audio_bytes = await file.read()
    content_type = file.content_type or ""
    filename = file.filename or "audio.webm"

    logger.info("Received %d bytes of audio (mime: %s)", len(audio_bytes), content_type)

    if state.deepgram_client is not None:
        try:
            ...
            return response
        except Exception as exc:
            logger.error("Deepgram transcription failed: %s", exc)
            return {"text": "", "confidence": 0.0, "error": str(exc)}
```

`UploadFile` + `Depends(get_app_state)` + plain-dict return + never-raise error handling.
If the probe takes JSON fields alongside the blob, the request-model pattern is
`TTSRequest` (`web/server.py:316-317`):

```python
class TTSRequest(BaseModel):
    text: str
```

CLAUDE.md requires Pydantic `BaseModel` for structures crossing boundaries, so the probe
*response* should be a declared model, not a bare dict, even though `/api/status` is legacy-flat.

**B8 — the advisory branch** (`web/server.py:1086-1104`), verbatim; `success` is `True` for
any dict without an `"error"` key, so a dry run currently renders as executed:

```python
        def _on_tool_result(tool_name: str, tool_input: dict[str, Any], tool_result: Any) -> None:
            if tool_name != "set_aircraft_control":
                return
            system = tool_input.get("system", "unknown")
            action = tool_input.get("action", "unknown")
            success = not (isinstance(tool_result, dict) and "error" in tool_result)
            if success:
                message = f"{system.upper()} {action.upper()}"
            else:
                message = f"{system.upper()} {action.upper()} failed"
            command_status_queue.append(
                {
                    "type": "command_status",
                    "system": system,
                    "action": action,
                    "success": success,
                    "message": message,
                }
            )
```

Add a `tool_result.get("advisory")` branch emitting `{"type": "command_advisory", ...}`.
The queue is drained at L1116-1117 and L1130-1131 — no change needed there.

---

### `web/static/app.js` (modified — D-20/D-21 probe, B8 render, AUTH-08 badge)

**Constants to replace** (`app.js:1433-1435`):

```javascript
  const VAD_SPEECH_THRESHOLD = 0.015;  // RMS level to detect speech
  const VAD_SILENCE_MS = 1200;         // Silence duration before sending
  const VAD_MIN_SPEECH_MS = 300;       // Minimum speech duration to send
```

Per RESEARCH these become server-supplied (`turn_probe_silence_ms` for the probe point,
`vad_silence_ms`=400 for the D-21 fallback), with the current literals as defaults.

**The loop to modify** (`app.js:1547-1561`) — the silence branch is where the probe fires;
`requestAnimationFrame` at ~60 Hz means the probe **must** be rate-limited:

```javascript
    } else if (_vadIsSpeaking) {
      // Silence detected while speaking
      if (_vadSilenceStart === 0) _vadSilenceStart = now;

      if (now - _vadSilenceStart >= VAD_SILENCE_MS) {
        // Enough silence — stop recording and send
        if (_vadRecorder && _vadRecorder.state === 'recording') {
          _vadRecorder.stop();
        }
        _vadSilenceStart = 0;
      }
    }

    _vadPollId = requestAnimationFrame(pollVAD);
```

**Blob assembly — B7** (`app.js:1525-1543`). `_vadChunks` accumulates via `start(100)`;
only chunk[0] carries the header, so send `new Blob(_vadChunks)` whole. The existing send
path shows the shape (`app.js:1531-1536`):

```javascript
            const blob = new Blob(_vadChunks, { type: _vadRecorder.mimeType });
            if (state.chatWs && state.chatWs.readyState === WebSocket.OPEN) {
              state.chatWs.send(JSON.stringify({ type: 'audio_start', mime: blob.type }));
              state.chatWs.send(blob);
              setVoiceMode('processing');
            }
```

The probe is a `fetch` POST, not a WS send — nearest fetch analog is `pollStatus`
(`app.js:1944-1966`), including its try/catch-degrades-silently structure:

```javascript
  async function pollStatus() {
    try {
      const res = await fetch(`${API_BASE}/api/status`);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();
      setLed(dom.statusSim, data.sim_connected ? 'green' : 'red');
      ...
    } catch {
      setLed(dom.statusSim, 'red');
      ...
    }
  }
```

**B8 render** (`app.js:846-849` + `showCommandStatus` L479-496) — add a `command_advisory`
case and a third visual state alongside `cmd-success` / `cmd-failure`:

```javascript
      case 'command_status':
        // Aircraft control command executed — show inline status + toast
        showCommandStatus(msg);
        break;
```

```javascript
  function showCommandStatus(msg) {
    var success = msg.success !== false;
    var icon = success ? '✓' : '✗';
    var label = msg.message || (msg.system + ' ' + msg.action).toUpperCase();
    var el = document.createElement('div');
    el.className = 'chat-msg command-status-msg ' + (success ? 'cmd-success' : 'cmd-failure');
    ...
    showCommandToast(icon + ' ' + label, success);
  }
```

**AUTH-08 badge** — reuse the existing LED group (`web/static/index.html:33-49`):

```html
        <div class="status-led-group" role="group" aria-label="Subsystem status indicators">
          <div class="status-indicator" id="status-simconnect" role="status" aria-label="SimConnect status">
            <span class="status-label">SIM</span>
          </div>
          ...
```

An `AUTH` indicator fits the pattern; but AUTH-08 requires the *reason* to be visible,
which an LED colour cannot carry — pair it with a text label or tooltip.

---

### `adapters/msfs/Models/SimDataStructs.cs` (modified — CMD-07 event IDs)

**Enum to extend** (`SimDataStructs.cs:31-83`) — grouped with `//` section comments,
PascalCase members, XML doc on the type:

```csharp
/// <summary>
/// Event IDs for SimConnect system event subscriptions.
/// </summary>
public enum SimEventId
{
    // System events (subscribed via SubscribeToSystemEvent)
    FlightLoaded,
    ...
    // Client events for aircraft control (mapped via MapClientEventToSimEvent)
    // Flaps
    FlapsUp,
    Flaps1,
    ...
    // Instruments / misc
    BarometerSet,
    ParkingBrakeToggle,
    SpoilersToggle,
    SpoilersSet,
    ElevatorTrimSet,
}
```

Append new groups (`// Trim`, `// De-ice`, `// Fuel selector`, `// Crossfeed`) after
`ElevatorTrimSet`. Appending is safe: these values are only used as `MapClientEventToSimEvent`
IDs, never persisted.

**Do not touch** `LowFrequencyData` (`SimDataStructs.cs:136-166`) — CMD-08 was descoped to
refusal (D-02), so no struct change is needed. If that ever reverses, note
`SimDataStructTests.cs:29-35` hard-codes the field count.

---

### `adapters/msfs/SimConnectManager.cs` (modified — CMD-07 CommandMap)

**Table to extend** (`SimConnectManager.cs:245-290`):

```csharp
    /// <summary>
    /// Maps SimConnect event name strings (e.g. "FLAPS_SET") to enum values
    /// for use with TransmitClientEvent.
    /// </summary>
    private static readonly Dictionary<string, SimEventId> CommandMap =
        new(StringComparer.OrdinalIgnoreCase)
        {
            // Flaps
            ["FLAPS_UP"] = SimEventId.FlapsUp,
            ...
            // Instruments / misc
            ["KOHLSMAN_SET"] = SimEventId.BarometerSet,
            ["PARKING_BRAKES"] = SimEventId.ParkingBrakeToggle,
            ["SPOILERS_TOGGLE"] = SimEventId.SpoilersToggle,
            ["SPOILERS_SET"] = SimEventId.SpoilersSet,
            ["ELEVATOR_TRIM_SET"] = SimEventId.ElevatorTrimSet,
        };
```

**Nothing else changes** — registration iterates the map (`SimConnectManager.cs:296-308`):

```csharp
    private void RegisterClientEvents()
    {
        if (_simConnect is null) return;
        Log("INFO", "Registering client events for aircraft control...");
        foreach (var (eventName, eventId) in CommandMap)
        {
            _simConnect.MapClientEventToSimEvent(eventId, eventName);
        }
        Log("INFO", $"{CommandMap.Count} client events registered.");
    }
```

**The failure being fixed** (`SimConnectManager.cs:316-347`) — today an unmapped command
logs and returns `false`, which the orchestrator sees as an ack with `success: false`:

```csharp
        if (!CommandMap.TryGetValue(command, out var eventId))
        {
            Log("WARN", $"Unknown command: {command}");
            return false;
        }
```

Per D-01a, add exactly the ~20 events for enum-exposed systems: `ELEV_TRIM_UP`,
`ELEV_TRIM_DN`, `RUDDER_TRIM_LEFT/RIGHT/SET`, `AILERON_TRIM_LEFT/RIGHT/SET`,
`PITOT_HEAT_TOGGLE`, `TOGGLE_STRUCTURAL_DEICE`, `WINDSHIELD_DEICE_TOGGLE`,
`TOGGLE_PROPELLER_DEICE`, `FUEL_SELECTOR_OFF/ALL/LEFT/RIGHT/SET`,
`CROSS_FEED_OPEN/OFF/TOGGLE`. The six CMD-09 systems' events stay out
(sequencing requirement — `PROCEDURES["shutdown"]` becomes live the moment they land).

---

## Shared Patterns

### Injected collaborators, never module singletons

**Source:** `orchestrator/orchestrator/tools.py:217-225`
**Apply to:** `AuthorityState` everywhere — `set_aircraft_control`, `ProcedureExecutor`,
`TelemetryClient`, `ClaudeClient`, both entry points.

```python
async def set_aircraft_control(
    sim_client: TelemetryClient,
    system: str,
    action: str,
    value: float | None = None,
    verifier: CommandVerifier | None = None,
    safety_check: CommandSafetyCheck | None = None,
    command_history: CommandHistory | None = None,
) -> dict[str, Any]:
```

**Counter-example in the same file** (`tools.py:20`, `:245`) — `_safety_check = CommandSafetyCheck()`
plus `checker = safety_check or _safety_check`. D-09 rejects it; STATE.md still lists it
as an open concern. `authority is None` ⇒ treat as `FULL`, do not reach for a global.

### Data table extends, evaluator is frozen

**Sources:** `command_safety.py:123-179` (`DEFAULT_RULES`), `command_history.py:41-84`,
`command_verifier.py:167-175`, `SimConnectManager.cs:245-290`
**Apply to:** `COMMAND_WATCHED_FIELDS`, the new `VERIFICATION_CHECKS` entries, the
`CommandMap` additions.

```python
@dataclass
class SafetyRule:
    name: str
    commands: set[str]
    condition: Callable[[str, int, SimState, AircraftLimits | None], bool]
    severity: str  # "blocked" | "warning"
    message_template: str
```

Three of this phase's four new mechanisms are table additions. Only the watchdog is new
control flow.

### The severity contract `assisted` keys off

**Source:** `orchestrator/orchestrator/command_safety.py:206-259`
**Apply to:** the gate in `tools.py` — this is the exact object AUTH-03 branches on.

```python
    def check(
        self,
        command: str,
        value: int,
        sim_state: SimState,
        aircraft_type: str = "",
    ) -> SafetyResult:
```

```python
@dataclass
class SafetyResult:
    safe: bool
    command: str
    reason: str = ""
    severity: str = ""  # "warning" or "blocked"; empty when safe
```

`severity` is a bare `str`, not an enum, and `""` means clean. Match that — do not
introduce a competing enum for it in `authority.py`.

### Graceful degradation resolved at startup, not mid-flight

**Source:** `orchestrator/orchestrator/turn/__init__.py:52-75`
**Apply to:** the turn-probe availability flag (D-21), the authority level resolution.

```python
    if choice == "smart":
        from .smart_turn import SmartTurnDetector

        detector = SmartTurnDetector(
            threshold=settings.turn_threshold,
            probe_silence_ms=settings.turn_probe_silence_ms,
        )
        if detector.available:
            return detector
        logger.warning(
            "Semantic turn detection requested but unavailable; using fixed-silence "
            "detection at %d ms. Run `python3 tools/fetch_turn_model.py` to enable it.",
            settings.vad_silence_ms,
        )
        return SilenceTurnDetector(silence_ms=settings.vad_silence_ms)

    expected = ", ".join(repr(d) for d in SUPPORTED_DETECTORS)
    raise ValueError(f"Unknown turn detector: {choice!r}. Expected one of {expected}.")
```

Note the closing `raise ValueError` listing `SUPPORTED_DETECTORS` — an unknown
`authority_level` should fail loudly the same way, not silently fall back.

### Errors returned as dicts, never raised across the tool boundary

**Sources:** `tools.py:242`, `:258-263`; `sim_client.py:368, 389, 396`;
`web/server.py:424`
**Apply to:** every new refusal — advisory dry run, assisted withhold, floor refusal,
CMD-08 refusal, probe endpoint failure.

```python
        return {"error": f"Unknown control: system={system}, action={action}"}
        return {"success": False, "error": "Not connected to telemetry service"}
        return {"text": "", "confidence": 0.0, "error": str(exc)}
```

Claude receives `json.dumps(result)` (`claude_client.py:701`), so the dict *is* the
interface. Keep keys flat and self-describing.

### Test conventions

**Sources:** `orchestrator/tests/test_tools.py:684-690`, `test_command_verifier.py:196-241`,
`test_turn_detection.py:25-50`, `web/tests/conftest.py:24-80`, `test_rest.py:22-38`

Mocked client (≈40 occurrences):

```python
        mock_client = MagicMock(spec=TelemetryClient)
        mock_client.get_state = AsyncMock(return_value=SimState())
        mock_client.send_command = AsyncMock(return_value={"success": True, "message": ""})

        result = await set_aircraft_control(mock_client, "flaps", "2")

        mock_client.send_command.assert_awaited_once_with("FLAPS_2", 0)
```

Settings helper (`test_turn_detection.py:25-28`):

```python
def _settings(**overrides: object) -> Settings:
    base: dict[str, object] = {"anthropic_api_key": "sk-test", "_env_file": None}
    base.update(overrides)
    return Settings(**base)  # type: ignore[arg-type]
```

Time-dependence: **no fake-clock library exists in any extra**. Existing practice is to
shrink the real timeout (`CommandVerifier(mock, timeout=0.3, poll_interval=0.1)`,
`test_command_verifier.py:196-241`) or inject literal timestamps
(`test_command_history.py:45` — `timestamp=1234567890.0`). For `AuthorityState`, inject
the clock instead (RESEARCH §Test Strategy) — new code, no legacy signature to preserve.

ONNX-free scaffolding for the probe endpoint test (`test_turn_detection.py:31-50`):

```python
class _FakeSession:
    """Stand-in for an onnxruntime InferenceSession returning a fixed probability."""

    def __init__(self, probability: float = 0.9, raises: Exception | None = None) -> None:
        self.probability = probability
        self.raises = raises
        self.calls: list[np.ndarray] = []

    def run(self, _outputs: object, feeds: dict[str, np.ndarray]) -> list[np.ndarray]:
        if self.raises is not None:
            raise self.raises
        self.calls.append(feeds["input_features"])
        return [np.array([[self.probability]], dtype=np.float32)]


def _detector_with(session: _FakeSession, **kwargs: object) -> SmartTurnDetector:
    detector = SmartTurnDetector(**kwargs)  # type: ignore[arg-type]
    detector._session = session
    detector._load_attempted = True
    return detector
```

Web tests (`web/tests/test_rest.py:22-38` + `conftest.py:66-80`) — in-process ASGI, no
live server:

```python
async def test_status_returns_subsystem_health(test_app, mock_app_state):
    transport = ASGITransport(app=test_app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/status")

    assert resp.status_code == 200
    data = resp.json()
    assert "sim_connected" in data
```

```python
    srv.app.dependency_overrides[srv.get_app_state] = lambda: mock_app_state
    srv.app.dependency_overrides[srv.get_ws_app_state] = lambda: mock_app_state
```

Structural regression guard (`test_voice.py:1-24, 63-91`) — the pattern for Pitfall 1's
"`procedures.py` must not call `send_command`" test and for the B3 timeout-arithmetic guard:

```python
"""...
The regression guards below are deliberately structural: they assert that
`VoiceOutput` holds no credentials, hardcodes no voice settings, and contains no
provider URLs. Those are the exact properties that were lost, so they are the
exact properties worth pinning.
"""

import inspect
from pathlib import Path

VOICE_SOURCE = Path(inspect.getfile(VoiceOutput)).read_text()


class TestNoProviderCouplingRegression:
    def test_constructor_takes_a_tts_client_not_credentials(self) -> None:
        params = list(inspect.signature(VoiceOutput.__init__).parameters)
        assert "tts_client" in params, (
            "VoiceOutput must accept a TTSClient. If this fails, the Phase 02-02 "
            "protocol refactor has been reverted again (see commit a1b508a)."
        )

    def test_no_provider_urls_in_source(self) -> None:
        for url in ("api.elevenlabs.io", "api.cartesia.ai", "xi-api-key"):
            assert url not in VOICE_SOURCE, f"provider detail {url!r} leaked back into voice.py"
```

`Path(inspect.getfile(X)).read_text()` is also the mechanism `test_command_coverage.py`
uses to reach `SimConnectManager.cs` — except that file is found by path from the repo
root, not by `inspect`.

C# tests (`SimDataStructTests.cs:13-70`) — xUnit + FluentAssertions, `[Fact]` for single
assertions, `[Theory]`/`[InlineData]` for parametrised, with a because-string on every assertion:

```csharp
    [Fact]
    public void LowFrequencyData_HasCorrectSize()
    {
        var size = Marshal.SizeOf<LowFrequencyData>();
        size.Should().Be(2 * sizeof(int) + 16 * sizeof(double),
            "LowFrequencyData has 2 int fields and 16 double fields");
    }

    [Theory]
    [InlineData(typeof(HighFrequencyData))]
    [InlineData(typeof(LowFrequencyData))]
    public void AllStructs_HaveSequentialLayout(Type structType)
```

`CommandMap` is `private static readonly`, so the C# parity test needs either reflection
(`typeof(SimConnectManager).GetField("CommandMap", BindingFlags.NonPublic | BindingFlags.Static)`)
or a visibility change to `internal` + `InternalsVisibleTo`. Decide in planning.

### Lint parity (CLAUDE.md, verified clean at research time)

```bash
ruff check orchestrator/ telemetry-service/ web/ --config orchestrator/pyproject.toml \
  --extend-ignore SIM105,SIM117,F841,B008,B017,B007,UP041
ruff format --check orchestrator/ telemetry-service/ web/ --config orchestrator/pyproject.toml
```

Run from the **repo root**. `ruff check .` inside `orchestrator/` flips isort's
first-party classification and disagrees with CI — new modules (`authority.py`,
`override_detector.py`) are exactly where that bites.

---

## Partial / weak analogs

| File | Role | Data Flow | What's missing |
|---|---|---|---|
| `web/static/app.js` — turn-probe upload loop | component | streaming + rate-limited request-response | No existing browser→server probe or debounced-fetch pattern. Nearest: WS blob send (`app.js:1531-1536`) for assembly, `pollStatus` (`:1944-1966`) for fetch + silent-degrade. The rate limiter (once at threshold, then every 100–200 ms) has no in-repo precedent — write it fresh |
| `orchestrator/tests/test_command_coverage.py` | test (cross-language) | file-I/O + regex | No Python test currently reads C# source. `test_voice.py:24` is the closest (reads its own module's source). Needs a repo-root-relative path to `adapters/msfs/SimConnectManager.cs` and a regex over `["EVENT_NAME"] = SimEventId.X` |
| `web/static/index.html` + `style.css` — authority badge with reason | template / style | n/a | `status-indicator` LEDs (`index.html:33-49`) carry state but not text. Reason (`config` / `override` / `watchdog`) needs a label or tooltip that has no existing counterpart; the `command-toast` classes (`app.js:498-504`) are the nearest text-bearing element |

---

## Metadata

**Analog search scope:** `orchestrator/orchestrator/` (incl. `turn/`),
`orchestrator/tests/`, `web/`, `web/tests/`, `web/static/`, `adapters/msfs/`,
`adapters/msfs/SimConnectBridge.Tests/`, `tools/`, `.env.example`
**Files read:** 28
**Pattern extraction date:** 2026-07-31
**Verified against:** working tree on `chore/v1.3-phase2-context` (clean); line numbers
match those cited in `02-RESEARCH.md`
