# Phase 2: Authority & Safety Layer - Context

**Gathered:** 2026-07-31
**Status:** Ready for planning

<domain>
## Phase Boundary

This phase delivers the layer that decides **whether MERLIN may act at all**, as
distinct from whether a specific command is safe right now. The latter already
exists as `command_safety.py` (SAFE-01…08) and is not re-litigated here.

Scope: AUTH-01…08 — configurable authority levels (`advisory` / `assisted` /
`full`), pilot override detection with cooldown, an ack watchdog, and surfacing
the current level so it is never ambiguous.

Two additions to the original AUTH-only scope, both agreed during discussion:

1. **The adapter command-coverage fix** (see D-01, D-01a — *revised after
   research*). The original intent was to expose six unreachable systems. Research
   showed the C# adapter registers 40 of the 67 events `_resolve_command` emits,
   so exposing them would deliver nothing — and, more urgently, that **four
   systems already in the enum** (`trim`, `deice`, `fuel_selector`, `crossfeed`)
   have no adapter handler either. MERLIN reports those actions as taken today
   and they do nothing. Phase 2 fixes that live defect (CMD-07); exposing the six
   moves to a follow-up phase (CMD-09).
2. **Semantic turn detection on the web path** (VARC, see D-14…D-16). Orthogonal
   to authority — command control and voice endpointing share nothing — but
   deliberately bundled here by the project owner. Plan it as an independent
   workstream, not as a dependency of the AUTH work.

**Explicit non-goals (from REQUIREMENTS.md):** no new envelope rules. Those are
SAFE-* territory and already exist.

</domain>

<decisions>
## Implementation Decisions

### Scope: the unreachable control systems

- **D-01 — AMENDED after research.** *Originally: expose the six unreachable
  systems this phase.* Research found the C# adapter's `CommandMap` registers 40
  events while `_resolve_command` emits 67 — **all 11 events for those six
  systems are missing from the adapter**, so exposing them in the enum would
  deliver nothing but a command that acks and does nothing.
  **Now: the six are deferred to a follow-up phase (CMD-09).**
  What replaces it is more urgent — see D-01a.
- **D-01a — NEW.** The adapter is also missing ~20 events for **four systems that
  are already in the enum today**: `trim` (`ELEV_TRIM_UP/DN`, `RUDDER_*`,
  `AILERON_*`), `deice` (`PITOT_HEAT_TOGGLE`, `TOGGLE_STRUCTURAL_DEICE`, …),
  `fuel_selector` (`FUEL_SELECTOR_*`), and `crossfeed` (`CROSS_FEED_*`). Claude
  can emit these commands right now and the adapter has no handler — MERLIN
  reports an action it did not take. **This is a live defect on `main` and is
  Phase 2 scope (CMD-07, redefined).** Register the missing events so the
  adapter covers every event `_resolve_command` can emit for enum-exposed
  systems.
- **D-02 — AMENDED after research.** *Originally: resolve `carb_heat`/`fuel_pump`
  `"on"`/`"off"` against current telemetry.* There is no carb-heat or fuel-pump
  state anywhere in the chain — `SurfaceState` is exactly `gear_handle`,
  `flaps_percent`, `spoilers_percent`, in the C# struct, the adapter model, the
  service schema, and `sim_client.py`. There is nothing to read.
  **Now: refuse rather than toggle.** `"toggle"` still emits the toggle event;
  `"on"` and `"off"` return an explicit error stating MERLIN cannot confirm the
  current position. Removes the defect's teeth with no telemetry work, and never
  does the opposite of what was asked. (Adding the state through all four layers
  was considered and deferred — see Deferred Ideas.)

### Enforcement chokepoint

- **D-03:** Authority policy lives in `set_aircraft_control` (`tools.py:217`),
  where full `SimState` and the safety verdict are already available. This is
  required, not incidental: `assisted` is defined as "execute if safety is clean,
  withhold on `warning`", so the gate must sit where the safety verdict exists.
