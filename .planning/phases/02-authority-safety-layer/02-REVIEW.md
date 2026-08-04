---
phase: 02-authority-safety-layer
reviewed: 2026-08-01T00:00:00Z
depth: standard
files_reviewed: 35
files_reviewed_list:
  - adapters/msfs/Models/SimDataStructs.cs
  - adapters/msfs/SimConnectBridge.Tests/CommandMapTests.cs
  - adapters/msfs/SimConnectManager.cs
  - docs/AIRCRAFT_CONTROLS.md
  - docs/CONFIGURATION.md
  - docs/SMART_CONTROLS.md
  - docs/VOICE_PIPELINE.md
  - orchestrator/orchestrator/audio_processing.py
  - orchestrator/orchestrator/authority.py
  - orchestrator/orchestrator/claude_client.py
  - orchestrator/orchestrator/command_verifier.py
  - orchestrator/orchestrator/config.py
  - orchestrator/orchestrator/main.py
  - orchestrator/orchestrator/override_detector.py
  - orchestrator/orchestrator/procedures.py
  - orchestrator/orchestrator/sim_client.py
  - orchestrator/orchestrator/tools.py
  - orchestrator/tests/test_audio_processing.py
  - orchestrator/tests/test_authority.py
  - orchestrator/tests/test_claude_client.py
  - orchestrator/tests/test_command_coverage.py
  - orchestrator/tests/test_command_verifier.py
  - orchestrator/tests/test_config.py
  - orchestrator/tests/test_override_detector.py
  - orchestrator/tests/test_procedures.py
  - orchestrator/tests/test_sim_client.py
  - orchestrator/tests/test_tools.py
  - tests/integration/test_tool_chain.py
  - web/server.py
  - web/static/app.js
  - web/static/index.html
  - web/static/style.css
  - web/tests/test_chat_ws.py
  - web/tests/test_rest.py
  - web/tests/test_turn_probe.py
findings:
  critical: 5
  warning: 12
  info: 5
  total: 22
status: issues_found
---

# Phase 2: Code Review Report

**Reviewed:** 2026-08-01
**Depth:** standard
**Files Reviewed:** 35
**Status:** issues_found

## Summary

The six invariants named in the phase brief were traced and **all six hold**:

1. `tools.py:450` is the only production call to `TelemetryClient.send_command` (verified by grep across `orchestrator/`, `web/`, `tools/`); `procedures.py` routes through `set_aircraft_control` and carries a structural guard.
2. The floor at `sim_client.py:518` is level-only, re-reads `self._authority.level` at dispatch, takes no caller-supplied level (`test_send_command_takes_no_caller_supplied_level`), caches nothing, and returns before any watchdog mutation.
3. `main.py` contains zero occurrences of `degraded_fallback` and lets construction propagate; `web/server.py:305-327` substitutes `AuthorityState.degraded_fallback(...)` and never leaves `state.authority` as `None` on any path out of `lifespan`.
4. `AuthorityReason` has four members; `AUTHORITY_REASON_TEXT` in `app.js` has four arms with no default fallthrough (`hasOwn` guard), and `renderAuthorityUnknown()` uses a key (`client:unreachable`) that cannot collide with a server-derived `level|reason` key.
5. The `authority_tool_timeout_s > command + verify` budget is enforced by a `Settings` model validator and pinned structurally in `test_claude_client.py`.
6. `web/server.py` `_on_tool_result` branches explicitly on `advisory` and `withheld` before any heuristic.

Lint passes CI-form (`ruff check`/`ruff format --check` clean). 1,302 orchestrator + 92 web + 38 telemetry tests pass locally.

**However, the phase's own stated failure mode — a false confirmation — is still reachable on three separate paths, and the phase newly made engine-shutdown commands executable while explicitly deferring a less-lethal equivalent for exactly that reason.** The findings below are ordered by how close they sit to a control surface.

The most serious pattern: the review of *outcome reporting* stopped at the two new dicts (`advisory`, `withheld`) and never revisited the paths that existed before. `success = "error" not in result` still survives verbatim at `web/server.py:1535`, `safety_note: "Critical system change executed"` is still attached unconditionally, and `undo_last_command` still mutates history before the gate runs.

---

## Critical Issues

### CR-01: BLOCKER — a negative adapter ack is still reported to the pilot as an executed command

**File:** `web/server.py:1535`

**Issue:** The advisory/withheld arms were added, but the fall-through still uses the exact heuristic the phase set out to delete:

```python
success = "error" not in result
message = label if success else f"{label} failed"
```

`TelemetryClient.send_command` returns the adapter's acknowledgment verbatim as `{"success": <bool>, "message": <str>}` (`sim_client.py:713-718`). A negative ack — which `sim_client.py:576-579` explicitly documents as routine ("unregistered events return exactly this ack shape routinely"), and which `SimConnectManager.ExecuteCommand` produces for any unmapped command name or `COMException` — carries **no `error` key**. Reproduced:

