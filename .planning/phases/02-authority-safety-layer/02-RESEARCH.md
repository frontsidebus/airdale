# Phase 2: Authority & Safety Layer — Research

**Researched:** 2026-07-31
**Domain:** Runtime authority gating over an out-of-process sim command path; state-delta actor attribution; circuit-breaker latching; browser→server semantic turn probing
**Confidence:** HIGH for codebase findings (all line-verified against `main` @ `7127a2b`), MEDIUM for external attribution prior art

---

## Summary

Every locked decision in CONTEXT.md is implementable, but **five of them rest on premises about the existing code that do not hold**. The discuss-phase scouting identified the right *files*; this research read them and found that three "reusable assets" are not reusable as described, one required runtime object is never instantiated, and two requirements (CMD-07, CMD-08) span the C# adapter, which nobody has looked at yet.

The single largest finding: `_resolve_command` in `tools.py` can emit **67 SimConnect event names**; the MSFS adapter's `CommandMap` registers **36**. The 31 missing ones include *every* event for all six systems CMD-07 wants to expose — plus 20 more for four systems that are *already in the enum today*. So CMD-07 as written ("makes reachable what is already there") delivers nothing without C# work, and the repo currently ships four live command systems that fail at the adapter.

The second largest: `CommandHistory._extract_relevant_state()` is an **undo** snapshot, not a "fields this command affects" map. It returns `{}` for gear, every toggle, throttle, and trim. D-11's plan to reuse it for override detection needs a genuinely new mapping — and only 7 of 20 commandable systems are visible in telemetry at all, which structurally bounds AUTH-05.

**Primary recommendation:** Sequence the phase as five workstreams with the blocking findings resolved first — (0) telemetry/adapter substrate for CMD-07/08, (1) `AuthorityState` + gate + floor, (2) watchdog + wiring, (3) override detection, (4) VARC-06 web turn probe. Workstreams 1–2 and 4 are independent and parallelisable; 3 depends on 1; 0 blocks CMD-07/08 only and can be descoped without touching AUTH-01…08.

---

## User Constraints (from CONTEXT.md)

### Locked Decisions

Copied verbatim from `.planning/phases/02-authority-safety-layer/02-CONTEXT.md`. **Do not re-litigate.**

**Scope: the unreachable control systems**
- **D-01:** The six systems that `_resolve_command` handles but the `set_aircraft_control` enum omits — `magnetos`, `carb_heat`, `fuel_pump`, `starter`, `primer`, `lights` — are **in scope**, in this order: build AUTH gating first, fix the resolution defect second, expose them in the enum third. Sequencing matters: exposing them before gating would put the most dangerous commands in the surface (`magnetos: off`, `starter` in flight, `fuel_selector: off`) behind no rule at all.
- **D-02:** `carb_heat` and `fuel_pump` currently map `"on"`, `"off"`, and `"toggle"` to the same toggle event (`tools.py:184-190`), so "carb heat off" turns it **on** when it was already off. Fix with telemetry-aware resolution — read current state, emit the toggle only when the requested state differs. Latent today because the systems are unreachable; live the moment D-01 lands.

**Enforcement chokepoint**
- **D-03:** Authority policy lives in `set_aircraft_control` (`tools.py:217`), where full `SimState` and the safety verdict are already available. This is required, not incidental: `assisted` is defined as "execute if safety is clean, withhold on `warning`", so the gate must sit where the safety verdict exists.
- **D-04:** `ProcedureExecutor._execute_step` (`procedures.py:259-269`) is re-routed through `set_aircraft_control` instead of calling `_resolve_command` + `send_command` directly. This closes a live gap — multi-step procedures currently reach SimConnect with **no safety check whatsoever**, because the check went into `tools.py` and never into `procedures.py`.
- **D-05:** A thin, level-only check in `TelemetryClient.send_command` (`sim_client.py:359`) refuses everything when authority is `advisory`. No safety re-run, no policy weight — a structural floor so a future caller that bypasses `set_aircraft_control` cannot reach the sim unnoticed. Chosen because the "remember to add the check" approach has already failed once in this exact code path.
- **D-06:** When authority withholds a step mid-procedure, **abort and hand back to the pilot** — do not continue. This deliberately overrides `ProcedureExecutor`'s documented continue-on-failure default. Rationale: a failed step means the sim didn't take it; a withheld step means MERLIN has decided it shouldn't be acting unsupervised, and continuing past that is precisely acting unsupervised. MERLIN reports which step and how many completed.

**Advisory semantics**
- **D-07:** In `advisory`, the tool stays in the schema and returns a **dry-run result** — the gate resolves the command, runs the safety check, then returns `{advisory: true, would_execute: <event>, safety: <verdict>}` without transmitting. Rejected alternative: removing `set_aircraft_control` from `TOOL_DEFINITIONS` per level. Prompt caching is a prefix match rendered `tools` → `system` → `messages`, and a tool-definition change invalidates all three tiers — so a dynamic tool list would invalidate the cached MERLIN persona block (`claude_client.py:509`) on every request. The cache-preserving alternative (mid-conversation tool changes) requires Opus 5 or newer; this project runs Sonnet 4.
- **D-08:** Enforcement is in code, never in the prompt. Consistent with the recorded principle that safety layers do not depend on Claude behaving well.

**Authority state**
- **D-09:** Authority is **mutable runtime state**, not just a config read — AUTH-06 drops it to `advisory` on override. It lives in an injected `AuthorityState` object seeded from `settings.authority_level`, passed to `set_aircraft_control` alongside the `verifier` / `command_history` / `safety_check` params it already accepts, and handed to `TelemetryClient` for the floor. Rejected: a module-level singleton like `_safety_check` (`tools.py:20`) — that is the global-mutable-state shape v1.2 Phase 4 spent a plan removing from `web/server.py`, and which STATE.md still lists as an open concern.
- **D-10:** `AuthorityState` carries a **reason** alongside the level (`config` / `override` / `watchdog`) so AUTH-08 can distinguish "MERLIN is deferring to the pilot" from "MERLIN cannot reach the sim". Same level, materially different situations.

**Override detection**
- **D-11:** Detection is a **continuous watch in `ProactiveMonitor`** — a new `_check_override()` in `on_telemetry_update()` (`proactive_monitor.py:145`), alongside the existing `_check_emergencies` / `_check_deviations` / `_check_callouts`. Compare each `SimState` against `CommandHistory`'s recent records using the existing `_extract_relevant_state()` (`command_history.py:209`), which already extracts exactly the fields a given command affects.
- **D-12:** An override is **any unattributed change on a watched field** — the field moved and no recent `CommandRecord` accounts for it. Direction-agnostic: flaps 2 → flaps 3 counts as much as flaps 2 → flaps up, because both mean the pilot is working that system. Deliberately biased toward sensitivity: a false positive costs one advisory window, a false negative leaves MERLIN commanding an aircraft the pilot is already flying. **Implementation risk to plan around:** telemetry reports state, not provenance. "The pilot did it" can only mean "no matching recent `CommandRecord`", and MERLIN's own commands take up to 3s to appear in telemetry. Get the correlation wrong and MERLIN detects itself as the pilot.
- **D-13:** The watch opens when `CommandVerifier` **confirms** the aircraft reached the commanded state, then runs for a configurable grace window (~30s default). This sidesteps the attribution race by construction — MERLIN's own change is what closes verification, so anything after it is by definition not MERLIN's. A command the sim never applied is never watched.
- **D-14:** Cooldown is a **rolling timer**: drop to `advisory` for a configurable period, each new override pushes the expiry out, auto-restore when it lapses. Sustained pilot activity keeps MERLIN advisory; a single false positive costs one window rather than the rest of the flight — which matters given the deliberately sensitive rule in D-12. MERLIN announces both the drop and the restore.

**Watchdog**
- **D-15:** A per-command ack timeout **already exists** — `send_command` wraps the ack future in `asyncio.wait_for(timeout=5.0)` and returns `{"success": False, "error": "Command timed out"}`. AUTH-07's new part is the **latch**, not the timeout.
- **D-16:** The latch trips after **N consecutive ack timeouts** (3 by default), counter reset on any successful ack. Standard circuit-breaker shape. Tolerates a dropped WebSocket frame or momentary sim hitch — both routine for an out-of-process adapter reached over WS from WSL2 to a Windows host — while catching a genuinely dead command path in roughly 15s.
- **D-17:** A latched watchdog sets level `advisory` with reason `watchdog` (per D-10), and registers command-path health via the existing `HealthMonitor` (`sim_client.py:206`) so `/api/status` can render "advisory (command path down)". Rejected: a fourth authority state, which would thread through the gate, the floor, the status endpoint, the UI, and the tests for no behavioral gain.
- **D-18:** The latch clears on **telemetry reconnect / heartbeat recovery**. A latch that stops command issuance would otherwise deadlock — no commands means no successful ack to clear it. `TelemetryClient` already runs a heartbeat loop and reconnects with exponential backoff, and the same WebSocket carries both telemetry and commands, so telemetry flowing again is direct evidence the command path is back. No probe traffic, no pilot action required.

**Web-path semantic turn detection (VARC)**
- **D-19:** The web path does **not** use Deepgram endpointing — `deepgram_client.transcribe()` is batch, and the turn decision happens in the browser via RMS energy with `VAD_SILENCE_MS = 1200` (`app.js:1433-1435`). That is 3× the local fixed fallback (`vad_silence_ms: 400`) and 8× the semantic probe point (`turn_probe_silence_ms: 150`).
- **D-20:** Architecture: **browser probes, server decides.** Lower the browser's silence threshold toward `turn_probe_silence_ms`, and on each candidate endpoint POST the trailing 8s of audio to a new endpoint that runs the existing `SmartTurnDetector` and returns continue/stop. This is the recorded architectural principle verbatim — a cheap acoustic gate finds candidates and decides *when* to ask; the `TurnDetector` decides *whether* the turn is over — with the gate in JS instead of Silero. Upload is bounded by the model's 8s window (`[batch, 80, 800]`), and probes only fire during silence. Rejected: running the model in-browser via ONNX Runtime Web. It would require reimplementing `features.py` in JavaScript and keeping it numerically identical to the numpy version, and that file's own docstring warns a divergence "would not raise — it would just make turn predictions quietly wrong." Noted for later: continuous audio streaming to the server is the eventual target and is what VARC-02 (Parakeet local streaming STT) will need, but it reworks the web audio path including barge-in, which is too much to carry here.
- **D-21:** When the probe endpoint is unavailable or the model isn't loaded, the browser falls back to fixed-silence endpointing at **400ms**, matching `vad_silence_ms`. Graceful degradation consistent with the rest of the system, and even the degraded web path ends up 3× more responsive than today.

### Claude's Discretion

- Exact default values for the new config fields (grace window, cooldown period, consecutive-timeout count) — starting points are suggested above; tune during planning. All must be `pydantic-settings` fields, never hardcoded.
- Naming of the new config fields, the `AuthorityState` API surface, and the turn-probe endpoint route.
- Whether the web-path turn work gets its own requirement ID (e.g. VARC-01b) or extends VARC-01. VARC-01 is already marked complete for the local path.

### Deferred Ideas (OUT OF SCOPE)