- **D-04:** `ProcedureExecutor._execute_step` (`procedures.py:259-269`) is
  re-routed through `set_aircraft_control` instead of calling `_resolve_command`
  + `send_command` directly. This closes a live gap — multi-step procedures
  currently reach SimConnect with **no safety check whatsoever**, because the
  check went into `tools.py` and never into `procedures.py`.
- **D-05:** A thin, level-only check in `TelemetryClient.send_command`
  (`sim_client.py:359`) refuses everything when authority is `advisory`. No
  safety re-run, no policy weight — a structural floor so a future caller that
  bypasses `set_aircraft_control` cannot reach the sim unnoticed. Chosen because
  the "remember to add the check" approach has already failed once in this exact
  code path.
- **D-06:** When authority withholds a step mid-procedure, **abort and hand back
  to the pilot** — do not continue. This deliberately overrides
  `ProcedureExecutor`'s documented continue-on-failure default. Rationale: a
  failed step means the sim didn't take it; a withheld step means MERLIN has
  decided it shouldn't be acting unsupervised, and continuing past that is
  precisely acting unsupervised. MERLIN reports which step and how many completed.

### Advisory semantics

- **D-07:** In `advisory`, the tool stays in the schema and returns a **dry-run
  result** — the gate resolves the command, runs the safety check, then returns
  `{advisory: true, would_execute: <event>, safety: <verdict>}` without
  transmitting. Rejected alternative: removing `set_aircraft_control` from
  `TOOL_DEFINITIONS` per level. Prompt caching is a prefix match rendered
  `tools` → `system` → `messages`, and a tool-definition change invalidates all
  three tiers — so a dynamic tool list would invalidate the cached MERLIN persona
  block (`claude_client.py:509`) on every request. The cache-preserving
  alternative (mid-conversation tool changes) requires Opus 5 or newer; this
  project runs Sonnet 4.
- **D-08:** Enforcement is in code, never in the prompt. Consistent with the
  recorded principle that safety layers do not depend on Claude behaving well.

### Authority state

- **D-08a — NEW.** The default `authority_level` is **`full`**, which preserves
  today's behavior exactly: execute unless `command_safety` blocks. Restriction is
  opt-in. Rationale: override detection is deliberately sensitive (D-12) and has
  never been exercised against real flight data, so shipping a default that
  silently withholds commands would produce confusing behavior nobody asked for.
  `advisory` and `assisted` are reachable via config and are exercised by the
  override and watchdog paths regardless of the default.
  **Document, don't hide:** `assisted` is close to a no-op for 16 of the 20
  systems, because only 7 safety rules exist and they cover gear, flaps,
  autopilot, and throttle only. Nothing warns on `mixture`, `fuel_selector`,
  `crossfeed`, or `deice`, so `assisted` withholds nothing there. That follows
  correctly from the "no new envelope rules" non-goal, but it must be stated in
  the config documentation rather than discovered in flight.
- **D-09:** Authority is **mutable runtime state**, not just a config read —
  AUTH-06 drops it to `advisory` on override. It lives in an injected
  `AuthorityState` object seeded from `settings.authority_level`, passed to
  `set_aircraft_control` alongside the `verifier` / `command_history` /
  `safety_check` params it already accepts, and handed to `TelemetryClient` for
  the floor. Rejected: a module-level singleton like `_safety_check`
  (`tools.py:20`) — that is the global-mutable-state shape v1.2 Phase 4 spent a
  plan removing from `web/server.py`, and which STATE.md still lists as an open
  concern.
- **D-10:** `AuthorityState` carries a **reason** alongside the level
  (`config` / `override` / `watchdog`) so AUTH-08 can distinguish "MERLIN is
  deferring to the pilot" from "MERLIN cannot reach the sim". Same level,
  materially different situations.

### Override detection