```
tool result: {'success': False, 'message': 'Unknown command', 'command': 'GEAR_DOWN',
              'sim_value': 0, 'safety_note': 'Critical system change executed'}
web _on_tool_result would compute success = True
```

The browser then renders a green `✓ GEAR DOWN` for a gear the adapter refused. This is the identical class of defect the docstring immediately above it says was fixed ("the pilot saw 'GEAR DOWN' for a gear that never moved"), and `procedures.py:379` already gets it right (`bool(result.get("success", False))`) — only this call site does not.

`web/tests/test_chat_ws.py` covers `_EXECUTED_RESULT` (`success: True`) and `_BLOCKED_RESULT` (has `error`) but has no case for `{"success": False}` with no `error`, so the gap is invisible to the suite.

**Fix:**
```python
# web/server.py, in _on_tool_result
success = bool(result.get("success", False)) and "error" not in result
message = label if success else f"{label} failed"
```
Add a `web/tests/test_chat_ws.py` case pinning `{"success": False, "message": "Unknown command", "command": "GEAR_DOWN"}` -> `command_status` with `success is False`.

---

### CR-02: BLOCKER — `safety_note: "Critical system change executed"` is attached to commands that were refused, NACKed or never transmitted

**File:** `orchestrator/orchestrator/tools.py:469-470`

**Issue:**

```python
if command in CRITICAL_COMMANDS:
    result["safety_note"] = "Critical system change executed"
```

This runs unconditionally after `send_command` returns, with no check on `result["success"]` or `result.get("refused")`. `result` is the dict Claude reads and relays to the pilot. Two reproduced cases:

- Adapter NACK: `{'success': False, 'message': 'Unknown command', ..., 'safety_note': 'Critical system change executed'}`
- Authority floor refusal (the wiring-bug fallback the whole two-layer design rests on):
  ```
  {'success': False, 'error': 'Refused: MERLIN holds advisory authority only (config);
    nothing was sent to the aircraft.', 'refused': True, 'authority_level': 'advisory',
    'authority_reason': 'config', 'command': 'GEAR_DOWN', 'sim_value': 0,
    'safety_note': 'Critical system change executed'}
  ```

So in the one path the phase describes as "what contains a wiring bug in the meantime" (`tools.py:324`), the tool result simultaneously says *nothing was sent* and *critical system change executed*. This affects the CLI as well as the browser, because it is in the payload handed to Claude, not to a renderer.

**Fix:**
```python
if command in CRITICAL_COMMANDS and result.get("success"):
    result["safety_note"] = "Critical system change executed"
```
and add a test asserting `safety_note` is absent from a refused/NACKed `GEAR_DOWN`.

---

### CR-03: BLOCKER — `undo_last_command` destroys the history entry before the authority gate can refuse the undo, then reports it as reversed

**File:** `orchestrator/orchestrator/tools.py:789-818`

**Issue:** The order is: read the undo action, `pop_last()`, *then* call `set_aircraft_control`.

```python
undo_action = command_history.get_undo_action()
...
last = command_history.pop_last()          # <-- state destroyed here
original_command = last.command if last else "unknown"
result = await set_aircraft_control(..., authority=authority)   # <-- may refuse
result["undone_command"] = original_command
result["undo_description"] = f"Reversed {original_command}: {system} {action}"
```

At `advisory` (or when the gate withholds, or when `command_safety` blocks the reverse command) nothing is transmitted, but the `CommandRecord` is already gone. The pilot can never undo that command again, and the returned dict — which the docstring says "at `advisory` it is described rather than sent" — carries `undo_description: "Reversed GEAR_DOWN: gear up"` in the past tense on top of `advisory: True`. That is a false confirmation in the exact wording the phase says is "the worst failure mode this system has" (`test_command_coverage.py:15`).

`orchestrator/tests/test_tools.py:1133-1156` asserts `result["undone_command"] == "GEAR_DOWN"` and never asserts `len(history)`, so the test currently pins the defective behaviour.

**Fix:** Only pop after a transmitted command, and do not claim a reversal that did not happen:
```python
result = await set_aircraft_control(..., authority=authority)

if result.get("advisory") or result.get("withheld") or "error" in result:
    # Nothing was sent -- leave the undo target on the stack.
    result["undo_target"] = command_history.last_command.command
    result["undo_description"] = f"Would reverse {...}: {system} {action}"
    return result

last = command_history.pop_last()
result["undone_command"] = last.command if last else "unknown"
result["undo_description"] = f"Reversed {result['undone_command']}: {system} {action}"
```
Update `test_undo_at_advisory_sends_nothing` to assert `len(history) == 1` after the advisory undo.

---