- **Continuous browser→server audio streaming.** The eventual target for the web voice path and a prerequisite for VARC-02 (Parakeet local streaming STT). Reworks the web audio path including barge-in and per-client cancellation — too large to carry alongside AUTH. D-20 is the incremental step.
- **`claude_model` is on a retired-or-retiring model.** `config.py:27` defaults to `claude-sonnet-4-20250514`, deprecated with a published retirement of 2026-06-15 — now past. Verify whether it still resolves; if not, MERLIN's default model 404s. Its own work item, not Phase 2.
- **`claude_temperature` blocks any model upgrade.** `config.py:42` sets `temperature: 0.3`; sampling parameters are rejected outright on Claude Sonnet 5 and Opus 4.7+, so a model bump 400s until `temperature` / `top_p` / `top_k` are removed. Pairs with the item above.
- **Delete `docs/phase2-controls` and `feat/fuel-controls`.** Both are strictly behind `main`. Housekeeping.
- **Regenerate `.planning/codebase/*.md`.** Dated 2026-03-26, predates all of v1.3.
- **11 `worktree-agent-*` branches** — ~30 commits of leftover agent worktrees. Triage or delete.

---

## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| AUTH-01 | `authority_level` config field, enforced at the single point where `set_aircraft_control` reaches SimConnect | §Gate Chokepoint; `tools.py:239-308` read in full. Single `send_command` call at `:271`. New `orchestrator/authority.py` recommended — see §Module Placement (import-cycle constraint) |
| AUTH-02 | `advisory` describes the intended action and sends nothing | §Advisory Dry-Run. **B8**: `web/server.py:1085-1103` will render a dry run as a *successful* command in the UI unless changed |
| AUTH-03 | `assisted` executes on clean safety, withholds on `warning` | `command_safety.py:206-259` — `check()` returns `SafetyResult(severity ∈ {"", "warning", "blocked"})`. Verdict is already computed at `tools.py:254`. **Caveat:** only 7 rules exist covering 4 systems; `warning` is unreachable for 16 of 20 systems — see §Assisted-Mode Coverage Gap |
| AUTH-04 | `full` preserves current behavior — execute unless `blocked` | Current behaviour is `tools.py:256-263`. `full` = no-op branch |
| AUTH-05 | Pilot override detection identifies manual input contradicting a MERLIN command | §Override Detection. **B4** (`_extract_relevant_state` unusable) and **B6** (only 7 of 20 systems observable) both bound this |
| AUTH-06 | Override drops authority to `advisory` for a cooldown and informs the pilot | §Rolling Cooldown; `ProactiveEvent` queue (`proactive_monitor.py:37-58`) is the announce channel |
| AUTH-07 | Watchdog bounds dispatch→ack; on expiry MERLIN stops issuing and says so | §Watchdog. **B3 is blocking**: the tool-layer timeout pre-empts the command timeout, so the counter never increments |
| AUTH-08 | Authority level + reason surfaced in `/api/status` and the web UI | §Status Surfacing. **B5**: `/api/status` (`web/server.py:343-385`) never reads `HealthMonitor`; `AppState` has no health field |
| CMD-07 | Six systems exposed in the enum, after AUTH gating | **B2 is blocking**: adapter `CommandMap` (`SimConnectManager.cs:245-290`) registers none of their events |
| CMD-08 | `carb_heat` / `fuel_pump` resolve on/off against current telemetry | **B1 is blocking**: no carb-heat or fuel-pump field exists anywhere in the telemetry chain |
| VARC-06 | Semantic turn detection on the web path with fixed-silence fallback | §VARC-06. Conversion path exists and works; **B7** (MediaRecorder container framing) changes what the browser can upload |

---

## BLOCKING FINDINGS

> These make a locked decision unimplementable **as written**. Each is stated with the
> evidence, the scope of the fix, and a descope option. None of them invalidate a
> decision's intent — they change what the work costs.

### B1 — CMD-08 / D-02: no carb-heat or fuel-pump telemetry exists

`[VERIFIED: codebase]`

D-02 says "read current state, emit the toggle only when the requested state differs." **There is no current state to read.**

| Layer | File | Carb heat? | Fuel pump? |
|---|---|---|---|
| SimConnect data definition | `adapters/msfs/Models/SimDataStructs.cs` — `LowFrequencyData` (19 fields) | ✗ | ✗ |
| Adapter model | `adapters/msfs/Models/SimState.cs` — `SurfaceData` (3 fields) | ✗ | ✗ |
| Universal schema | `telemetry-service/telemetry/schema.py` — `AircraftExtensions`, `SurfaceState` | ✗ | ✗ |
| Orchestrator model | `orchestrator/orchestrator/sim_client.py:129-133` — `SurfaceState` | ✗ | ✗ |
| Test harness | `tools/mock_adapter.py:235-239` — acknowledges the command, tracks no state, emits no field | ✗ | ✗ |

`SurfaceState` is exactly `gear_handle: bool`, `flaps_percent: float`, `spoilers_percent: float` (`sim_client.py:129-133`). Nothing else. A repo-wide grep for `carb|CARB|fuel_pump|anti_ice|ANTI_ICE` returns only command-name constants — never a state field.

**Fix scope (4 layers + harness):**
1. `SimDataStructs.cs` — add fields to `LowFrequencyData` (candidate simvars: `GENERAL ENG ANTI ICE POSITION:1` bool, `GENERAL ENG FUEL PUMP SWITCH:1` bool) `[ASSUMED — simvar names from training data; must be confirmed against the MSFS SDK before use]`
2. `SimConnectManager.cs` — matching `RegFloat64`/`RegInt32` calls in the low-frequency registration block (see the pattern at `:396-399`). **Registration order must match struct field order** — the struct is `[StructLayout(LayoutKind.Sequential, Pack = 1)]`.
3. `SimState.cs` + `telemetry/schema.py` + `sim_client.py` — a new `SystemsState` block (preferred over widening `SurfaceState`, which is genuinely about control surfaces), plus `to_legacy_simstate()` flattening in `schema.py:154-186`.
4. `tools/mock_adapter.py` — track and emit the fields, so CMD-08 is testable without MSFS.

**Descope option:** ship CMD-08 as an *error* rather than a wrong action — when `carb_heat`/`fuel_pump` receive `"on"`/`"off"` and no state field is available, return `{"error": "cannot determine current state; use action='toggle'"}`. This satisfies "so 'carb heat off' cannot turn it on" (the literal requirement text) without the telemetry work. Recommend surfacing this choice to the user before planning — it is a real scope fork.

### B2 — CMD-07 / D-01: the MSFS adapter registers none of the six systems' events

`[VERIFIED: codebase]`

CMD-07's premise is that "those six systems already resolve to SimConnect events in shipped code; it makes reachable what is already there." They resolve to event **names**. The adapter has no mapping for any of them, so `ExecuteCommand` hits `SimConnectManager.cs:324-328`, logs `"Unknown command"`, returns `false`, and the ack comes back `success: false`.

`CommandMap` (`SimConnectManager.cs:245-290`) has **36 entries**. `_resolve_command` (`tools.py:36-214`) can emit **67 distinct event names**. The 31 missing:

| System | Missing events | In enum today? |
|---|---|---|
| `trim` | `ELEV_TRIM_UP`, `ELEV_TRIM_DN`, `RUDDER_TRIM_LEFT/RIGHT/SET`, `AILERON_TRIM_LEFT/RIGHT/SET` (8) | **YES — live defect** |
| `deice` | `PITOT_HEAT_TOGGLE`, `TOGGLE_STRUCTURAL_DEICE`, `WINDSHIELD_DEICE_TOGGLE`, `TOGGLE_PROPELLER_DEICE` (4) | **YES — live defect** |
| `fuel_selector` | `FUEL_SELECTOR_OFF/ALL/LEFT/RIGHT/SET` (5) | **YES — live defect** |
| `crossfeed` | `CROSS_FEED_OPEN/OFF/TOGGLE` (3) | **YES — live defect** |
| `lights` | `LANDING_LIGHTS_TOGGLE`, `TOGGLE_TAXI_LIGHTS`, `TOGGLE_NAV_LIGHTS`, `TOGGLE_BEACON_LIGHTS`, `STROBES_TOGGLE`, `PANEL_LIGHTS_TOGGLE` (6) | no (CMD-07) |
| `magnetos` | `MAGNETO_SET` (1) | no (CMD-07) |
| `carb_heat` | `ANTI_ICE_CARB_HEAT_TOGGLE` (1) | no (CMD-07) |
| `fuel_pump` | `FUEL_PUMP_TOGGLE` (1) | no (CMD-07) |
| `starter` | `TOGGLE_STARTER1` (1) | no (CMD-07) |
| `primer` | `TOGGLE_PRIMER` (1) | no (CMD-07) |

Two consequences:

1. **CMD-07 spans C# or it delivers nothing.** Fix = add `SimEventId` enum members (`SimDataStructs.cs:36-79`) + `CommandMap` entries. `RegisterClientEvents()` (`:296-308`) iterates the map, so no other change is needed. This is mechanical but it is a second language and a second test project (`SimConnectBridge.Tests`).
2. **The D-01 danger argument is weaker than stated, and the sequencing requirement is stronger.** `magnetos: off` cannot shut down an engine today — the adapter rejects it. But **all six built-in procedures in `procedures.py` contain at least one step that fails at the adapter right now** (`lights` appears in all six; `shutdown` also has `magnetos`; `takeoff_config` also has `fuel_pump`). Adding the adapter events makes `PROCEDURES["shutdown"]` a genuinely working in-flight engine shutdown that Claude can invoke by name via `execute_procedure` — a tool whose enum is *already* populated from `PROCEDURES.keys()` (`claude_client.py:418-437`) and therefore needs no CMD-07 change to become reachable. **The `execute_procedure` surface bypasses the `set_aircraft_control` enum entirely.** D-04's re-route is what gates it; do not land adapter events before D-04.

**Descope option:** land the 20 events for the four already-exposed systems (closing a live defect) and defer the 11 for the six new ones alongside the enum exposure. Or defer all C# work and treat CMD-07 as "enum + gating only, capability arrives with the adapter."

### B3 — AUTH-07 / D-15, D-16: the ack timeout can never be observed by the gate

`[VERIFIED: codebase]`

D-15 says the timeout "already exists" and only the latch is new. The timeout exists but its result **does not reach the caller**, because two `asyncio.wait_for` deadlines are set to the same value and the outer one wins:

- `claude_client.py:713` — `_TOOL_TIMEOUTS["set_aircraft_control"] = 5.0`, applied at `:722-726` as `asyncio.wait_for(self._dispatch_tool(...), timeout=5.0)`
- `sim_client.py:364` — `send_command(..., timeout: float = 5.0)`, applied at `:392` as `asyncio.wait_for(future, timeout=timeout)`

The outer deadline starts first (`set_aircraft_control` awaits `get_state()` and `ws.send()` before reaching the inner `wait_for`), so on a genuine ack timeout the outer fires, cancels `_dispatch_tool`, and `send_command`'s `except TimeoutError` at `:394-396` never runs. The gate sees `{"error": "Tool 'set_aircraft_control' timed out after 5 seconds"}` from `claude_client.py:729`, not `{"success": False, "error": "Command timed out"}`.

Worse for D-16's "counter reset on any successful ack": when a verifier is attached, `set_aircraft_control` also awaits `verifier.verify_command(...)`, which polls for up to `timeout=3.0` (`command_verifier.py:184`). A **successful** command with a registered verification check therefore takes up to ~3s of polling on top of the ack round-trip, and a slow-but-successful command can also blow the 5.0s tool budget. The consecutive-timeout counter would then be fed by tool-layer cancellations that are not command-path failures at all.

**Fix:** the watchdog counter must be incremented **inside `TelemetryClient.send_command`** (where the ack future actually resolves or times out), never inferred from the tool's return dict. And `_TOOL_TIMEOUTS["set_aircraft_control"]` must exceed `send_command` timeout + verifier timeout with margin. Suggested: command timeout as a config field (default 5.0), verifier timeout as a config field (default 3.0), tool timeout ≥ 12.0.