- **D-11 — AMENDED after research.** *Originally: a `_check_override()` inside
  `ProactiveMonitor.on_telemetry_update()`, reusing `_extract_relevant_state()`.*
  Two premises failed. `ProactiveMonitor` **is never instantiated** in `main.py`
  or `web/server.py`, so the check would be dead code; and
  `_extract_relevant_state()` is an *undo* snapshot, non-empty for only 8 of 67
  commands and `{}` for gear and every toggle — it cannot serve as the
  comparison basis.
  **Now: override detection hangs off the existing `TelemetryClient` update
  callback**, which both the CLI and web paths already subscribe to. It runs
  wherever telemetry runs, with no dependency on dormant code, and keeps this
  phase from silently commissioning callouts, deviation alerts, emergency
  detection, and checklist automation as a side effect.
  **A command→watched-fields mapping must be written** — the "do not write a
  second mapping" instruction cannot be honoured, because the first mapping does
  not cover the cases override detection needs. Deriving one from
  `command_verifier.py`'s expected-state checks is the closest existing analog.
  **Clock mismatch to resolve:** `CommandRecord.timestamp` is `time.monotonic()`,
  while `SimState.timestamp` is an ISO string from the adapter. Correlating them
  needs one clock, chosen deliberately.
- **D-12:** An override is **any unattributed change on a watched field** — the
  field moved and no recent `CommandRecord` accounts for it. Direction-agnostic:
  flaps 2 → flaps 3 counts as much as flaps 2 → flaps up, because both mean the
  pilot is working that system. Deliberately biased toward sensitivity: a false
  positive costs one advisory window, a false negative leaves MERLIN commanding
  an aircraft the pilot is already flying.
  **Implementation risk to plan around:** telemetry reports state, not
  provenance. "The pilot did it" can only mean "no matching recent
  `CommandRecord`", and MERLIN's own commands take up to 3s to appear in
  telemetry. Get the correlation wrong and MERLIN detects itself as the pilot.
- **D-13 — AMENDED after research.** *Originally: the watch opens when
  `CommandVerifier` confirms the aircraft reached the commanded state, which
  sidesteps the attribution race by construction.* The mechanism is sound but has
  a hole: **60 of 67 commands have no verification rule**, so `verify_command`
  returns `verified=True` in roughly zero milliseconds. For those, the watch
  opens before the sim has moved — reintroducing exactly the race D-13 was chosen
  to avoid.
  **Now: keep verifier-confirmation as the trigger where a real rule exists, and
  for unverifiable commands open the watch after a fixed settle delay instead.**
  The delay must exceed the observed telemetry propagation lag. Do not treat a
  `verified=True` that no rule produced as evidence the aircraft moved.
- **D-14:** Cooldown is a **rolling timer**: drop to `advisory` for a
  configurable period, each new override pushes the expiry out, auto-restore when
  it lapses. Sustained pilot activity keeps MERLIN advisory; a single false
  positive costs one window rather than the rest of the flight — which matters
  given the deliberately sensitive rule in D-12. MERLIN announces both the drop
  and the restore.

### Watchdog

- **D-15:** A per-command ack timeout **already exists** —
  `send_command` wraps the ack future in `asyncio.wait_for(timeout=5.0)` and
  returns `{"success": False, "error": "Command timed out"}`. AUTH-07's new part
  is the **latch**, not the timeout.
- **D-16 — AMENDED after research.** The circuit-breaker shape is unchanged:
  latch after **N consecutive ack timeouts** (3 by default), counter reset on any
  successful ack. What changed is *where it reads the signal from*.
  `_TOOL_TIMEOUTS["set_aircraft_control"]` is **5.0s** — identical to
  `send_command`'s internal `asyncio.wait_for` timeout — and the outer wrapper
  starts first, so the `{"success": False, "error": "Command timed out"}` dict
  the counter was going to watch is never reliably produced.
  **Now: the watchdog counter lives inside `TelemetryClient.send_command`**, at
  the point the ack future actually times out. Do not derive it from the tool's
  return value. (Raising the outer tool timeout above 5.0s would also work and is
  worth doing regardless, but the counter should not depend on that ordering.)
- **D-17:** A latched watchdog sets level `advisory` with reason `watchdog`
  (per D-10), and registers command-path health via the existing `HealthMonitor`
  (`sim_client.py:206`) so `/api/status` can render "advisory (command path
  down)". Rejected: a fourth authority state, which would thread through the
  gate, the floor, the status endpoint, the UI, and the tests for no behavioral
  gain.