### CR-04: BLOCKER — `parking_brake` is a reachable, unguarded blind toggle, the exact defect `carb_heat`/`fuel_pump` were refused for

**File:** `orchestrator/orchestrator/tools.py:167-168`, `orchestrator/orchestrator/tools.py:55-58`, `adapters/msfs/SimConnectManager.cs:286`

**Issue:**

```python
elif system == "parking_brake":
    return "PARKING_BRAKES", 0
```

Every action resolves to `PARKING_BRAKES` — a SimConnect *toggle* — including `"off"`, `"release"` and `"on"`. There is no parking-brake field anywhere in `SimState`, so the position cannot be read. This is bit-for-bit the CMD-08 / D-02 defect described at `tools.py:43-54`:

> Both map "on", "off" and "toggle" to the *same* toggle event, so "carb heat off" turns it ON whenever it was already off — the command does the opposite of what was asked.

But `UNCONFIRMABLE_POSITION_SYSTEMS` lists only `carb_heat` and `fuel_pump` — **neither of which is in the `set_aircraft_control` system enum, and neither of which is registered in `CommandMap`.** The refusal therefore protects two systems Claude cannot name and the adapter cannot execute, while `parking_brake` — which *is* in the enum (`claude_client.py:366`), *is* registered (`SimConnectManager.cs:286`), and *is* in `CRITICAL_COMMANDS` — has no protection at all. `docs/AIRCRAFT_CONTROLS.md:173` documents the action column as literally `*(any)*`.

Operational consequence: "parking brake off" on landing rollout, or "parking brake" spoken twice, sets the brake. There is no `command_safety` rule for `PARKING_BRAKES` either (7 rules, covering gear/flaps/autopilot/throttle only), so `assisted` behaves identically to `full` here.

**Fix:** Add `parking_brake` to the refusal table and only allow the explicit toggle:
```python
UNCONFIRMABLE_POSITION_SYSTEMS: dict[str, str] = {
    "carb_heat": "carb heat",
    "fuel_pump": "fuel pump",
    "parking_brake": "parking brake",
}
...
elif system == "parking_brake":
    if action in ("toggle", "set"):
        return "PARKING_BRAKES", 0
```
Then extend the refusal condition to cover `("on", "off", "release", "set")` for `parking_brake`, and add a `RESOLVER_BRANCH_TABLE` row plus a `test_tools.py` parametrisation. Longer term, add `parking_brake` to `SurfaceState` and use `PARKING_BRAKE_SET` (which takes an absolute value) instead.

---

### CR-05: BLOCKER — engine-starvation commands were newly made executable with no safety rule, while a less lethal equivalent was deferred for exactly that reason

**File:** `adapters/msfs/SimConnectManager.cs:304-313`, `orchestrator/orchestrator/tools.py:184-202`

**Issue:** This phase added `FUEL_SELECTOR_OFF`, `FUEL_SELECTOR_ALL/LEFT/RIGHT/SET`, `CROSS_FEED_OPEN/OFF/TOGGLE` to `CommandMap`. Before the change these resolved to unregistered events and the adapter NACKed them; now `TransmitClientEvent` fires for real. `fuel_selector` and `crossfeed` are already in the `set_aircraft_control` system enum, so Claude can name them directly.

Meanwhile `MAGNETO_SET` was deliberately held back, with the reason stated in `CommandMapTests.cs:243-249` and `docs/AIRCRAFT_CONTROLS.md:190-193`:

> registering `MAGNETO_SET` before the authority gate ... lands turns a named tool call into a working in-flight engine shutdown with nothing in front of it.

`fuel_selector: off` in flight is an in-flight engine shutdown by a different route, and it now has *less* in front of it than magnetos would: it is in the enum (magnetos are not), it is registered (magnetos are not), and `DEFAULT_RULES` contains no rule for `FUEL_SELECTOR_OFF`, `CROSS_FEED_*` or `MIXTURE_SET`. `docs/AIRCRAFT_CONTROLS.md:229-232` and `docs/SMART_CONTROLS.md` both acknowledge the gap in prose while the code ships it. With the default `AUTHORITY_LEVEL=full`, and with `assisted` a documented no-op for these systems (no `warning` rule can fire), a single hallucinated or misheard tool call cuts fuel.

**Fix:** Either defer `FUEL_SELECTOR_OFF` and `CROSS_FEED_OFF` alongside the CMD-09 set (remove from `CommandMap`, add to `CMD09_EVENTS` in `test_command_coverage.py` and `Cmd09EventNames` in `CommandMapTests.cs`), **or** add blocking safety rules before they ship:
```python
SafetyRule(
    command="FUEL_SELECTOR_OFF",
    condition=lambda s, v: not s.on_ground,
    severity="blocked",
    message_template="Fuel selector OFF in flight ({alt} ft AGL) starves the engine.",
),
SafetyRule(command="MIXTURE_SET", condition=lambda s, v: v == 0 and not s.on_ground,
           severity="blocked", ...),
```
Whichever is chosen, the reachable/deferred split must follow one consistent severity rationale — right now it does not.