Note this also means `TelemetryClient` owns the watchdog counter — which is consistent with D-05 already putting the authority floor there, and with D-18 clearing the latch on reconnect (a `TelemetryClient` event).

### B4 — AUTH-05 / D-11: `_extract_relevant_state()` does not do what D-11 says

`[VERIFIED: codebase]`

D-11 and the CONTEXT "Reusable Assets" section both state it "already maps a command to the telemetry fields it affects" and "already extracts exactly the fields a given command affects. Override detection needs exactly this; do not write a second mapping."

Read at `command_history.py:209-224`, it does two things and nothing else:

```python
def _extract_relevant_state(command: str, state: SimState) -> dict[str, Any]:
    snapshot: dict[str, Any] = {}
    if command == "AP_MASTER":
        snapshot["autopilot_master"] = state.autopilot.master
    if command in _STATE_RESTORE_COMMANDS:
        _sys, _act, state_path = _STATE_RESTORE_COMMANDS[command]
        if state_path:
            ...
    return snapshot
```

It captures what is needed to **undo** a command. Coverage:

- Non-empty snapshot for exactly **8 commands**: `AP_MASTER`, plus the 7 `_STATE_RESTORE_COMMANDS` entries with a non-empty `state_path` (`FLAPS_SET`, `HEADING_BUG_SET`, `AP_ALT_VAR_SET_ENGLISH`, `AP_VS_VAR_SET_ENGLISH`, `AP_SPD_VAR_SET`, `SPOILERS_SET`, `KOHLSMAN_SET`).
- Empty `{}` for **everything else**, including `GEAR_UP` / `GEAR_DOWN` / `GEAR_TOGGLE` (the most safety-relevant commands), all 16 toggle commands in `_TOGGLE_COMMANDS`, `THROTTLE_SET` and `ELEVATOR_TRIM_SET` (both mapped with `state_path=""`, deliberately skipped at `:218`).

The mappings are also structurally the wrong shape for the job. Undo asks "what value do I restore?" (a *scalar snapshot*). Override detection asks "which telemetry fields should I watch, and did any of them move?" (a *field-path set*). Those coincide only for value-restore commands.

**Fix:** write a new `COMMAND_WATCHED_FIELDS: dict[str, tuple[str, ...]]` mapping command → dotted state paths, in the same data-driven style as `_STATE_RESTORE_COMMANDS`. Reuse `_get_nested_attr` (`command_history.py:87-91`). Do **not** extend `_extract_relevant_state` — the two consumers want different things and coupling them will break undo.

### B5 — D-11, D-17, AUTH-08: `ProactiveMonitor` is never instantiated, and `/api/status` never reads `HealthMonitor`

`[VERIFIED: codebase]`

Repo-wide grep for `ProactiveMonitor(`:

- Defined at `proactive_monitor.py:112`.
- Tested in `orchestrator/tests/test_proactive_monitor.py` (543 lines) and `test_proactive_integration.py`.
- **Constructed in zero production code paths.** Not in `orchestrator/main.py`, not in `web/server.py`'s `lifespan` (`web/server.py:176-270`).

`web/server.py` subscribes exactly one callback to telemetry — the phase detector at `:205-213`. `orchestrator/main.py` subscribes `_on_state_update` at `:102`, which updates the phase detector (`:404`). Neither calls `on_telemetry_update`.

So D-11's `_check_override()` would be dead code on arrival. **Wiring `ProactiveMonitor` into at least the web path is a prerequisite task**, not an incidental one — and doing so also switches on emergency detection, deviation alerts, callouts, and checklist offers, all of which currently never fire in the browser. That is a behaviour change well beyond AUTH-05 and needs its own plan step (and possibly a config flag), or override detection needs a narrower host.

**Alternative host worth considering:** subscribe an `OverrideDetector` callback directly via `TelemetryClient.subscribe()` (`sim_client.py:352`) in both entry points. Same per-update loop, same prev/curr access, no coupling to the unwired proactive stack, no accidental activation of four other subsystems. This is a deviation from D-11's letter (which names `ProactiveMonitor`) but preserves its intent (a continuous telemetry watch). **Flag to the user before planning.**

Separately for D-17/AUTH-08:

- `HealthMonitor` (`sim_client.py:206-243`) is instantiated **only** in `MerlinOrchestrator.__init__` (`main.py:84`) — the CLI. Registered subsystems: `simconnect_bridge`, `chromadb`, `whisper`, `claude_api`.
- `web/server.py`'s `AppState` (`:100-115`) has no health monitor field, and `/api/status` (`:343-385`) constructs its response dict from scratch — it never calls `HealthMonitor.summary()`.

D-17's "registers command-path health via the existing `HealthMonitor` so `/api/status` can render …" requires adding a `HealthMonitor` to `AppState` and having `/api/status` read it. Both entry points need it, or the CLI and web report different things.

### B6 — AUTH-05 / D-12: only 7 of 20 commandable systems are visible in telemetry

`[VERIFIED: codebase]`

Override detection compares `SimState` fields. The complete set of `SimState` fields that any command can move (`sim_client.py:56-179`):

| Observable | Field path | Commanded by |
|---|---|---|
| ✅ gear | `surfaces.gear_handle` | `gear` |
| ✅ flaps | `surfaces.flaps_percent` | `flaps` |
| ✅ spoilers | `surfaces.spoilers_percent` | `spoilers` |
| ✅ autopilot | `autopilot.{master,heading,altitude,vertical_speed,airspeed}` | `autopilot` |
| ✅ radios | `radios.{com1,com2,nav1,nav2}` | `radio` |
| ✅ barometer | `environment.barometer_inhg` | `barometer` |
| ⚠️ throttle | `engines[].rpm` (indirect proxy only) | `throttle` |
| ❌ trim, mixture, propeller, parking_brake, fuel_selector, crossfeed, deice, magnetos, carb_heat, fuel_pump, starter, primer, lights | *no field exists* | 13 systems |

AUTH-05 is therefore satisfiable for 6 systems cleanly plus throttle-by-proxy, and structurally unsatisfiable for 13. This is fine — the six observable ones are the ones a pilot actually grabs mid-flight — but the plan should state the bound explicitly and the acceptance criteria should not imply universal coverage.

Note `engines[].rpm` is a poor override signal: RPM moves continuously with airspeed, mixture, and prop pitch. Recommend **excluding throttle from the watched set** rather than generating a false positive on every power change. `_check_throttle` in the verifier (`command_verifier.py:129-160`) already treats RPM as directional-only with a ±50 tolerance for exactly this reason.

### B7 — VARC-06 / D-20: MediaRecorder chunks are not independently decodable

`[VERIFIED: codebase + container-format constraint]`

D-20 says "POST the trailing 8s of audio." The browser cannot produce that from what it has.

`app.js:1522-1543` creates a `MediaRecorder` with `audio/webm;codecs=opus` and `start(100)`, accumulating `Blob` chunks in `_vadChunks`. Only the **first** chunk carries the EBML/WebM header and codec-private data; subsequent chunks are bare clusters. Slicing the trailing N chunks produces a stream ffmpeg cannot open.

`_vadAnalyser` cannot substitute: it is polled from `requestAnimationFrame` (`app.js:1560`) reading `fftSize = 512` samples (~10.7 ms at 48 kHz) roughly every 16.7 ms — it **drops ~36% of samples** and cannot reconstruct a continuous waveform.

**Recommended path — upload the whole accumulated blob:**
`new Blob(_vadChunks)` → POST → server decodes → `truncate_or_pad` (`features.py:103-124`) already **keeps the last 8 s** ("Long audio is truncated from the *front*"). So the server-side truncation D-20 wants is free; only the browser-side slicing is impossible. Cost: upload grows with utterance length. Opus at ~24 kbps ⇒ a 15 s utterance ≈ 45 KB, over localhost. Acceptable.

**Do not reuse `convert_webm_to_wav_normalized`** (`audio_processing.py:327-373`). It calls `preprocess_audio` (`:147-185`), which applies a high-pass filter, **trims leading and trailing silence**, and normalizes. Trailing-silence trimming destroys precisely the context Smart Turn is judging, and the golden-value-pinned feature path (`features.py`) was verified against unmodified waveforms. Add a sibling helper that does the ffmpeg decode only (same subprocess invocation, `-ar 16000 -ac 1 -f s16le`) and returns float32 samples directly — or reuse `wav_bytes_to_samples` (`audio_processing.py:312-325`) on an unprocessed WAV.

Also: `log_mel_spectrogram` **raises** on any sample rate other than 16000 (`features.py:136-139`). The ffmpeg `-ar 16000` flag is load-bearing, not incidental.

### B8 — AUTH-02 / D-07: the web UI renders an advisory dry-run as a successful command

`[VERIFIED: codebase]`

`web/server.py:1085-1103`:

```python
def _on_tool_result(tool_name, tool_input, tool_result):
    if tool_name != "set_aircraft_control":
        return
    success = not (isinstance(tool_result, dict) and "error" in tool_result)
    message = f"{system.upper()} {action.upper()}" if success else "... failed"
```

D-07's dry-run shape is `{advisory: true, would_execute: <event>, safety: <verdict>}` — no `"error"` key — so `success` evaluates `True` and the browser receives `{"type": "command_status", "success": true, "message": "GEAR DOWN"}` for a command that was never transmitted. This directly contradicts AUTH-08 ("the current mode is never ambiguous").

**Fix:** `_on_tool_result` must branch on `tool_result.get("advisory")` and emit a distinct status (e.g. `"type": "command_advisory"`), and `app.js` needs a corresponding visual treatment. Small, but it is a required part of AUTH-02/AUTH-08, not polish.