- **D-18:** The latch clears on **telemetry reconnect / heartbeat recovery**.
  A latch that stops command issuance would otherwise deadlock — no commands
  means no successful ack to clear it. `TelemetryClient` already runs a heartbeat
  loop and reconnects with exponential backoff, and the same WebSocket carries
  both telemetry and commands, so telemetry flowing again is direct evidence the
  command path is back. No probe traffic, no pilot action required.

### Web-path semantic turn detection (VARC)

- **D-19:** The web path does **not** use Deepgram endpointing —
  `deepgram_client.transcribe()` is batch, and the turn decision happens in the
  browser via RMS energy with `VAD_SILENCE_MS = 1200` (`app.js:1433-1435`). That
  is 3× the local fixed fallback (`vad_silence_ms: 400`) and 8× the semantic
  probe point (`turn_probe_silence_ms: 150`).
- **D-20 — AMENDED after research.** Architecture is unchanged: **browser probes,
  server decides.** Two implementation corrections.
  *(a)* The browser **cannot** send "the trailing 8s" — MediaRecorder webm chunks
  are not independently decodable, so a slice of the buffer will not decode. Send
  the **whole blob**; `truncate_or_pad` already keeps the last 8s server-side.
  *(b)* Do **not** reuse `convert_webm_to_wav_normalized` from the transcribe
  path. Its silence trimming destroys precisely the signal the turn model judges.
  A separate decode path is required.
  Lower the browser's silence threshold toward `turn_probe_silence_ms`, POST to a
  new endpoint that runs the existing `SmartTurnDetector`, return continue/stop.
  This is the recorded
  architectural principle verbatim — a cheap acoustic gate finds candidates and
  decides *when* to ask; the `TurnDetector` decides *whether* the turn is over —
  with the gate in JS instead of Silero. Upload is bounded by the model's 8s
  window (`[batch, 80, 800]`), and probes only fire during silence.
  Rejected: running the model in-browser via ONNX Runtime Web. It would require
  reimplementing `features.py` in JavaScript and keeping it numerically identical
  to the numpy version, and that file's own docstring warns a divergence "would
  not raise — it would just make turn predictions quietly wrong."
  Noted for later: continuous audio streaming to the server is the eventual
  target and is what VARC-02 (Parakeet local streaming STT) will need, but it
  reworks the web audio path including barge-in, which is too much to carry here.
- **D-21:** When the probe endpoint is unavailable or the model isn't loaded, the
  browser falls back to fixed-silence endpointing at **400ms**, matching
  `vad_silence_ms`. Graceful degradation consistent with the rest of the system,
  and even the degraded web path ends up 3× more responsive than today.

### Claude's Discretion

- Exact default values for the new config fields (grace window, cooldown period,
  consecutive-timeout count) — starting points are suggested above; tune during
  planning. All must be `pydantic-settings` fields, never hardcoded.
- Naming of the new config fields, the `AuthorityState` API surface, and the
  turn-probe endpoint route.
- Whether the web-path turn work gets its own requirement ID (e.g. VARC-01b) or
  extends VARC-01. VARC-01 is already marked complete for the local path.

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Requirements and prior decisions
- `.planning/REQUIREMENTS.md` — AUTH-01…08 verbatim, plus the recorded non-goals
  and the VARC series. The authoritative scope statement for this phase.
- `.planning/v1.3-RECONCILIATION.md` — why Phase 2 was rescoped and which of its
  original deliverables already shipped as SAFE-*.
- `.planning/TECH-STACK-REVIEW.md` §2–3 — why the cascade architecture is
  retained; constrains any voice-path change.
- `.planning/STATE.md` § "Phase 2 scope inputs" — the three findings that
  produced D-01, D-02, and the gating sequence.

### Feature documentation
- `docs/SMART_CONTROLS.md` — command safety severity model and rule reference;
  the `blocked` / `warning` two-tier model that `assisted` keys off.
- `docs/SAFETY.md` — emergency fast paths and numerical validation.
- `docs/AIRCRAFT_CONTROLS.md` — supported control systems and SimConnect mapping;
  cross-check before touching the enum (D-01).