---

## Warnings

### WR-01: WARNING — `/api/turn-probe` returns HTTP 500 when ffmpeg is absent, contradicting its "never raises" contract

**File:** `web/server.py:829`, `orchestrator/orchestrator/audio_processing.py:357-375`

**Issue:** The docstring at `web/server.py:796-798` and `docs/VOICE_PIPELINE.md` both state:

> Never raises. Every failure path returns a not-ended answer ... The endpoint never raises. Every failure returns a not-ended answer with HTTP 200.

But `decode_webm_to_samples` is called *outside* any `try`. `asyncio.create_subprocess_exec("ffmpeg", ...)` raises `FileNotFoundError` when ffmpeg is not on `PATH` — verified:

```
RAISED: FileNotFoundError [Errno 2] No such file or directory: 'ffmpeg'
```

`np.frombuffer(stdout, dtype=np.int16)` at line 385 also raises `ValueError` on an odd-length buffer (truncated ffmpeg output). Both propagate to Starlette as a 500. Every test in `web/tests/test_turn_probe.py` patches `decode_webm_to_samples`, so this path is never exercised. In a container without ffmpeg the browser would take a 500 on every probe (~7 Hz during speech) with a full traceback logged each time.

**Fix:**
```python
try:
    samples = await decode_webm_to_samples(audio_bytes)
except Exception as exc:
    logger.error("Turn probe decode raised: %s", exc)
    return _turn_probe_result("decode_failed", available=True)
if samples is None:
    return _turn_probe_result("decode_failed", available=True)
```
Add a test that monkeypatches `srv.decode_webm_to_samples` to raise and asserts a 200 with `detector == "decode_failed"`.

---

### WR-02: WARNING — `execute_procedure`'s 30 s deadline is exempt from the B3 timeout invariant it depends on

**File:** `orchestrator/orchestrator/claude_client.py:759-761`

**Issue:** The comment states the problem and then declines to fix it:

```python
# A procedure runs N command-path steps in sequence, so the same ordering
# concern applies per step. Left as-is: no Settings field covers it yet.
"execute_procedure": 30.0,
```

With defaults, a single step's worst case is `authority_command_timeout_s (5) + authority_verify_timeout_s (3) = 8 s`, plus up to 500 ms of inter-step delay. `go_around` and `shutdown` have four steps: 4 x 8 + 1.5 = 33.5 s > 30 s. When the outer `asyncio.wait_for` in `_execute_tool` fires:

- `ProcedureExecutor.execute` is cancelled mid-step, so `send_command`'s own `except TimeoutError` never runs and **the watchdog counter never increments** — the exact failure the `Settings` validator exists to prevent, reintroduced for the compound path;
- Claude receives `{"error": "Tool 'execute_procedure' timed out after 30 seconds"}` with no `steps_completed`, so a procedure that actually transmitted two of four steps is reported as a flat failure;
- `ProcedureResult` is discarded, so nothing was recorded in `CommandHistory` for the later steps either.

`test_claude_client.py::TestCommandPathToolTimeoutOrdering` parametrises only `set_aircraft_control` and `undo_last_command`; `execute_procedure` is untested.

**Fix:** Derive the procedure deadline instead of hardcoding it, and extend the `Settings` validator:
```python
# claude_client.__init__
longest = max(len(p.steps) for p in PROCEDURES.values())
self._tool_timeouts["execute_procedure"] = longest * command_tool_timeout
```
and add an `execute_procedure` row to the structural ordering test.

---

### WR-03: WARNING — the browser's fixed-silence fallback dropped from 1200 ms to 400 ms, and that is the default configuration

**File:** `web/static/app.js:1541`, `web/static/app.js:1676`, `orchestrator/orchestrator/config.py:138-142`

**Issue:** `VAD_SILENCE_MS = 1200` was replaced with `_vadFallbackSilenceMs = 400` (seeded from `vad_silence_ms`, default 400). The fallback fires unconditionally:

```js
if (silenceMs >= _vadFallbackSilenceMs) {
  stopVadRecording();
  _vadSilenceStart = 0;
}
```

The Smart Turn model is **not vendored** (`docs/VOICE_PIPELINE.md`: "The model is not vendored. Fetch it with `python3 tools/fetch_turn_model.py`"), so on a fresh install `create_turn_detector` resolves to `SilenceTurnDetector`, `/api/status` reports `turn_probe_available: false`, and 400 ms of RMS silence is the *only* endpointing. CLAUDE.md decision 23 argues the opposite case explicitly:

> a threshold short enough to feel responsive cuts off mid-sentence pauses, and aviation phraseology is full of them ("descend and maintain... one zero thousand")

400 ms is comfortably inside a normal inter-phrase pause. The docs frame this as "three times more responsive than the old fixed wait even in the fully degraded case" — but the degraded case is the default case, and the tradeoff it describes is the one decision 23 says not to make.

**Fix:** Give the browser a separate fallback threshold from the server-side `SilenceTurnDetector` threshold, defaulted to the pre-change value when no semantic detector is available:
```js
// in pollStatus
_vadFallbackSilenceMs = _turnProbeAvailable
  ? (data.vad_silence_ms || 400)
  : (data.vad_fallback_silence_ms || 1200);
```
and add a `VAD_FALLBACK_SILENCE_MS` setting (default 1200) served from `/api/status`.

---

### WR-04: WARNING — a late turn-probe verdict can truncate the *next* utterance

**File:** `web/static/app.js:1696-1744`

**Issue:** `probeTurnEnd` is fire-and-forget with a 300 ms abort timeout, and its completion handler is:

```js
if (data.ended === true && _vadIsSpeaking) {
  stopVadRecording();
  _vadSilenceStart = 0;
}
```

There is no generation/utterance token. Sequence: a probe is launched for utterance A at 150 ms of silence; the 400 ms fallback ends A at 400 ms; the pilot begins utterance B and `pollVAD` creates a new `_vadRecorder` and sets `_vadIsSpeaking = true`; the probe for A resolves at ~450 ms with `ended: true` and stops B. Because `VAD_MIN_SPEECH_MS = 300`, a B shorter than 300 ms is discarded entirely and the pilot's transmission vanishes with no error shown.

The window is small but is exactly the barge-in / rapid-correction case ("negative — say again") where a lost utterance matters most.

**Fix:** Stamp each utterance and check it on resolution:
```js
let _vadUtteranceId = 0;
// on speech start: _vadUtteranceId++;
async function probeTurnEnd(silenceMs) {
  const utterance = _vadUtteranceId;
  ...
  if (data.ended === true && _vadIsSpeaking && utterance === _vadUtteranceId) {
    stopVadRecording();
    _vadSilenceStart = 0;
  }
}
```

---

### WR-05: WARNING — `OverrideDetector` does not suppress after an orchestrator↔service reconnect, despite claiming it does

**File:** `orchestrator/orchestrator/override_detector.py:229-242`

**Issue:** The comment and the module docstring both claim reconnect is handled:

```python
# F4: an aircraft change, a flight load or a reconnect moves everything
# at once and none of it is the pilot working a control.
if (
    state.aircraft != prev.aircraft
    or state.connected != prev.connected
    or not state.connected
):
```

`SimState.connected` reports whether the **adapter** has SimConnect, not whether the orchestrator's WebSocket to the telemetry service is up. When the orchestrator's own connection drops and `_reconnect()` succeeds (`sim_client.py:622-661`), no frames arrive during the gap; the first frame after it is compared against the last pre-gap frame with `aircraft` and `connected` both unchanged. Everything the pilot moved during the outage — flaps, autopilot selectors, radios, altimeter — lands as unattributed movement in one frame and trips `_record_override`, dropping MERLIN to advisory for the full 120 s cooldown immediately after it recovers.

`_on_connection_established` (`sim_client.py:407`) clears the watchdog on reconnect but has no hook into the detector.

**Fix:** Arm the settle window on the client's own reconnect. Give the detector a public `note_reconnect()` and call it from `_on_connection_established` (or have the detector track `sim_client.connection_state`):
```python
# override_detector.py
def note_reconnect(self) -> None:
    """Suppress detection briefly; a reconnect moves everything at once."""
    self._prev_state = None
    self._settle_until = self._clock() + self._settle_s
```
Add a test that drops and restores `ConnectionState` and asserts no override is recorded on the first post-reconnect frame.

---

### WR-06: WARNING — `OverrideDetector.events` is never drained; the AUTH-06 announcements are dead code and the queue grows without bound

**File:** `orchestrator/orchestrator/override_detector.py:204-212`, `orchestrator/orchestrator/main.py:108-114`, `web/server.py:382-392`

**Issue:** Both composition roots construct an `OverrideDetector`, subscribe `on_telemetry_update`, and never touch `detector.events`. The queue is an unbounded `asyncio.PriorityQueue` (no `maxsize`). Every `_record_override` and `_announce_restore` calls `put_nowait` into a queue with no consumer, so `ProactiveEvent` objects accumulate for the lifetime of the process.

Growth is slow (one event per cooldown drop / lapse), so this is not an urgent leak — but the more important consequence is that the "You've taken the flaps. I'm advisory only until you're done." and "Back to full authority whenever you want me." messages are **never delivered to the pilot on any path**. The browser badge shows the level change on the next 10 s poll; the CLI shows nothing at all (see WR-07). Both messages and both `ProactiveEvent` constructions are dead code today.