---

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|---|---|---|---|
| Authority level + reason state | Orchestrator (`orchestrator/authority.py`, new) | — | Pure runtime state machine; must import nothing from the package so `sim_client.py` can import it without a cycle (see §Module Placement) |
| Policy gate (level × safety verdict) | Orchestrator (`tools.py:set_aircraft_control`) | — | D-03: the only place holding both `SimState` and the `SafetyResult` |
| Structural floor (level-only refuse) | Orchestrator (`sim_client.py:send_command`) | — | D-05: last point before the wire |
| Ack watchdog counter + latch | Orchestrator (`sim_client.py:TelemetryClient`) | — | **B3**: only place that observes the real ack future; also owns reconnect for D-18 |
| Override detection | Orchestrator (`proactive_monitor.py` or a telemetry subscriber) | — | **B5**: host is contested; needs a decision |
| Command→watched-fields map | Orchestrator (`command_history.py` or new module) | — | **B4**: new data table, not an extension of the undo map |
| Authority surfacing (JSON) | Web server (`web/server.py:/api/status`) | Orchestrator (`HealthMonitor`) | AUTH-08; **B5**: `AppState` needs a health monitor |
| Authority surfacing (visual) | Browser (`app.js`, `index.html`, `style.css`) | — | AUTH-08 + **B8** |
| Turn candidate detection (acoustic gate) | Browser (`app.js` RMS poll) | — | D-20: cheap gate stays client-side |
| Turn decision (semantic) | Web server (new POST endpoint) | Orchestrator (`turn/smart_turn.py`) | D-20: model runs server-side; endpoint is a thin adapter |
| Audio decode for the probe | Web server (ffmpeg subprocess) | Orchestrator (`audio_processing`) | **B7**: needs a non-preprocessing decode helper |
| Carb-heat / fuel-pump state | MSFS adapter (C#) → telemetry service → orchestrator | Mock adapter | **B1**: 4 layers |
| Six systems' SimConnect events | MSFS adapter (C#) | Mock adapter (already done) | **B2** |

### Module Placement — the import-cycle constraint

`[VERIFIED: codebase]`

`orchestrator/sim_client.py` currently imports **nothing** from its own package (`sim_client.py:9-20`: stdlib, `websockets`, `pydantic`). It is the base of the dependency graph — `command_safety.py`, `command_history.py`, `command_verifier.py`, `tools.py`, and `proactive_monitor.py` all import *from* it.

D-05 requires `TelemetryClient.send_command` to consult `AuthorityState`. Therefore:

> `AuthorityState` must live in a module that imports nothing from the orchestrator package.

Recommended: `orchestrator/orchestrator/authority.py` containing only the level enum, the reason enum, the state object, and the watchdog counter. No `SimState` import needed — the state machine is about levels and clocks, not telemetry. The *detector* that consumes `SimState` lives elsewhere.

Alternative if a cycle proves unavoidable: type-only import under `if TYPE_CHECKING:` plus duck-typed runtime access. Prefer the clean module.

---

## Architecture Patterns

### System flow — where authority intercepts

```
Claude tool_use ──> ClaudeClient._dispatch_tool (claude_client.py:760)
                         │  [B3: wait_for(5.0) wraps everything below]
                         ▼
             set_aircraft_control (tools.py:217)
                         │
                    _resolve_command ──> (event, value)     ← CMD-08 needs SimState here
                         │
                    sim_client.get_state() ──> SimState
                         │
                    safety_check.check() ──> SafetyResult{severity}
                         │
        ┌────────────────┴──────── AUTHORITY GATE (D-03, new) ────────┐
        │ advisory: return dry-run, DO NOT SEND        (AUTH-02, D-07)│
        │ assisted: severity == "warning" -> withhold  (AUTH-03)      │
        │ full:     severity == "blocked" -> reject    (AUTH-04)      │
        └────────────────┬────────────────────────────────────────────┘
                         ▼
        TelemetryClient.send_command (sim_client.py:359)
                         │  ── AUTHORITY FLOOR (D-05, new): advisory -> refuse
                         │  ── WATCHDOG (D-16, new): count consecutive ack timeouts
                         ▼
                    WebSocket ──> telemetry service ──> MSFS adapter
                                                              │
                                                     CommandMap lookup  ← B2 fails here
                                                              │
                                                    TransmitClientEvent
                         ┌────────────────────────────────────┘
                         ▼
                    AdapterCommandAck ──> future.set_result (sim_client.py:520-529)
                         │  ── WATCHDOG: reset counter on success
                         ▼
              CommandVerifier.verify_command (poll 0.5s, up to 3.0s)
                         │  ── D-13: confirmation opens the override watch window
                         ▼
              CommandHistory.record(...)

ProcedureExecutor._execute_step (procedures.py:257) ─────┐
   currently calls _resolve_command + send_command       │  D-04 re-routes
   DIRECTLY — bypasses safety AND would bypass the gate ─┘  through the gate

Telemetry broadcast (1 Hz for surfaces/AP/radios) ──> TelemetryClient._listen_loop
                         │
                    subscribers  [B5: only the phase detector is subscribed today]
                         ▼
              ProactiveMonitor.on_telemetry_update (proactive_monitor.py:145)
                    _check_emergencies / _check_deviations / _check_callouts
                    _check_override  ← D-11 (new)  [B5: monitor is never constructed]
```

### Pattern 1: Injected collaborator with a keyword default — follow this for `AuthorityState`

**What:** `set_aircraft_control` already takes optional collaborators as keyword params.
**Where demonstrated:** `tools.py:217-225`.

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

`authority: AuthorityState | None = None` follows exactly. **But note the anti-pattern already present at `:245`:** `checker = safety_check or _safety_check` falls back to the module singleton at `tools.py:20`. D-09 explicitly rejects that shape for authority. If `authority is None`, the correct behaviour is *not* to fall back to a global — it is to treat authority as `full` (preserve current behaviour) so existing callers and tests are unaffected, with the floor in `send_command` as the real backstop. Make this explicit in the docstring.

**Wiring reality:** `ClaudeClient.__init__` constructs `CommandHistory()`, `CommandVerifier(sim_client)`, and `ProcedureExecutor(sim_client)` internally (`claude_client.py:493-495`) and does not accept them as params. `AuthorityState` must be threaded through `ClaudeClient.__init__` → the dispatch site at `:761-768`. Also note `:760-768` does **not** pass `safety_check` — production runs on the module singleton today.

### Pattern 2: Data-driven rule/mapping tables

**What:** behaviour extends by adding a record, never by editing an evaluator.
**Where demonstrated:** `command_safety.py:123-179` (`DEFAULT_RULES`), `command_history.py:41-84` (`_INVERSE_PAIRS`, `_STATE_RESTORE_COMMANDS`, `_NON_REVERSIBLE`), `command_verifier.py:167-175` (`VERIFICATION_CHECKS`), `SimConnectManager.cs:245-290` (`CommandMap`).

The new `COMMAND_WATCHED_FIELDS` map (B4) and any new authority rules must follow this. Dotted paths + `_get_nested_attr` (`command_history.py:87-91`) is the established resolution mechanism.

### Pattern 3: Protocol + factory + `SUPPORTED_*` tuple

**Where demonstrated:** `turn/__init__.py:39-73` (`SUPPORTED_DETECTORS`), `stt/__init__.py`, `tts/__init__.py`.

`authority_level` is a small closed enum, not a pluggable backend — a factory is overkill. **But CLAUDE.md's recorded hazard applies directly:** *"Config properties that branch on a backend selector must have a branch for every supported backend. A missing branch does not error — it silently reports the feature unconfigured."* If any `Settings` property or `/api/status` field branches on authority level, every level needs a branch, and a `SUPPORTED_AUTHORITY_LEVELS` tuple should keep them in sync. Prefer a `StrEnum` (the codebase already uses `StrEnum` for `FlightPhase` and `ConnectionState`, `sim_client.py:25,42`) with exhaustive handling.

### Pattern 4: Graceful degradation, decided at startup

**Where demonstrated:** `turn/__init__.py:52-68` — the smart→silence fallback is resolved at factory time, with the reasoning stated inline: *"That check runs here, at startup, rather than mid-flight — a fallback discovered during a takeoff callout would be the worst possible time to find out."*

D-21's browser fallback should follow: the browser should learn once (at VAD enable, or from `/api/status`) whether the probe endpoint is available, not discover it via a failed fetch during an utterance. Recommend adding `turn_probe_available: bool` to `/api/status` alongside the authority fields, so one call answers both AUTH-08 and D-21.

### Pattern 5: Circuit breaker with reset-on-success and external clear

**What:** count consecutive failures, trip at N, reset on any success, plus an independent clear path so the breaker cannot deadlock.
**Prior art:** the standard closed/open/half-open breaker; D-18's "clear on reconnect" is the half-open substitute — instead of probing, it uses an out-of-band liveness signal (telemetry flow) that the same socket already provides. `[CITED: standard resilience pattern]`

**Where the clear hook goes:** `TelemetryClient._reconnect()` sets `ConnectionState.CONNECTED` at `sim_client.py:452` and `:320` in `connect()`. Both are the natural clear points. Note that `_listen_loop` (`:478-558`) drives reconnection and `_heartbeat_loop` (`:402-428`) breaks out on ping failure — there is **no existing "on reconnect" callback list**, only `_subscribers` for state. Adding a small `on_reconnect` hook (or clearing the latch inline at both connect points) is a required micro-task.

### Anti-patterns to avoid

- **Module-level mutable singleton for authority.** `tools.py:20` (`_safety_check`) is the shape D-09 rejects and STATE.md still lists as an open concern (line 54).
- **Inferring ack timeouts from the tool result dict.** See B3 — the tool layer's own timeout masquerades as a command timeout.
- **Extending `_extract_relevant_state` for override detection.** See B4 — two different questions, one function, guaranteed regression in undo.
- **Reusing `convert_webm_to_wav_normalized` for the turn probe.** See B7 — silence trimming destroys the signal.
- **Putting the gate only in `set_aircraft_control`.** `procedures.py:269` and any future caller bypass it. D-05's floor exists precisely because this failure already happened once in this code path.

---

## Don't Hand-Roll

| Problem | Don't build | Use instead | Why |
|---|---|---|---|
| Dotted state-path resolution | A new getattr walker | `command_history._get_nested_attr` (`:87-91`) | Already exists, already tested, already the convention for `_STATE_RESTORE_COMMANDS` |
| Per-subsystem health tracking + JSON summary | A new health dict in `AppState` | `HealthMonitor` (`sim_client.py:206-243`) — `register`/`update`/`get`/`all_healthy`/`summary` | D-17 names it; it already emits the `{healthy, age_seconds, message}` shape `/api/status` wants |
| Priority-ordered announcement queue for the AUTH-06 drop/restore | A new notification channel | `ProactiveEvent` + `asyncio.PriorityQueue` (`proactive_monitor.py:37-58, 126`) | Priority semantics (3=emergency…0=info) and `tts_override` already defined; the web server already drains it |
| Log-mel feature extraction for Smart Turn | Anything at all, in any language | `turn/features.py:log_mel_spectrogram` | Pinned to golden vectors (`test_turn_features.py`); its docstring warns divergence "would not raise — it would just make turn predictions quietly wrong" |
| 8-second window fitting | Browser-side slicing | `turn/features.py:truncate_or_pad` (`:103-124`) | Already keeps the *last* 8 s and right-pads short input, matching the executable upstream reference (not its prose) |
| webm/opus → 16 kHz mono PCM | A pure-Python opus decoder | ffmpeg subprocess, pattern at `audio_processing.py:334-352` | ffmpeg 6.1.1 verified present; the exact invocation is already in-repo |
| ONNX session lifecycle, threading, availability probing | A new loader | `SmartTurnDetector` (`turn/smart_turn.py:97-145`) | Lazy, thread-safe, caches failure, single-threaded sequential execution already tuned |
| Fake ONNX session for tests | Mocking `onnxruntime` | `_FakeSession` / `_detector_with` (`test_turn_detection.py:31-50`) | Established; keeps CI model-free |
| Sim command exercise without MSFS | New fixtures | `tools/mock_adapter.py` | Already handles all 67 event names including the six dead systems (`:225-283`) — it is *ahead* of the real adapter |
| Circuit breaker | A library | ~30 lines in `TelemetryClient` | Counter + threshold + reset. A dependency here is not worth the supply-chain surface, and the clear path (D-18) is domain-specific anyway |

**Key insight:** this codebase's habit is that the *data table* is the extension point and the *evaluator* is frozen. Three of the four new mechanisms in this phase (watched fields, authority levels, adapter events) are table additions. Only the watchdog is genuinely new control flow.

---

## Override Detection — the attribution problem (research question 1)

### What real systems do

`[CITED: USPTO 8954235, USPTO 7044024, AOPA]` Production autopilots and lane-centering systems **do not infer override from state deltas.** They read an actuator-layer signal: *"when the difference between steering torque expected and measured is greater than a threshold torque value, an automated control system may be disengaged and control relinquished to the operator."* A separate circuit in the pitch servo detects shaft torque directly. Certification authorities require the pilot be able to override the actuator at any time, and the mechanism is force, not state comparison.

**Implication:** D-12's approach is what you do when no provenance channel exists. It is inherently heuristic, and the literature offers no way to make it exact. MSFS/SimConnect exposes no per-simvar "who wrote this."

### The closest applicable prior art: desired/reported reconciliation

`[CITED: docs.aws.amazon.com/iot/latest/developerguide/iot-device-shadows.html; book.kubebuilder.io/reference/good-practices.html]`

The canonical distributed-systems shape for "I commanded X, the world now reports Y, did someone else do it?" is **desired-state / reported-state reconciliation** — AWS IoT Device Shadow (`desired`, `reported`, `delta`) and Kubernetes controllers (`spec` vs `status`). Both hit exactly the failure mode D-12 names ("MERLIN detects itself as the pilot"), and both solve it the same way:

| Mitigation | Where it comes from | Translation to MERLIN |
|---|---|---|
| **Generation counter** — `.metadata.generation` increments on intent change; controller writes `.status.observedGeneration`; `observedGeneration < generation` means "not converged yet, don't react" | Kubernetes `[CITED: kubebuilder]` | The `CommandRecord` timestamp (`command_history.py:102`) is the generation. A field change is only unattributed if it postdates the *convergence* of every record touching that field |
| **Version-based stale rejection** — a shadow update carrying an older version is rejected; clients ignore messages with a version below what they hold | AWS IoT Device Shadow `[CITED: AWS docs]` | Ignore telemetry frames that predate the command dispatch. Relevant because telemetry is 1 Hz and delta-deduplicated |
| **Level-triggered, not edge-triggered** — reconcile against "is the world as I want it", never react once to a specific event | Kubernetes controllers `[CITED: kubebuilder]` | `on_telemetry_update` is already level-triggered (it receives full state). Keep the override check stateless w.r.t. individual transitions; compare current state against the last *attributed* state, not against the immediately previous frame |
| **Suppression window after own write** | Both | Exactly what D-13 specifies |

**D-13 is the right call and it maps onto the generation-counter mitigation.** Anchoring the watch window on *verification success* rather than *dispatch* is the strongest available approximation of `observedGeneration` — the aircraft demonstrably reached the commanded state, so subsequent movement is by construction someone else's.

### But D-13 has a hole: 60 of 67 commands have no verification rule

`[VERIFIED: codebase]`

`VERIFICATION_CHECKS` (`command_verifier.py:167-175`) has **7 entries**: `GEAR_DOWN`, `GEAR_UP`, `FLAPS_SET`, `AP_MASTER`, `HEADING_BUG_SET`, `AP_ALT_VAR_SET_ENGLISH`, `THROTTLE_SET`.

For everything else, `verify_command` returns **immediately**, before any polling, with `verified=True`:

```python
check = VERIFICATION_CHECKS.get(command)
if check is None:
    return VerificationResult(verified=True, ..., message=f"No verification rule for {command}; assumed OK.")
```
— `command_verifier.py:202-210`. Confirmed by `test_command_verifier.py:216-220`, which asserts `mock_client.get_state.assert_not_called()`.

So for `FLAPS_1/2/3`, `SPOILERS_SET`, `AP_SPD_VAR_SET`, `AP_VS_VAR_SET_ENGLISH`, `KOHLSMAN_SET`, and all radio sets — commands whose fields **are** observable and therefore **are** watchable — "confirmation" fires ~0 ms after dispatch, before the sim has done anything and before the next 1 Hz telemetry frame. D-13's guarantee ("MERLIN's own change is what closes verification, so anything after it is by definition not MERLIN's") does not hold for these. The very next frame showing MERLIN's own change would be scored as a pilot override.

**Two options, both cheap:**
1. **Only open watch windows on genuinely verified commands** — i.e. treat `expected == "no verification rule"` as "do not watch." Loses coverage on spoilers/radios/baro/AP-speed but is correct by construction and needs no new code.
2. **Add verification checks for the observable commands** (`SPOILERS_SET`, `AP_SPD_VAR_SET`, `AP_VS_VAR_SET_ENGLISH`, `KOHLSMAN_SET`, `FLAPS_1/2/3`, radio sets). Each is ~12 lines following `_check_alt_set` (`:113-126`). This is additive, follows Pattern 2, and gives full coverage of the observable set.

Recommend option 2 — it is small, it strengthens SAFE-05 as a side effect, and without it the watched set shrinks to gear + flaps-set + AP master/heading/altitude.

### Concrete failure modes and mitigations

| # | Failure mode | Cause | Mitigation |
|---|---|---|---|
| F1 | **Self-detection.** MERLIN's own change scored as pilot override | Telemetry is 1 Hz for surfaces/AP/radios (`SimConnectManager.cs:61` — `lowFrequencyHz = 1`); a command's effect can appear 0–1000 ms after dispatch and up to 3 s after verification polling starts | D-13's post-verification window; plus per-field debounce of ≥2 frames |
| F2 | **Instant false window.** Unverifiable command "confirms" immediately | `command_verifier.py:202-210` | See options 1/2 above — **must be resolved in the plan** |
| F3 | **Continuous-value chatter.** `flaps_percent`, `barometer_inhg`, `rpm` drift by fractions | Float telemetry; `_listen_loop` delta detection (`sim_client.py:505`) compares raw JSON, so any float jitter produces an update | Per-field epsilon thresholds. Precedent: `_check_flaps_set` uses ±5 % (`command_verifier.py:67`), `_check_heading_bug` ±1° (`:99`), `_check_alt_set` ±50 ft (`:119`). Reuse those tolerances |
| F4 | **Sim-initiated change scored as pilot.** Flight loaded, aircraft changed, sim reset, autopilot mode reversion | `SimState.aircraft` changes; `connected` flips | Suppress detection across `aircraft` change, `connected` false→true, and for a settling period after either |
| F5 | **Stale-frame attribution.** A frame captured before dispatch arrives after it | 1 Hz cadence + WS buffering | Compare telemetry `timestamp` (`SimState.timestamp`, `sim_client.py:142`) against `CommandRecord.timestamp`. **Blocker: they are different clocks** — `CommandRecord.timestamp` is `time.monotonic()` (`command_history.py:134`), `SimState.timestamp` is an ISO string from the adapter's `DateTimeOffset.UtcNow`. Use arrival-time monotonic marking on the client side, not the adapter's wall clock |
| F6 | **Startup burst.** First telemetry frame after connect differs from the default `SimState()` on every field | `TelemetryClient._state` initialises to `SimState()` (`sim_client.py:277`) — all zeros/False | Require a `prev_state is not None` guard **and** at least one prior frame from the same `adapter_id`; `on_telemetry_update` already guards `prev is not None` for emergencies/callouts (`proactive_monitor.py:150,157`) but *not* for deviations |
| F7 | **Undo self-trigger.** `undo_last_command` calls `set_aircraft_control` with `command_history=None` (`tools.py:626`), so the undo is never recorded | Deliberate, to keep undo non-recursive | The undo's own state change would be unattributed ⇒ false override. Must be suppressed explicitly |

---

## Watchdog (research support for AUTH-07)

**Existing pieces** `[VERIFIED: codebase]`:
- `send_command` ack future + `asyncio.wait_for(future, timeout=timeout)` — `sim_client.py:370-396`
- `_pending_commands: dict[str, asyncio.Future]` — `:286`, resolved at `:520-529` on `type == "command_ack"`
- Reconnect with exponential backoff (base 1.0, factor 2.0, max 30.0) — `:260-263, 434-472`
- Heartbeat loop (interval 5.0, timeout 15.0) — `:266-267, 402-428`

**Missing pieces:**
1. Counter + threshold + latch state (new, in `TelemetryClient` per B3)
2. A "command path" subsystem registered on `HealthMonitor` (per D-17) — needs a `HealthMonitor` reachable from both entry points (per B5)
3. A clear hook at reconnect (per D-18) — `TelemetryClient` has `_subscribers` for state but no connection-event callbacks

**Timing arithmetic for D-16's "roughly 15s":** 3 consecutive × 5.0 s command timeout = 15 s, *provided* commands are issued back to back. In practice each failure is followed by Claude generating a response and the pilot speaking again, so real time-to-latch is longer. This is fine — but the plan should not assert a 15 s bound as an acceptance criterion. Assert the *count* (3 consecutive timeouts trips it), which is deterministic and testable.

**Interaction with D-05's floor:** once latched, level = `advisory`, so the floor in `send_command` refuses everything — including the commands that would have produced the successful ack needed to reset the counter. D-18 correctly identifies this deadlock and solves it via reconnect. Note the ordering requirement: **the floor check must run before the watchdog counter increments**, or a refused-by-floor command would count as a timeout and re-latch on every attempt.

**Failure modes not covered by D-15/D-16 that the plan should decide:**
- `send_command` returns `{"success": False, "error": "Not connected to telemetry service"}` at `:367-368` **without** creating a future or timing out. Is that a watchdog event? Recommend **no** — it is a connection failure, already visible via `ConnectionState`, and counting it would double-report.
- `send_command` returns `{"success": False, "error": f"Failed to send command: {exc}"}` at `:387-389` on a send exception. Recommend **yes, count it** — the command path is demonstrably broken.
- The adapter can ack with `success: False` (unknown command — see B2, or a COM exception at `SimConnectManager.cs:342-345`). The ack *arrived*, so the path is healthy. Recommend **reset the counter** — this is a command failure, not a path failure. Important given B2: with 31 unregistered events, `success: False` acks are currently common.

---

## Assisted-Mode Coverage Gap (AUTH-03)

`[VERIFIED: codebase]`

AUTH-03 defines `assisted` as "executes commands that pass safety cleanly but withholds any that raise a `warning`." Withholding therefore requires a `warning` rule to exist.

`DEFAULT_RULES` (`command_safety.py:123-179`) has **7 rules** covering **4 systems**:

| Rule | Commands | Severity |
|---|---|---|
| `gear_up_on_ground` | `GEAR_UP` | blocked |
| `gear_up_too_low` | `GEAR_UP` | blocked |
| `gear_down_too_fast` | `GEAR_DOWN` | warning |
| `flaps_above_vfe` | `FLAPS_SET/1/2/3/FULL/INCR` | warning |
| `flaps_full_at_cruise_speed` | `FLAPS_SET`, `FLAPS_FULL` | warning |
| `ap_disconnect_low` | `AP_MASTER` | warning |
| `throttle_idle_on_approach` | `THROTTLE_SET` | warning |

So in `assisted`, MERLIN withholds only: gear-down-fast, flaps-above-Vfe, flaps-full-fast, AP-disconnect-low, throttle-idle-on-approach. **Everything else executes identically to `full`** — including `mixture: set 0` (idle cutoff), `fuel_selector: off`, and, once B2 is fixed, `magnetos: off` and `starter: engage`.

This is not a contradiction of AUTH-03 (which is about the *mechanism*), and REQUIREMENTS.md explicitly lists "no new envelope rules" as a Phase 2 non-goal. **But the plan must state it plainly**, because the phase goal says authority is "explicit, bounded, and never ambiguous," and a pilot reading "assisted" will reasonably assume it is more conservative than it is for 16 of 20 systems. Recommended: document the gap in `docs/SMART_CONTROLS.md` and record it as a follow-on requirement (SAFE-09?) rather than silently shipping it.

STATE.md line 101-109 already records this as "Phase 2 scope input #2" and concludes "Sequence AUTH gating before the enum fix" — consistent, but note the gating being sequenced first does **not** itself add rules.

---

## VARC-06 — web-path semantic turn detection

### The conversion path and its cost

```
MediaRecorder(audio/webm;codecs=opus).start(100)     app.js:1522-1543
   └─ _vadChunks: Blob[]                             (B7: chunk[0] holds the only header)
        │  on silence >= turn_probe_silence_ms
        ▼
   POST new Blob(_vadChunks)  ──────────────────>  new endpoint (web/server.py)
                                                        │
                          ffmpeg -i pipe:0 -ar 16000 -ac 1 -f s16le pcm_s16le pipe:1
                          (pattern: audio_processing.py:334-352)   ~30-60 ms
                                                        │
                          np.frombuffer(int16) / 32768.0 -> float32   (:364)
                                 ⚠ do NOT call preprocess_audio (B7)
                                                        │
                          SmartTurnDetector.evaluate(samples, 16000, silence_ms)
                            └─ truncate_or_pad -> last 8 s      features.py:103
                            └─ log_mel_spectrogram -> (80, 800) features.py:126
                               ⚠ raises unless sample_rate == 16000  features.py:136
                            └─ session.run -> probability in [0,1]  smart_turn.py:164-168
                                                     ~10-20 ms CPU
                                                        ▼
                          {"ended": bool, "probability": float, "detector": "smart_turn"}
```

**Round-trip budget:** ~30–60 ms ffmpeg spawn + ~10–20 ms inference + localhost HTTP ⇒ **~50–100 ms per probe**. Against today's 1200 ms fixed wait, even a 3-probe utterance tail is a large net win. `[ASSUMED — spawn cost estimated, not measured; the plan should include a measurement task]`

**Probe rate control is required.** `pollVAD` runs on `requestAnimationFrame` (~60 Hz, `app.js:1560`). Without debouncing, silence would fire ~60 probes/second. Needed: probe once when silence first crosses `turn_probe_silence_ms`, then at a bounded re-probe interval (suggest 100–200 ms) until either the model says ended or speech resumes. Make the interval a config field surfaced to the browser.

### Environment availability

| Dependency | Required by | Available | Version | Fallback |
|---|---|---|---|---|
| ffmpeg | webm→PCM decode | ✅ | 6.1.1-3ubuntu5 (`/usr/bin/ffmpeg`) | none — already required by the existing transcribe path |
| onnxruntime | `SmartTurnDetector` | ✅ | 1.24.4 | D-21: `available` → False → 400 ms fixed silence |
| smart-turn-v3.2-cpu.onnx | inference | ✅ | 8,679,182 bytes, `~/.cache/merlin/turn/` | D-21 |
| numpy | features + decode | ✅ | orchestrator dependency (`pyproject.toml:19`) | none |

**Packaging gap** `[VERIFIED: codebase]`: `web/requirements.txt` lists only `fastapi, uvicorn[standard], python-multipart, websockets, httpx, aiofiles`. It does **not** list `numpy` — yet `web/server.py:37-48` already imports from `orchestrator.audio_processing`, `orchestrator.claude_client`, etc. The web server has always depended on the orchestrator venv; the requirements file has been incomplete since before this phase. `onnxruntime` lives only in the orchestrator's `vad` extra (`pyproject.toml:30-33`), not `dev`. The plan should either (a) document that the web server runs on the orchestrator venv with `[vad]`, or (b) fix `web/requirements.txt`. Option (a) matches CLAUDE.md's existing instruction ("or use the orchestrator venv"); option (b) is the cleaner fix but is scope creep.

### Browser-side changes (`app.js`)

- `VAD_SILENCE_MS = 1200` (`:1433`) — replaced by two values: a probe threshold (~150 ms, from `turn_probe_silence_ms`) and a fallback threshold (400 ms, from `vad_silence_ms`, per D-21).
- `VAD_SPEECH_THRESHOLD = 0.015` (`:1432`) and `VAD_MIN_SPEECH_MS = 300` (`:1434`) — unchanged.
- These are hardcoded JS constants. To honour "every threshold is a settings field," they should be fetched from `/api/status` (or a new `/api/config`) at VAD-enable time, with the current literals as fallbacks. This also gives the browser the availability flag for D-21 in the same call.
- The `dataavailable`/`stop` handler structure (`:1525-1541`) is unchanged — the probe reads `_vadChunks` without stopping the recorder.

---

## Test Strategy

> `.planning/config.json` sets `workflow.nyquist_validation: false`, so the Nyquist
> Validation Architecture section is intentionally omitted. This section answers the
> phase's explicit test-strategy question instead.

### Established conventions (follow these; do not invent)

`[VERIFIED: codebase]`

| Convention | Evidence |
|---|---|
| pytest + pytest-asyncio, `asyncio_mode = "auto"` | `orchestrator/pyproject.toml:47-49` |
| `MagicMock(spec=TelemetryClient)` + `AsyncMock` for `get_state`/`send_command` | `test_tools.py:43-44`, ~40 occurrences |
| **No fake clock library.** No freezegun, no time-machine, no pytest-freezegun in any extra | `orchestrator/pyproject.toml:24-39` |
| Time-dependent behaviour tested by **shrinking the real timeout** | `test_command_verifier.py:196,207,216,226,241` — `CommandVerifier(mock, timeout=0.3, poll_interval=0.1)` |
| Timestamps injected as literals when constructing records directly | `test_command_history.py:45` — `timestamp=1234567890.0` |
| `asyncio.sleep` patched when retry *ordering* is under test, not duration | `test_whisper_client.py:300,324,340,…` — `@patch("orchestrator.whisper_client.asyncio.sleep", new_callable=AsyncMock)` then asserting `mock_sleep.call_args_list` |
| ONNX stubbed by assigning a fake session | `test_turn_detection.py:31-50` — `_FakeSession` + `_detector_with` set `_session` and `_load_attempted` directly |
| Web tests: `httpx` + `ASGITransport`, `AppState` built from `MagicMock`, no live server | `web/tests/conftest.py:26-60` |
| Telemetry fixtures: `SimState` constructed in-process from typed sub-models via helpers | `orchestrator/tests/conftest.py:62-...`, `test_proactive_monitor.py:29-45` (`_make_state`) |

**Corrective note on the phase brief:** the brief says "the project records telemetry snapshots as JSON fixtures and replays them." CLAUDE.md line 339 says that, but the actual suite **constructs `SimState` objects programmatically** via `_make_state`-style helpers. There are no telemetry JSON fixture files in `orchestrator/tests/`. Follow the code, not the doc.

### Consequence for time-dependent behaviour

Three new mechanisms are time-dependent: the rolling cooldown (D-14), the grace window (D-13), and the consecutive-timeout latch (D-16). Only the latch is *count*-dependent rather than time-dependent.

**Recommended: inject the clock.** All three live in `AuthorityState` / the override detector, both new code, so there is no legacy signature to preserve:

```python
class AuthorityState:
    def __init__(self, level: AuthorityLevel, *, clock: Callable[[], float] = time.monotonic) -> None:
        self._clock = clock
```

Tests then advance a list-driven fake clock and assert exactly. This is strictly better than `asyncio.sleep(0.35)` for a 300 ms cooldown: deterministic, instant, no flake under CI load. It is a *new* pattern for this repo but consistent with its dependency-injection habit (`safety_check`, `verifier`, `command_history` are all injected), and it avoids adding a test dependency.

**Where injection is not available** (`CommandHistory.record` already hardcodes `time.monotonic()` at `:134`), keep the existing approach: construct `CommandRecord` objects with literal timestamps, as `test_command_history.py:45` does.

### Acceptance criteria a planner can write directly

**AUTH-01 / AUTH-04 (gate, `full`)**
- `set_aircraft_control(..., authority=AuthorityState(FULL))` with a clean safety verdict → `sim_client.send_command` called once with the resolved event; result has no `advisory` key.
- `authority=None` → identical behaviour to today (regression guard for every existing `TestSetAircraftControl` test, `test_tools.py:679-783`).

**AUTH-02 (advisory dry run)**
- `AuthorityState(ADVISORY)` → `send_command` **not called** (`mock_client.send_command.assert_not_called()`); result contains `advisory is True`, `would_execute == "<EVENT>"`, and a `safety` verdict.
- Advisory dry run still runs `_resolve_command` — an unknown system still returns the `Unknown control` error (`tools.py:241-242`), not an advisory.
- `web/server.py::_on_tool_result` given an advisory result emits a status distinguishable from success (B8). Testable via `web/tests/test_chat_ws.py` patterns.

**AUTH-03 (assisted)**
- Safety `severity == "warning"` + `ASSISTED` → withheld, `send_command` not called, reason surfaced.
- Safety `severity == ""` + `ASSISTED` → executed.
- Safety `severity == "blocked"` + `ASSISTED` → blocked (existing short-circuit at `tools.py:256-263` still wins; assert the returned dict retains `blocked: True`, not an authority reason).
- Parametrise over the 3 levels × 3 severities = 9 cases. This is the single highest-value test in the phase.

**D-05 (floor)**
- `TelemetryClient.send_command` with authority `ADVISORY` → returns a refusal dict, `self._ws.send` **not awaited**, no entry added to `_pending_commands`.
- Floor refusal does **not** increment the watchdog counter (ordering guard).

**D-04 / D-06 (procedures)**
- `ProcedureExecutor` constructed with an authority in `ADVISORY` → step 1 withheld, `steps_completed == 0`, `result.success is False`, and **no further steps executed** (assert `send_command.call_count == 0` for a 3-step procedure, and that `asyncio.sleep` between steps was not reached).
- Contrast test: a step that *fails* (adapter `success: False`) still continues, preserving the documented continue-on-failure default (`procedures.py:214-219`). Existing `test_procedures.py` (340 lines) covers the failure path — assert it is unchanged.
- Re-route regression: every step now passes through the safety check. Assert a `landing_config` execution with `gear` on the ground is blocked at step 1 (`_gear_up_on_ground`... note `landing_config` uses gear *down*; use `cleanup_after_takeoff`, whose step 1 is `gear up`).

**AUTH-07 (watchdog)**
- 2 consecutive ack timeouts → not latched, level unchanged.
- 3rd consecutive → latched, level `ADVISORY`, reason `WATCHDOG`.
- Successful ack between timeouts → counter reset (2 timeouts, 1 success, 2 timeouts ⇒ not latched).
- Adapter ack with `success: False` → counter **reset**, not incremented (the path is alive).
- `send_command` while latched → refused by the floor, counter unchanged (no re-latch storm).
- Reconnect (`ConnectionState` → `CONNECTED`) → latch cleared, level restored to configured, reason `CONFIG`.
- Test with short timeouts: `send_command(..., timeout=0.05)` against a mock ws that never acks. Follows `test_command_verifier.py:207`.
- **B3 guard:** assert `_TOOL_TIMEOUTS["set_aircraft_control"] > send_command_timeout + verifier_timeout`. A structural test, in the spirit of `test_voice.py`'s regression guards.

**AUTH-05 / AUTH-06 (override)**
- Watched-field map: parametrised test asserting every observable system in `_resolve_command` has an entry, and that no entry names a non-existent `SimState` path (walk with `_get_nested_attr`, expect no `AttributeError`).
- Unattributed change on a watched field, outside any grace window → override detected, level `ADVISORY`, reason `OVERRIDE`, announcement enqueued.
- Same change *inside* the grace window following a verified command → **not** detected (F1).
- Change on a field with no recent record at all → detected.
- `prev_state is None` (first frame) → never detected (F6).
- `aircraft` changed between frames → never detected (F4).
- Float jitter below the per-field epsilon → not detected (F3).
- Rolling cooldown: override at t=0 → advisory; override at t=cooldown/2 → expiry pushed out; no further overrides → auto-restore at the pushed expiry, restore announced (D-14). Fake clock makes this three assertions instead of three sleeps.
- Undo-generated change → not detected (F7).

**AUTH-08 (surfacing)**
- `GET /api/status` returns `authority_level` and `authority_reason`; parametrise all 3 levels × 3 reasons and assert every combination renders (the CLAUDE.md missing-branch hazard).
- `HealthMonitor` reachable from `AppState`; command-path subsystem present in the summary.
- Existing `/api/status` fields unchanged (`web/tests/test_rest.py:23-50` asserts the current shape — extend, don't replace).

**CMD-08**
- If B1 is resolved: `carb_heat off` with state `on` → emits `ANTI_ICE_CARB_HEAT_TOGGLE`; with state `off` → emits nothing and returns a no-op result. Same for `fuel_pump`. Plus `toggle` always emits.
- If descoped: `carb_heat on|off` with no state field → returns the explicit error, never a toggle.

**CMD-07**
- Enum/resolver parity: assert every `system` in the `set_aircraft_control` enum resolves for at least one action, **and** — the new one — that every event `_resolve_command` can emit is present in the adapter's `CommandMap`. The latter requires reading `SimConnectManager.cs` from Python or duplicating the list; a small `tests/test_command_coverage.py` that parses the C# file with a regex is the cheapest honest guard and would have caught B2. Recommend it.
- C# side: extend `SimConnectBridge.Tests` to assert `CommandMap` contains every expected event name.

### Tests requiring update when signatures change

`[VERIFIED: codebase]`

| File | Lines | Why it changes |
|---|---|---|
| `orchestrator/tests/test_tools.py` | 785 total; `TestSetAircraftControl` at `:679-783` (8 tests) | `set_aircraft_control` gains an `authority` param. Existing tests pass no authority ⇒ must still behave as `full`. Also `:530-543` parametrises the six dead systems' resolution — unchanged by CMD-07, but the enum-parity test lives near it |
| `orchestrator/tests/test_procedures.py` | 340 | `ProcedureExecutor.__init__` gains collaborators (`procedures.py:210` takes only `sim_client` today). Every construction site changes. `:175-179` asserts `shutdown` contains magnetos |
| `orchestrator/tests/test_command_verifier.py` | 259 | Only if new `VERIFICATION_CHECKS` entries are added (recommended, §Override Detection option 2). Additive |
| `orchestrator/tests/test_command_history.py` | 516 | Only if the watched-fields map lands in this module. `_extract_relevant_state` itself must be **unchanged** — assert that |
| `orchestrator/tests/test_proactive_monitor.py` | 543 | `ProactiveMonitor.__init__` gains an override detector / authority. `_make_state` helper (`:29-45`) is the fixture to extend with watched fields |
| `orchestrator/tests/test_claude_client.py` | — | `ClaudeClient.__init__` gains an authority param; `_dispatch_tool` passes it through. `_TOOL_TIMEOUTS` change (B3) |
| `orchestrator/tests/test_config.py` | 147 | New settings fields, defaults, and validation bounds |
| `orchestrator/tests/test_sim_client.py` | — | `send_command` gains the floor + watchdog. `TestHealthMonitor` at ~`:626` is the pattern for the command-path subsystem |
| `orchestrator/tests/test_turn_detection.py` | 233 | Unchanged — VARC-06 adds an endpoint, not detector behaviour. `_FakeSession` is reused by the new web test |
| `web/tests/test_rest.py` | — | `/api/status` new fields; new probe endpoint tests |
| `web/tests/test_chat_ws.py` | — | `_on_tool_result` advisory branch (B8) |
| `tests/integration/test_tool_chain.py` | — | End-to-end tool dispatch with authority |
| `tests/test_mock_adapter.py` | — | If mock adapter gains carb-heat/fuel-pump state (B1). `:362-386` already tests the six systems' command handling |
| `adapters/msfs/SimConnectBridge.Tests` | — | New `CommandMap` entries (B2), new struct fields (B1) |

**Baseline verified clean:** `ruff check orchestrator/ telemetry-service/ web/ --config orchestrator/pyproject.toml --extend-ignore SIM105,SIM117,F841,B008,B017,B007,UP041` → "All checks passed!"; `ruff format --check …` → "102 files already formatted". Use these exact commands (CLAUDE.md lines 343-358) — `ruff check .` from inside `orchestrator/` disagrees with CI and has broken it before.

---

## Config Fields (Claude's discretion — recommendations)

All must be `pydantic-settings` fields on `Settings` (`orchestrator/orchestrator/config.py`), with `.env.example` entries and `docs/CONFIGURATION.md` updates. Existing style: `Field(default=..., description=...)`, with `gt=`/`lt=` bounds where meaningful (`config.py:119-140` is the closest precedent).

| Field | Type | Suggested default | Rationale |
|---|---|---|---|
| `authority_level` | `str` | `"assisted"` | Middle setting is the safe default. **Note:** `full` preserves today's behaviour; `assisted` changes it. Ship `full` if backward compatibility matters more than safety-by-default — flag this to the user, it is a real product choice |
| `authority_override_grace_s` | `float` | `30.0` | D-13's stated ~30 s |
| `authority_override_cooldown_s` | `float` | `120.0` | D-14 rolling window. Long enough to cover a pilot working a system through a phase change; short enough that one false positive is not the rest of the flight |
| `authority_watchdog_max_timeouts` | `int` | `3` | D-16 |
| `authority_command_timeout_s` | `float` | `5.0` | Currently the hardcoded default at `sim_client.py:364`. Promoting it to config is required for B3's arithmetic and for fast tests |
| `authority_verify_timeout_s` | `float` | `3.0` | Currently hardcoded at `command_verifier.py:184` |
| `turn_probe_reprobe_ms` | `int` | `150` | VARC-06 probe rate limit; reuses the `turn_probe_silence_ms` scale |

Do **not** add a `Settings` property that branches on `authority_level` unless every level has a branch — see CLAUDE.md's `tts_configured` cautionary tale (lines 364-367) and `config.py:232-267`.

---

## Common Pitfalls

### Pitfall 1: The second write path
**What goes wrong:** the gate lands in `set_aircraft_control`, and `procedures.py` reaches SimConnect unguarded.
**Why it happens:** it already happened — `command_safety.py` was wired into `tools.py:245` in v1.3 Phase 1 and never into `procedures.py:269`. Nothing detected it for months.
**How to avoid:** D-04 re-routes, D-05 floors. Add a structural test asserting `procedures.py` does not import or call `send_command` directly — the `test_voice.py` structural-guard pattern (VOIC-09) exists for exactly this class of regression.
**Warning signs:** `grep -n "send_command" orchestrator/orchestrator/` returning more than `sim_client.py` and `tools.py`.

### Pitfall 2: Trusting doc-stated coverage
**What goes wrong:** `docs/AIRCRAFT_CONTROLS.md:3` claims "**20 systems, 72+ actions**" and documents `starter`, `lights`, etc. as working. The enum has 14 systems and the adapter has 36 events. Three sources of truth, all different, all confidently stated.
**How to avoid:** the enum-parity + adapter-parity tests proposed above turn this into a CI failure rather than a doc drift. Update `AIRCRAFT_CONTROLS.md` and `SMART_CONTROLS.md` as part of the phase.

### Pitfall 3: Detecting yourself as the pilot
Covered in full in §Override Detection F1–F7. The specific trap is F2 — 60 of 67 commands "verify" instantly, so D-13's guarantee silently does not apply to most of them.

### Pitfall 4: The `assisted` illusion
Covered in §Assisted-Mode Coverage Gap. `assisted` behaves identically to `full` for 16 of 20 systems because no `warning` rule exists for them.

### Pitfall 5: `ConnectionError` handling that never fires
`tools.py:247-250` and `:267-269` catch `ConnectionError` around `sim_client.get_state()`. `TelemetryClient.get_state` (`sim_client.py:348-350`) is `return self._state` — it never raises. So `sim_state` is never `None` in production; it is a default-constructed `SimState()` when disconnected, where `altitude_agl == 0` ⇒ `on_ground is True` ⇒ `_gear_up_on_ground` blocks `GEAR_UP`. Harmless today, but any authority logic branching on `sim_state is None` will be dead code, and any logic assuming `sim_state` is *fresh* is wrong when disconnected. Check `sim_state.connected` (`sim_client.py:143`), not `sim_state is None`.

### Pitfall 6: Lint divergence
`ruff check .` from inside `orchestrator/` flips isort first-party classification and disagrees with CI. Use the repo-root form from CLAUDE.md. New modules (`authority.py`) and new cross-package imports are exactly where this bites.

---

## Code Examples

### Existing gate insertion point — verbatim from `tools.py:239-271`

```python
command, sim_value = _resolve_command(system, action, value)

if command is None:
    return {"error": f"Unknown control: system={system}, action={action}"}

# --- Pre-execution safety check ---
checker = safety_check or _safety_check
safety_result = None
try:
    sim_state = await sim_client.get_state()
except ConnectionError:                       # never fires — see Pitfall 5
    sim_state = None

if sim_state is not None:
    aircraft_type = sim_state.aircraft or ""
    safety_result = checker.check(command, sim_value, sim_state, aircraft_type)

    if safety_result.severity == "blocked":
        logger.warning("Command %s BLOCKED: %s", command, safety_result.reason)
        return {"error": safety_result.reason, "command": command,
                "blocked": True, "severity": "blocked"}

# <<<<<< AUTHORITY GATE GOES HERE (D-03) >>>>>>
#   safety_result is available; sim_state is available; nothing sent yet.

state_before = sim_state
...
result = await sim_client.send_command(command, sim_value)   # :271
```

### Existing bypass to be closed — verbatim from `procedures.py:257-269`

```python
async def _execute_step(self, step: ProcedureStep) -> StepResult:
    """Execute a single procedure step via the telemetry service."""
    command, sim_value = _resolve_command(step.system, step.action, step.value)

    if command is None:
        return StepResult(step=step, success=False,
                          error=f"Unknown control: system={step.system}, action={step.action}")

    try:
        cmd_result = await self._sim_client.send_command(command, sim_value)
        #            ^^^ no safety check, no verifier, no history, no gate
```

Note `ProcedureExecutor.__init__` (`:210-211`) takes only `sim_client`. D-04 requires it to accept and forward the same collaborators `set_aircraft_control` takes.

### Health registration pattern to follow for D-17 — `main.py:84-88`

```python
self._health = HealthMonitor()
self._health.register("simconnect_bridge")
self._health.register("chromadb")
self._health.register("whisper")
self._health.register("claude_api")
# add: self._health.register("command_path")
```
Update with `self._health.update("command_path", healthy, message)`; `summary()` (`sim_client.py:234-243`) yields `{healthy, age_seconds, message}` per subsystem, ready for `/api/status`.

### ONNX-free test scaffolding to reuse for the probe endpoint — `test_turn_detection.py:31-50`

```python
class _FakeSession:
    def __init__(self, probability: float = 0.9, raises: Exception | None = None) -> None: ...
    def run(self, _outputs, feeds): return [np.array([[self.probability]], dtype=np.float32)]

def _detector_with(session, **kwargs) -> SmartTurnDetector:
    detector = SmartTurnDetector(**kwargs)
    detector._session = session
    detector._load_attempted = True
    return detector
```

---

## Package Legitimacy Audit

**No new external packages are required by this phase.** Every dependency the plan needs is already declared or already installed:

| Package | Registry | Status | Notes |
|---|---|---|---|
| `numpy` | PyPI | Existing dependency — `orchestrator/pyproject.toml:19` (`numpy>=1.26`) | Used by `features.py`, `audio_processing.py` |
| `onnxruntime` | PyPI | Existing optional dependency — `orchestrator/pyproject.toml:32` (`vad` extra, `onnxruntime>=1.16`) | Installed locally at 1.24.4. May need promoting from `vad` to a runtime extra for the web path — a **declaration** change, not a new package |
| `pydantic-settings` | PyPI | Existing dependency — `pyproject.toml:17` | New config fields only |
| ffmpeg | OS package | Present at `/usr/bin/ffmpeg`, 6.1.1-3ubuntu5 | Already required by the existing transcribe path |

**slopcheck not run** — no new package names are being introduced, so there is no hallucination surface. If planning later introduces a circuit-breaker or fake-clock library, run the Package Legitimacy Gate then. The recommendation in this document is explicitly to hand-write both (~30 lines and ~5 lines respectively) rather than add dependencies.

---

## Project Constraints (from CLAUDE.md)

| Directive | Where it binds this phase |
|---|---|
| Line length 100; ruff `E,F,I,N,UP,B,SIM` | All new modules |
| **Type hints required on all function signatures** | `authority.py`, `_check_override`, the probe endpoint |
| `async`/`await` throughout the orchestrator | Gate, floor, watchdog, override check |
| **Pydantic `BaseModel` for all data structures crossing boundaries** | The `/api/status` authority payload and the probe request/response. `AuthorityState` itself is internal — a plain class or dataclass is consistent with `CommandSafetyCheck`/`CommandHistory` |
| **`pydantic-settings` for config — never hardcode keys or magic numbers** | All 7 recommended fields; also the browser constants, which are currently hardcoded JS |
| **Run lint the way CI does** (repo root, `--config orchestrator/pyproject.toml`, the exact `--extend-ignore` list) | Every commit. Baseline verified clean today |
| C#: PascalCase public, `_camelCase` private, nullable enabled, XML doc comments on public APIs | `SimDataStructs.cs`, `SimConnectManager.cs` changes for B1/B2 |
| **Safety layers are independent of the LLM** (arch. decision 22) | D-08 restates it. The gate must never be advisory-by-prompt |
| **Semantic turn detection gated by acoustic VAD** (arch. decision 23) | D-20 is this principle with the gate in JS |
| Backend-selector properties need a branch for **every** value | Any `Settings` property or status field branching on `authority_level` |
| Test counts: ~1,066 across suites | The phase should raise, never lower, this number |

Two CLAUDE.md updates are owed by this phase: a new architectural-decision entry for the authority layer, and a correction to the directory listing for any new module (`authority.py`). CLAUDE.md line 341's test-category list should gain authority/override/watchdog.

---

## Concerns

> Per the phase brief: findings that make a locked decision unworkable **as written**.
> None of these ask to reverse a decision; each asks for a small amendment.

1. **D-02 / CMD-08 cannot be implemented as specified.** No telemetry exists to read (B1). Either add it across 4 layers of C# + Python, or change CMD-08 from "resolve against telemetry" to "refuse when state is unknown." **Needs a user call.**
2. **D-01 / CMD-07 delivers no capability without C# work.** The premise "already resolve to SimConnect events in shipped code" is true of the orchestrator and false of the adapter (B2). **Needs a user call** on whether C# is in scope.
3. **D-11's named reusable asset is not reusable.** `_extract_relevant_state` covers 8 of 67 commands and answers a different question (B4). The instruction "do not write a second mapping" cannot be honoured; a watched-fields map must be written. This is an amendment to the *means*, not the *intent*.
4. **D-11's named host is dead code.** `ProactiveMonitor` is never constructed (B5). Wiring it activates four other dormant subsystems in the browser. Recommend either accepting that as an explicit deliverable, or hosting `_check_override` on a direct `TelemetryClient.subscribe` callback. **Needs a user call.**
5. **D-13's guarantee does not hold for 60 of 67 commands.** Unverifiable commands "confirm" instantly (F2). Fix by adding ~7 verification checks (small, additive, strengthens SAFE-05) or by only watching genuinely-verified commands (free, narrower coverage).
6. **D-15's "the timeout already exists" is true but the gate can never see it.** The tool-layer `wait_for` pre-empts it (B3). The watchdog must live inside `TelemetryClient`, and `_TOOL_TIMEOUTS` must be raised.
7. **D-20's "POST the trailing 8s" is not producible by the browser.** MediaRecorder chunk framing (B7). Upload the whole accumulated blob; server-side `truncate_or_pad` already keeps the last 8 s, so the outcome is identical.
8. **AUTH-03's `assisted` is a near-no-op for 16 of 20 systems** because only 7 safety rules exist. Not a decision defect — REQUIREMENTS.md rules out new envelope rules — but it must be documented, not shipped silently.

---

## Assumptions Log

| # | Claim | Section | Risk if wrong |
|---|---|---|---|
| A1 | `GENERAL ENG ANTI ICE POSITION:1` and `GENERAL ENG FUEL PUMP SWITCH:1` are the correct MSFS simvars for carb heat and fuel pump state | B1 | The adapter registers a nonexistent simvar; SimConnect fails the data definition at connect. **Must be confirmed against the MSFS SDK simvar list before implementation.** Note the existing adapter uses `GEAR HANDLE POSITION`, `TRAILING EDGE FLAPS LEFT PERCENT` style names, so the family is right |
| A2 | ffmpeg subprocess spawn costs ~30–60 ms and ONNX inference ~10–20 ms, giving a ~50–100 ms probe round trip | VARC-06 | If spawn is much slower on Windows/WSL2, the probe adds latency instead of removing it. **The plan should include a measurement task**, and consider a persistent decoder process if it measures poorly |
| A3 | Opus at ~24 kbps ⇒ a 15 s utterance ≈ 45 KB upload | B7 | Underestimate would make repeated whole-blob uploads costly for long utterances. Mitigated by MERLIN utterances being short and the transport being localhost |
| A4 | `assisted` is the right default for `authority_level` | Config Fields | Changes existing behaviour on upgrade. A user expecting today's `full` behaviour would see commands silently withheld. **Confirm with the user** |
| A5 | Counting a send-exception as a watchdog timeout, and an adapter `success: False` as a counter reset, is the desired policy | Watchdog | Wrong polarity either latches spuriously (given B2's frequent `success: False` acks) or fails to latch on a real fault. Not specified by D-15/D-16 |
| A6 | Suggested defaults (grace 30 s, cooldown 120 s, N=3, reprobe 150 ms) | Config Fields | Explicitly Claude's discretion per CONTEXT.md; tune in planning |
| A7 | `claude-sonnet-4-20250514` still resolves | — | Deferred item in CONTEXT.md, not this phase, but every integration test that hits the API depends on it |

---

## Open Questions

1. **Is C# adapter work in scope for Phase 2?**
   - Known: CMD-07 and CMD-08 both require it (B1, B2). CMD-08 also requires telemetry-service schema changes.
   - Unclear: whether the phase owner intended a Python-only phase. CONTEXT.md's `<code_context>` names only Python files.
   - Recommendation: **surface before planning.** Three viable shapes — (a) full scope including C#; (b) AUTH-only, defer CMD-07/08 to a Phase 2.5; (c) AUTH + the 20 adapter events for already-exposed systems (closes a live defect cheaply), defer the 11 new ones.

2. **Where does `_check_override` live?**
   - Known: D-11 says `ProactiveMonitor`; `ProactiveMonitor` is never constructed (B5).
   - Recommendation: either accept "wire `ProactiveMonitor` into `web/server.py` and `main.py`" as an explicit phase deliverable (with its four dormant subsystems switching on), or host the detector on a direct telemetry subscriber. **User call.**

3. **What is the default `authority_level` on upgrade?**
   - `full` preserves behaviour; `assisted` is safer but changes it silently. A5 above.

4. **Does `assisted` withhold, or withhold-and-ask?**
   - AUTH-03 says "withholds …, deferring to the pilot." Whether MERLIN should offer "say 'override' and I'll do it" is unspecified. A confirm-to-proceed affordance implies conversational state that does not exist today.
   - Recommendation: withhold and report, no confirmation loop. Note it explicitly so it is not re-opened during execution.

5. **Should the 20 events for already-exposed broken systems (trim/deice/fuel_selector/crossfeed) be fixed here?**
   - It is a live defect on `main`, adjacent to the work, and mechanical. But it is not any Phase 2 requirement ID — exactly the untracked-scope pattern REQUIREMENTS.md exists to catch. Recommend a new ID (CMD-09) if taken.

---

## Sources

### Primary (HIGH confidence)
- Live codebase at `main` @ `7127a2b`, all line references verified by direct read:
  `orchestrator/orchestrator/{tools,sim_client,command_safety,command_verifier,command_history,procedures,proactive_monitor,claude_client,config,audio_processing}.py`;
  `orchestrator/orchestrator/turn/{base,__init__,smart_turn,features}.py`;
  `web/server.py`; `web/static/app.js`; `web/requirements.txt`; `web/pyproject.toml`;
  `telemetry-service/telemetry/schema.py`;
  `adapters/msfs/Models/{SimState,SimDataStructs}.cs`; `adapters/msfs/SimConnectManager.cs`;
  `tools/mock_adapter.py`; `orchestrator/tests/*`; `web/tests/conftest.py`; `orchestrator/pyproject.toml`
- Environment probes: `ffmpeg -version` → 6.1.1-3ubuntu5; `onnxruntime.__version__` → 1.24.4; `~/.cache/merlin/turn/smart-turn-v3.2-cpu.onnx` → 8,679,182 bytes
- CI lint parity run: both ruff commands from CLAUDE.md pass on the current tree
- `.planning/{REQUIREMENTS,STATE,TECH-STACK-REVIEW}.md`, `.planning/phases/02-authority-safety-layer/02-CONTEXT.md`, `./CLAUDE.md`

### Secondary (MEDIUM confidence)
- AWS IoT Device Shadow — desired/reported/delta, version-based stale rejection: https://docs.aws.amazon.com/iot/latest/developerguide/iot-device-shadows.html
- Kubebuilder Good Practices — `generation` / `observedGeneration`, level-triggered reconciliation: https://book.kubebuilder.io/reference/good-practices.html
- USPTO 8954235 — "System and method for enhanced steering override detection during automated lane centering" (torque-differential override detection)
- USPTO 7044024 — "Apparatus and method for servo control of an aircraft" (pitch servo torque sensing)
- AOPA, "Proficiency: The other autopilot failure" — override force and disengagement behaviour: https://www.aopa.org/news-and-media/all-news/2017/january/pilot/proficiency-autopilot

### Tertiary (LOW confidence — flagged, not relied upon)
- MSFS simvar names for carb heat / fuel pump state (A1) — from training data, **not** verified against the MSFS SDK
- ffmpeg spawn and ONNX inference latency figures (A2) — estimates, not measured on this machine

---

## Metadata

**Confidence breakdown:**
- Codebase findings (all 8 blocking findings, integration points, patterns): **HIGH** — every claim line-verified by direct read, no reliance on `.planning/codebase/ARCHITECTURE.md`
- Test strategy: **HIGH** — derived from reading the existing suites and their conventions
- Override-attribution prior art: **MEDIUM** — two authoritative sources (AWS, Kubebuilder) plus patents; the translation to a 1 Hz polled-telemetry sim is reasoning, not citation
- VARC-06 latency figures: **LOW** — estimated, measurement task recommended
- MSFS simvar names: **LOW** — training data only

**Research date:** 2026-07-31
**Valid until:** 2026-08-30 (codebase findings valid until `main` moves; re-verify line numbers if any listed file changes)