- `docs/PROACTIVE_COPILOT.md` — the monitor loop that override detection extends.
- `docs/VOICE_PIPELINE.md` — STT/TTS backends, VAD, barge-in; the web-path
  context for D-19…D-21.

### Code that constrains the design
- `orchestrator/orchestrator/tools.py` — `set_aircraft_control` (line 217),
  `_resolve_command` (line 35), `CRITICAL_COMMANDS` (line 27), the
  `_safety_check` singleton (line 20), and the `carb_heat`/`fuel_pump` defect
  (lines 184-190).
- `orchestrator/orchestrator/command_safety.py` — `SafetyRule`, `DEFAULT_RULES`
  (7 rules, gear/flaps/AP/throttle only), and the `check()` signature the gate
  depends on.
- `orchestrator/orchestrator/procedures.py` — `ProcedureExecutor.execute` and its
  continue-on-failure rationale (lines 211-218), which D-06 overrides.
- `orchestrator/orchestrator/command_history.py` — `CommandRecord`,
  `get_recent`, and `_extract_relevant_state` (line 209), the comparison basis
  for override detection.
- `orchestrator/orchestrator/command_verifier.py` — `CommandVerifier`
  (timeout 3.0s, poll 0.5s) and its per-command expected-state checks; D-13 keys
  the watch window off its confirmation.
- `orchestrator/orchestrator/proactive_monitor.py` — `on_telemetry_update`
  (line 145), where `_check_override()` lands.
- `orchestrator/orchestrator/sim_client.py` — `send_command` (line 359),
  `HealthMonitor` (line 206), the heartbeat loop, and reconnect-with-backoff.
- `orchestrator/orchestrator/claude_client.py` — `TOOL_DEFINITIONS` (line 242),
  the enum to extend, and the `cache_control` breakpoint (line 509) that D-07
  protects.
- `orchestrator/orchestrator/turn/base.py` + `smart_turn.py` + `features.py` —
  the `TurnDetector` protocol, the ONNX detector, and the golden-value-pinned
  feature extractor. **Read the `features.py` docstring before proposing any
  reimplementation.**
- `web/server.py` — `/api/status` (line 343) for AUTH-08, and the Deepgram batch
  transcribe path.
- `web/static/app.js` — browser VAD constants (lines 1433-1435), the thing D-20
  changes.

### Caveat
- `.planning/codebase/ARCHITECTURE.md` is dated 2026-03-26 and **predates all of
  v1.3** — it documents 5 Claude tools and no command protocol. Do not treat it
  as current. Scout live code instead, or regenerate it first.

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `CommandHistory._extract_relevant_state()` — already maps a command to the
  telemetry fields it affects. Override detection needs exactly this; do not
  write a second mapping.
- `CommandVerifier` — already polls telemetry post-command with per-command
  expectations. D-13 uses its confirmation as the watch-window trigger.
- `ProactiveMonitor.on_telemetry_update()` — an existing per-update loop with
  prev/curr comparison. Override detection is a fourth check alongside three.
- `HealthMonitor` — `register` / `update` / `all_healthy` per named subsystem.
  Command-path health for D-17 and AUTH-08 fits without new infrastructure.
- `SmartTurnDetector` + the `turn/` package — used as-is by D-20; the web work is
  an endpoint plus browser probe logic, not new model code.
- `send_command`'s `asyncio.wait_for(timeout=5.0)` — the timeout half of AUTH-07
  already exists.

### Established Patterns
- **Injected collaborators over module singletons.** `set_aircraft_control`
  already takes `verifier`, `command_history`, and `safety_check` as parameters;
  `AuthorityState` follows the same shape (D-09).
- **Data-driven rules.** `command_safety.py` uses `SafetyRule` records that
  extend without touching the evaluator. Authority rules should not regress this.
- **Graceful degradation.** Whisper down → text only; ChromaDB down → empty RAG;
  Smart Turn unavailable → fixed silence. D-21 follows the same pattern.
- **Config through `pydantic-settings`.** Every threshold above is a settings
  field, never a literal.