**Fix:** Either bound the queue and document it as a future hook —
```python
self._events = event_queue if event_queue is not None else asyncio.PriorityQueue(maxsize=32)
# and use a drop-oldest put so a full queue cannot block the telemetry callback
```
— or wire it: in `main.py` drain it in the conversation loop and speak via `VoiceOutput`; in `web/server.py` drain it into the chat WebSocket as an `authority_event` frame.

---

### WR-07: WARNING — the CLI never displays authority, contradicting `summary()`'s docstring and `docs/CONFIGURATION.md`

**File:** `orchestrator/orchestrator/main.py:437-460`, `orchestrator/orchestrator/authority.py:305-306`, `docs/CONFIGURATION.md`

**Issue:** `AuthorityState.summary()` is documented as "a JSON-serialisable snapshot for `/api/status` **and the CLI**", and `docs/CONFIGURATION.md` states "The authority level always travels with a reason, shown in `/api/status` and in the CLI." Nothing in `main.py` calls `summary()`. `/status` prints SimConnect, context store, doc count, TTS, screen capture and Whisper — no authority. `/health` prints the `HealthMonitor` summary, which carries `command_path` but not the level or reason. The only CLI surface is a single `logger.info` at startup (`main.py:90-95`), which is superseded the moment the watchdog latches or the pilot overrides.

A CLI operator therefore cannot tell whether MERLIN is refusing commands because of `AUTHORITY_LEVEL`, an override cooldown, a latched watchdog or a degraded subsystem — the precise ambiguity D-10 exists to remove.

**Fix:** In `_handle_command`, extend `/status` (and add `/authority`):
```python
auth = self._authority.summary()
print(f"Authority: {auth['level']} ({auth['reason']}, configured: {auth['configured_level']})")
if auth["cooldown_remaining_s"]:
    print(f"  Override cooldown: {auth['cooldown_remaining_s']}s remaining")
if auth["watchdog_latched"]:
    print(f"  Watchdog latched after {auth['consecutive_timeouts']} timeouts")
if auth["degraded_detail"]:
    print(f"  DEGRADED: {auth['degraded_detail']}")
```

---

### WR-08: WARNING — the only end-to-end authority test never runs in CI

**File:** `tests/integration/test_tool_chain.py:30`

**Issue:** `TestAuthorityEndToEnd` is described in its own docstring as "the only place the whole chain runs together", and CLAUDE.md's testing section lists "tool chain including an end-to-end authority dispatch at every level" as covered. But the module carries `pytestmark = [pytest.mark.integration]`, `orchestrator/pyproject.toml:56` sets `addopts = "-m 'not integration'"`, and no CI job collects the root `tests/` directory at all:

- `python-ci.yml:63` — `cd orchestrator && pytest`
- `python-ci.yml:67` — `cd telemetry-service && pytest`
- `python-ci.yml:71` — `pytest web/tests/`
- `python-ci.yml:164` — `cd orchestrator && pytest tests/ -m integration` (the *orchestrator's* tests dir, not the root one)

The new tests need no external service — `TelemetryClient` and `anthropic.AsyncAnthropic` are both doubles — so the `integration` mark is over-broad for them and the cost of the mark is that the phase's headline safety assertion is never executed by any gate.

**Fix:** Move `TestAuthorityEndToEnd` (and `_command_sim_client` / `_claude_with` / `_dispatch_gear_down`) into `orchestrator/tests/test_authority_end_to_end.py`, unmarked, so it runs with the default orchestrator suite. Leave the network-dependent tool-chain tests where they are.

---

### WR-09: WARNING — the turn-probe throttle does not throttle a rotating source, on an unauthenticated ffmpeg-spawning endpoint

**File:** `web/server.py:757-775`

**Issue:**

```python
last = state.turn_probe_seen.get(client_host)
if last is not None and (now - last) * 1000.0 < min_interval_ms:
    return False
if last is None and len(state.turn_probe_seen) >= _MAX_TURN_PROBE_CLIENTS:
    oldest = min(state.turn_probe_seen, key=lambda host: state.turn_probe_seen[host])
    del state.turn_probe_seen[oldest]
```

A first-contact request (`last is None`) is **always accepted**, and when the table is full the LRU entry is evicted to make room. Any caller varying its apparent source address — or a single caller behind a proxy that rewrites `request.client.host`, or simply 65 concurrent connections — bypasses the rate limit entirely, and each accepted probe spawns an ffmpeg process with no concurrency cap. The comment claims "Both bounds below exist to keep a client bug from becoming a local fork bomb"; the table bound holds, the rate bound does not.

Context that raises the severity: the app binds `0.0.0.0:3838` and `CORSMiddleware(allow_origins=["*"], allow_credentials=True)` — this endpoint is reachable cross-origin from any page the pilot has open, and there is no authentication anywhere in `web/server.py`.

**Fix:** Add a global in-flight cap independent of the per-host table:
```python
_TURN_PROBE_SEMAPHORE = asyncio.Semaphore(2)
...
if _TURN_PROBE_SEMAPHORE.locked():
    return _turn_probe_result("throttled", available=True)
async with _TURN_PROBE_SEMAPHORE:
    samples = await decode_webm_to_samples(audio_bytes)
```
and bind the server to `127.0.0.1` by default, or restrict `allow_origins` to the served origin.

---

### WR-10: WARNING — `assisted` treats a missing safety verdict as a clean one, and the gate calls stale telemetry "live"

**File:** `orchestrator/orchestrator/tools.py:365-372`, `orchestrator/orchestrator/tools.py:386-392`, `orchestrator/orchestrator/tools.py:420`

**Issue:** Two related gaps in the same block.

1. **Fail-open on an absent verdict.** `safety_result` is `None` whenever `sim_state is None`, which makes `safety_severity == ""`. The `assisted` branch keys on `safety_severity == "warning"`, so an *absent* verdict takes the same path as a *clean* verdict and the command is transmitted. The docstring says assisted is "a `warning`-severity verdict withholds the command; a clean verdict executes it" — it says nothing about no verdict at all. Missing evidence is not evidence of safety, and this is the one level whose whole job is to be conservative about flagged commands.

2. **"Live telemetry" is not checked for liveness.** The gate comment reads "the single point where the resolved command, the live SimState and the safety verdict all exist". `TelemetryClient.get_state()` (`sim_client.py:396-398`) returns the cached `self._state` unconditionally; it never raises and never reports age. `HEARTBEAT_TIMEOUT` is 15 s, so an adapter that stops publishing while the WebSocket stays open leaves `ConnectionState.CONNECTED` and a `SimState` that can be 15+ seconds old. `command_safety` then evaluates airspeed/altitude interlocks against that frame, the gate accepts the verdict, and `send_command` transmits — because the same open socket satisfies the not-connected check.

**Fix:**
```python
# 1. treat a missing verdict as unsafe at assisted
if level == AuthorityLevel.ASSISTED and safety_severity in ("warning", ""):
    ...  # withhold, with a distinct message for the no-verdict case

# 2. refuse to evaluate a stale frame
if sim_client.last_message_age > STALE_TELEMETRY_S:
    return {"error": "Telemetry is %.0fs stale; I cannot check this command against "
                     "the aircraft's state." % sim_client.last_message_age,
            "command": command, "stale": True}
```
Promote `STALE_TELEMETRY_S` to a `Settings` field alongside the other authority timeouts.

---

### WR-11: WARNING — newly-reachable trim and fuel-selector values are unclamped, undocumented in the tool schema, and cast to `uint` unchecked in the adapter

**File:** `orchestrator/orchestrator/tools.py:137-155`, `orchestrator/orchestrator/claude_client.py:400-413`, `adapters/msfs/TelemetryServiceClient.cs:272-274`

**Issue:** `RUDDER_TRIM_SET`, `AILERON_TRIM_SET` and `FUEL_SELECTOR_SET` became executable in this phase. `_resolve_command` passes the LLM's number straight through with `int(value)` — no range check, no clamp:

```python
if action == "rudder_set" and value is not None:
    return "RUDDER_TRIM_SET", int(value)
```

The tool schema's `value` description (`claude_client.py:400-413`) documents units for flaps, autopilot heading/altitude/VS/speed, throttle/mixture/propeller/spoilers, radio and barometer — but **not** for trim or fuel selector, so Claude has no stated range for the two systems that just became live. On the adapter side:

```csharp
uint value = root.TryGetProperty("value", out var valEl) ? (uint)valEl.GetInt32() : 0u;
```

An unchecked C# cast turns a negative trim value into its two's-complement `uint`, and an out-of-range magnitude is passed to `TransmitClientEvent` verbatim. CI never compiles `SimConnectManager.cs` or `TelemetryServiceClient.cs`, and `CommandMapTests` reads them as text, so nothing checks this path.

**Fix:** Clamp at the resolver (the one place that knows the SimConnect range) and document the range in the schema:
```python
def _clamp(value: float, lo: int, hi: int) -> int:
    return max(lo, min(hi, int(value)))
...
if action == "rudder_set" and value is not None:
    return "RUDDER_TRIM_SET", _clamp(value, -16383, 16383)
```
Add `"trim set/rudder_set/aileron_set: -16383 to 16383; fuel_selector set: index 0-4"` to the `value` description, and add rows to `RESOLVER_BRANCH_TABLE` exercising the bounds.

---

### WR-12: WARNING — a comment in the new end-to-end test documents the surviving CR-01 bug as intended behaviour

**File:** `tests/integration/test_tool_chain.py:408-410`

**Issue:**

```python
# A restrained command is a decision, not a failure: the web layer's
# `success = "error" not in tool_result` heuristic depends on this.
assert "error" not in result
```

The whole point of plan 02-09 was to *remove* that heuristic (`web/server.py:1488-1493`: "The three-way split is explicit rather than inferred from the absence of an `"error"` key"). Leaving a comment saying the design "depends on" it invites the next maintainer to restore or preserve it — and, per CR-01, it *is* still there in the fall-through arm. A comment asserting a guarantee the architecture explicitly repudiated is worse than no comment.

**Fix:** Replace with the actual invariant being pinned:
```python
# A restrained command is a decision, not a failure: no "error" key, so the
# web layer must classify it on the `advisory` marker rather than on error
# presence. See web/server.py::_on_tool_result.
```

---

## Info

### IN-01: INFO — CLAUDE.md's test counts are already wrong

**File:** `CLAUDE.md:340`

**Issue:** Claims "~1,395 tests passing ... 1,302 orchestrator, 55 web, 38 telemetry-service". Measured: 1,302 orchestrator (+2 xfail) ✓, **92 web** (91 passed, 1 skipped) ✗, 38 telemetry ✓ — 1,432, not 1,395. The web figure appears to predate the 37 tests added in `test_rest.py` / `test_turn_probe.py` / `test_chat_ws.py` by this very phase.

**Fix:** Update to `~1,432 ... 1,302 orchestrator, 92 web, 38 telemetry-service`.

---

### IN-02: INFO — AP mode-engage events open suppression windows on fields they do not move

**File:** `orchestrator/orchestrator/override_detector.py:83-89`

**Issue:** `AP_HDG_HOLD -> autopilot.heading`, `AP_ALT_HOLD -> autopilot.altitude`, `AP_VS_HOLD -> autopilot.vertical_speed`, `AP_AIRSPEED_HOLD -> autopilot.airspeed`. These four events engage a *mode*; they do not change the corresponding selector value (that is `HEADING_BUG_SET`, `AP_ALT_VAR_SET_ENGLISH`, etc., which are mapped separately and correctly). Because `has_verification_rule` is False for the `*_HOLD` events, each opens a `settle_s + grace_s = 32 s` window during which genuine pilot movement of that selector is silently attributed to MERLIN. There is no `SimState` field for AP mode engagement, so the correct mapping is the empty tuple.

**Fix:** Map the four `*_HOLD` events to `()` and add a comment explaining that AP mode state is not observable, mirroring the `THROTTLE_SET` note directly below.

---

### IN-03: INFO — `undo_last_command` and `execute_procedure` outcomes produce no browser command frame

**File:** `web/server.py:1495-1496`

**Issue:** `_on_tool_result` early-returns unless `tool_name == "set_aircraft_control"`. An undo refused at advisory, and a procedure aborted by a withheld step, therefore produce no `command_advisory` / `command_withheld` / `command_status` frame at all — the pilot sees only whatever Claude's prose says. The phase's rationale for the three-way split ("the pilot saw 'GEAR DOWN' for a gear that never moved") applies equally to both.

**Fix:** Extend the guard to `{"set_aircraft_control", "undo_last_command"}` and add an `execute_procedure` arm that reads `aborted` / `abort_reason` / `steps_completed` from `ProcedureResult.to_dict()`.

---

### IN-04: INFO — the authority badge can lag a level change by up to 10 seconds

**File:** `web/static/app.js:13`, `web/static/app.js:2373`

**Issue:** `renderAuthority` is driven only by `pollStatus` on a `STATUS_POLL_MS = 10_000` interval. A watchdog latch or a pilot override can therefore leave `FULL (configured)` on screen for up to 10 s while the gate is already refusing commands. The `command_advisory` / `command_withheld` frames cover the case where the pilot asks for something in that window, but a pilot who glances at the badge before deciding whether to ask gets a stale answer.

**Fix:** Push authority on the chat WebSocket when it changes (the override detector already produces an event for exactly this — see WR-06), or drop the badge poll to 2 s.

---

### IN-05: INFO — the probe throttle table is keyed by IP, so browser tabs behind one NAT share a slot

**File:** `web/server.py:161`, `web/server.py:766`

**Issue:** `turn_probe_seen` is keyed on `request.client.host`. Two pilots on one LAN behind a NAT, or two tabs of the overlay and the main UI, share a single 75 ms slot and will throttle each other's probes. Harmless (the fallback covers it) but it means the throttle measures something other than what it claims.

**Fix:** Key on a per-session identifier the browser generates and sends with the probe, keeping the IP-based table only as a coarse abuse bound.

---

_Reviewed: 2026-08-01_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_