### Integration Points
- `tools.py:271` — the `send_command` call inside `set_aircraft_control`; where
  the gate wraps.
- `procedures.py:269` — the second SimConnect path; re-routed by D-04.
- `sim_client.py:359` — `send_command`; where the advisory floor lands (D-05).
- `proactive_monitor.py:145` — `on_telemetry_update`; where `_check_override`
  lands (D-11).
- `web/server.py:343` — `/api/status`; where authority level and reason surface
  (AUTH-08, D-10).
- `web/static/app.js:1433` — browser VAD constants; where D-20/D-21 land.

</code_context>

<specifics>
## Specific Ideas

- The pilot must always be able to tell **why** MERLIN is advisory. Three reasons
  produce the same level and call for different responses: configured,
  pilot override, command path down. D-10 and D-17 exist for this.
- Sensitivity over precision on override detection, explicitly: MERLIN commanding
  an aircraft the pilot has taken over is the failure that matters. The rolling
  cooldown (D-14) is what makes that bias affordable.
- "Gate first, then expose" for the enum work is a sequencing requirement, not a
  preference — the six systems include in-flight engine shutdown.

</specifics>

<deferred>
## Deferred Ideas

- **CMD-09 — expose the six unreachable systems.** `magnetos`, `carb_heat`,
  `fuel_pump`, `starter`, `primer`, `lights`. Requires ~11 new adapter events
  plus the enum change. Deferred from Phase 2 after research showed the adapter
  cannot execute them. **Sequencing note that must survive to that phase:**
  `execute_procedure` bypasses the `set_aircraft_control` enum entirely, so
  `PROCEDURES["shutdown"]` becomes a working in-flight engine shutdown the moment
  those adapter events land. Do not register them before the authority gate and
  the procedure re-route (D-04) are in place.
- **Carb-heat / fuel-pump telemetry state.** Adding it through the C# struct,
  adapter model, service schema, `SurfaceState`, and mock adapter would make
  CMD-08 implementable as originally written and would enable a "carb heat left
  on" deviation rule. Deferred in favor of refuse-rather-than-toggle (D-02).
- **Commissioning `ProactiveMonitor`.** It is never instantiated, so callouts,
  deviation alerts, emergency detection, and checklist automation — roughly 2,300
  lines with documentation in `docs/PROACTIVE_COPILOT.md` — are all dormant.
  Turning them on is a deliberate decision with real behavioral blast radius, and
  deserves its own phase rather than riding along with authority work.
- **Continuous browser→server audio streaming.** The eventual target for the web
  voice path and a prerequisite for VARC-02 (Parakeet local streaming STT).
  Reworks the web audio path including barge-in and per-client cancellation —
  too large to carry alongside AUTH. D-20 is the incremental step.
- **`claude_model` is on a retired-or-retiring model.** `config.py:27` defaults
  to `claude-sonnet-4-20250514`, deprecated with a published retirement of
  2026-06-15 — now past. Verify whether it still resolves; if not, MERLIN's
  default model 404s. Its own work item, not Phase 2.
- **`claude_temperature` blocks any model upgrade.** `config.py:42` sets
  `temperature: 0.3`; sampling parameters are rejected outright on Claude
  Sonnet 5 and Opus 4.7+, so a model bump 400s until `temperature` / `top_p` /
  `top_k` are removed. Pairs with the item above.
- **Delete `docs/phase2-controls` and `feat/fuel-controls`.** Both are strictly
  behind `main`; their `_resolve_command` content is already there, and they
  predate the `command_safety` / `command_verifier` / `command_history` wiring,
  so merging either would regress the safety layer. Housekeeping.
- **Regenerate `.planning/codebase/*.md`.** Dated 2026-03-26, predates all of
  v1.3. Run `/gsd:map-codebase` before any future phase relies on those maps.
- **11 `worktree-agent-*` branches** — ~30 commits of leftover agent worktrees,
  still listed as an open decision in STATE.md. Triage or delete.

</deferred>

---

*Phase: 02-authority-safety-layer*
*Context gathered: 2026-07-31*
