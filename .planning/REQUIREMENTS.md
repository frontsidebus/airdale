# Requirements: MERLIN v1.3 — Agent Copilot Control

**Defined:** 2026-07-29
**Status:** in progress

> **Why this file exists.** v1.2 had 36 requirement IDs that every plan declared
> and every verifier traced. v1.3 had none — so roughly 3,900 lines of working,
> documented code landed on `main` without appearing in any plan or roadmap, and
> nothing could detect it. See `.planning/v1.3-RECONCILIATION.md` §4.
>
> Requirements marked **[x] (retroactive)** were already built and are recorded
> here to make the roadmap describe reality. Retroactive IDs are not a claim that
> the work was planned — they are a claim about what exists, with evidence.

---

## Phase 1 — Discrete Command Control ✅ COMPLETE

Bidirectional command path from natural language to SimConnect.

- [x] **CMD-01** (retroactive): Command protocol routes consumer → service → adapter with acknowledgment tracking (`ConsumerCommand` → `ServiceCommand` → `AdapterCommandAck` → `ServiceCommandAck`)
- [x] **CMD-02** (retroactive): MSFS adapter registers 30+ SimConnect events and executes them via `TransmitClientEvent`
- [x] **CMD-03** (retroactive): Telemetry service forwards commands bidirectionally with ack correlation
- [x] **CMD-04** (retroactive): Orchestrator exposes `set_aircraft_control` as a Claude tool with Future-based ack waiting
- [x] **CMD-05** (retroactive): `_resolve_command()` translates human-friendly system/action/value parameters to SimConnect events
- [x] **CMD-06** (retroactive): Supported systems include flaps, gear, autopilot, throttle, radio, barometer, trim, parking brake, spoilers, mixture, propeller

> **Extended in Phase 2.** `CMD-07` and `CMD-08` continue this series — see the
> Phase 2 section. `_resolve_command` grew past what CMD-06 records (it now also
> handles `deice`, `fuel_selector`, `crossfeed`, and six systems the tool schema
> never exposed), and CMD-08 fixes a resolution defect in two of them.

## Command Safety & Integrity ✅ COMPLETE (undocumented until now)

Built during v1.3 Phase 1 but never specified. These partially satisfy what the
original Phase 2 scope promised — see `v1.3-RECONCILIATION.md` §1.

- [x] **SAFE-01** (retroactive): Pre-execution safety validation rejects dangerous commands against live telemetry — `command_safety.py`, wired at `tools.py:20`
- [x] **SAFE-02** (retroactive): Two-tier severity model — `blocked` prevents execution and short-circuits; `warning` proceeds with an advisory and accumulates
- [x] **SAFE-03** (retroactive): Safety rules are phase-aware, reading `FlightPhase` from `SimState` (gear up on ground, flaps above Vfe, throttle idle on approach, AP disconnect low)
- [x] **SAFE-04** (retroactive): Rules are data-driven `SafetyRule` records, extensible without touching the evaluator
- [x] **SAFE-05** (retroactive): Post-execution verification polls telemetry to confirm the aircraft actually changed state — `command_verifier.py`
- [x] **SAFE-06** (retroactive): Recent commands are tracked with generated undo actions — `command_history.py`
- [x] **SAFE-07** (retroactive): Multi-step compound commands execute as defined procedures — `procedures.py`
- [x] **SAFE-08**: Test coverage for `command_safety.py` — 24 tests (salvaged from `test/phase3-coverage`; the module had zero coverage while gating the aircraft write path)

## Proactive Co-Pilot ✅ COMPLETE (undocumented until now)

Telemetry-driven output that does not wait to be asked. Not in the v1.3 roadmap
for any phase; documented in `docs/PROACTIVE_COPILOT.md`.

- [x] **PROA-01** (retroactive): Callout engine fires aviation callouts (V1, rotate, altitude alerts, minimums) at telemetry-determined moments — `callouts.py`
- [x] **PROA-02** (retroactive): Deviation monitor checks phase-aware rules against each `SimState` update and raises alerts — `deviation_monitor.py`
- [x] **PROA-03** (retroactive): Unified `proactive_monitor.py` subscribes to telemetry and evaluates callouts, deviations, and emergency detection in one pass
- [x] **PROA-04** (retroactive): Interactive checklist sessions driven by flight-phase transitions — `checklist_manager.py`
- [x] **PROA-05** (retroactive): Emergency detection delivers pre-validated responses that bypass LLM inference for time-critical conditions — `emergency.py`
- [x] **PROA-06** (retroactive): Emergency types cover engine failure (takeoff/cruise), engine fire, electrical fire, and rapid decompression, with debounce before confirmation

## Numerical Safety ✅ COMPLETE (undocumented until now)

- [x] **VALD-01** (retroactive): Claude responses are scanned for aviation-critical numbers — V-speeds, altitudes, frequencies — and cross-referenced against structured limits — `validation.py`
- [x] **VALD-02** (retroactive): Per-aircraft `AircraftLimits` records supply the reference envelope for validation
- [x] **VALD-03** (retroactive): Validation operates on response **text**, which is why the cascade architecture is retained — see `TECH-STACK-REVIEW.md` §3.1

## Voice Pipeline ✅ COMPLETE

Backend abstraction restored and extended (PR #75).

- [x] **VOIC-01** (retroactive): STT backend selectable via config — Deepgram (cloud streaming) or Whisper (local batch)
- [x] **VOIC-02** (retroactive): TTS backend selectable via config — Cartesia, ElevenLabs, or local Kokoro
- [x] **VOIC-03**: `VoiceOutput` delegates to the `TTSClient` protocol; no provider URLs, credentials, or voice settings in `voice.py` (restores v1.2 TTS-02, silently reverted by `a1b508a`)
- [x] **VOIC-04**: Audio playback routes on `audio_content_type` rather than assuming MP3, so WAV/PCM backends do not spawn ffmpeg
- [x] **VOIC-05**: `create_tts_client()` handles every supported backend; `SUPPORTED_BACKENDS` keeps factory, config, and error message in sync
- [x] **VOIC-06**: `tts_configured`, `voice_id`, and `stt_configured` judge the selected backend against its own credentials only
- [x] **VOIC-07**: `create_stt_client()` factory with a `WhisperSTTAdapter`, making Whisper and Deepgram peers behind one protocol
- [x] **VOIC-08**: Both STT backends bias on one shared aviation vocabulary — Whisper via `initial_prompt`, Deepgram via `keywords`
- [x] **VOIC-09**: `voice.py` has structural regression guards asserting no credentials, provider URLs, or hardcoded voice settings

## Evaluation ✅ COMPLETE

- [x] **EVAL-01**: Aviation-weighted ASR scoring reports WER, critical token error rate, and value recall — `orchestrator/eval/aviation_wer.py`
- [x] **EVAL-02**: Normalization folds spoken digits into runs so `two seven zero` and `270` compare equal, including ICAO variants (`niner`, `tree`, `fife`)
- [x] **EVAL-03**: Reference corpus of aviation phraseology across altitude, squawk, frequency, callsign, V-speed, emergency, and conversational categories — `data/eval/aviation_stt_corpus.yaml`
- [x] **EVAL-04**: `tools/stt_bench.py` scores a backend against the corpus with per-category attribution and pass/fail gates
- [x] **EVAL-05**: Synthetic corpus generation via TTS with cockpit/VHF channel simulation and SNR sweep — `tools/gen_stt_corpus.py`, `eval/audio_augment.py`. Explicitly scoped to CI regression and degradation curves, not threshold setting.
- [x] **EVAL-06**: External corpus ingest so public ATC datasets (ATCOSIM, ATCO2, UWB-ATCC) can be scored — `stt_bench.py --paired-dir/--manifest`, `eval/corpus.py`. Deliberately no auto-download; licence terms vary and are the user's to accept.
- [ ] **EVAL-07**: Thresholds calibrated against real speech — a public ATC corpus for backend selection, plus a small set of own-voice/own-headset recordings for final calibration

## RAG Enhancements ✅ COMPLETE (undocumented until now)

- [x] **RAG-01** (retroactive): Cross-encoder re-ranking gives two-stage retrieval — top-K from the vector store, then top-N by re-rank — `reranker.py`
- [x] **RAG-02** (retroactive): Structure-aware semantic chunking preserves checklist items, procedure steps, and limitation entries — `chunking.py`
- [x] **RAG-03** (retroactive): Aviation data tools cover NOTAM, METAR/TAF, ADS-B, charts, performance, and airspace — `aviation_tools.py`

---

## Phase 2 — Authority & Safety Layer 🚧 RESCOPED

Original scope listed four items; two were already delivered as SAFE-01…04.
What remains is the part that decides **whether MERLIN may act at all**, as
distinct from whether a specific command is safe right now.

- [x] **AUTH-01**: `authority_level` config field with values `advisory` | `assisted` | `full`, enforced at the single point where `set_aircraft_control` reaches SimConnect (plans 02-01, 02-04, 02-05, 02-08 — `authority.py`'s `AuthorityState`, the policy gate in `tools.py::set_aircraft_control`, and the level-only floor in `TelemetryClient.send_command` that re-reads the level at dispatch; `orchestrator/tests/test_authority.py`)
- [x] **AUTH-02**: `advisory` describes the intended action and sends nothing to the sim (plan 02-04 for the direct path; **unblocked by plans 02-11 and 02-12**, which closed the false-confirmation paths that made "sends nothing" indistinguishable from "sent it". 02-11 added `tools.py::_was_transmitted`, gated `safety_note` on it, and made `undo_last_command` pop the history record only after a confirmed transmission; 02-12 gave `web/server.py::_on_tool_result` the identical expression so a refused command no longer renders as a green success in the browser)
- [x] **AUTH-03**: `assisted` executes commands that pass safety cleanly but withholds any that raise a `warning` severity, deferring to the pilot (plan 02-04 for the branch; plan 02-11 closed the fail-open where an absent verdict — `sim_state is None` — took the same path as a clean one, adding the `no_verdict` withhold; plan 02-14's crossfeed `warning` rule is what makes `assisted` behave differently from `full` on the newly-reachable fuel surface. **Residual, not scored:** WR-10 part 2 — a verdict computed from *stale* telemetry is still treated as live — is deferred; the requirement as written concerns severity, not freshness)
- [x] **AUTH-04**: `full` preserves current behavior — execute unless `blocked` (plan 02-04 left the branch unchanged; **plan 02-14 is what makes it non-vacuous** — verification found "execute unless blocked" literally true but hollow for the commands CMD-07 had just made reachable with no rule that could ever return `blocked`. `DEFAULT_RULES` 7 → 13 restored the posture)
- [x] **AUTH-05**: Pilot override detection identifies manual control input contradicting a MERLIN-issued command (plan 02-06 — `override_detector.py`'s `COMMAND_WATCHED_FIELDS` attributed against `TelemetryClient.recent_dispatches()` on one monotonic clock; `orchestrator/tests/test_override_detector.py`. **Residual, not scored:** WR-05 — an orchestrator↔service reconnect can register as a false override on resume)
- [x] **AUTH-06**: A detected override drops authority to `advisory` for a cooldown period and informs the pilot (plan 02-06 delivered the drop; the "informs" half was dead code until **plans 02-13 and 02-15**. 02-13 bounded `OverrideDetector.events` at `MAX_PENDING_ANNOUNCEMENTS`, made publishing incapable of raising, and added `orchestrator.main.drain_authority_events`, which prints and speaks each announcement on the CLI; 02-15 added `web.server._authority_event_pump`, fanning an `authority_event` frame out to every open chat socket. `orchestrator/tests/test_main_authority.py` + `web/tests/test_authority_events.py`)
- [x] **AUTH-07**: Watchdog bounds the interval between command dispatch and `AdapterCommandAck`; on expiry MERLIN stops issuing commands and says so (plans 02-05 and 02-08 for the "stops" half — the counter increments inside `send_command` on a real `TimeoutError`, latches after N consecutive timeouts, and the floor then refuses every subsequent command; **plan 02-13 closed the CLI "says so" gap (WR-07)** — `/status` now ends with the authority lines and a dedicated `/authority` command prints level, reason, cooldown, latch state and timeout count)
- [x] **AUTH-08**: Authority level is surfaced in `/api/status` and the web UI so the current mode is never ambiguous, including *why* it is advisory (configured / pilot override / watchdog) (plans 02-09 and 02-10 — `authority_level` / `authority_reason` / the full `summary()` dict in `/api/status`, with `renderAuthority` and `AUTHORITY_REASON_TEXT` covering all four reasons plus an unreachable-server state; plan 02-15 additionally moves the badge at announcement time rather than waiting up to 10 s for the next poll. **Note:** the live-browser legibility and perceived-timing checks in `02-VERIFICATION.md`'s `human_verification:` were **approved** by the developer as a blanket `approved`, not narrated as observations — see `02-15-SUMMARY.md`)

Command surface (CMD series — extends Phase 1, delivered here because gating must exist first):

- [x] **CMD-07** *(redefined 2026-07-31 after research)*: The MSFS adapter's `CommandMap` registers a handler for **every** SimConnect event `_resolve_command` can emit for systems the enum already exposes. Today it registers 40 of 67; `trim`, `deice`, `fuel_selector`, and `crossfeed` are in the enum with no adapter handler, so MERLIN reports actions it did not take. This is a live defect on `main`, not new capability. (plan 02-02 registered the handlers, pinned by `orchestrator/tests/test_command_coverage.py::test_every_enum_exposed_event_has_an_adapter_handler` and the C#-side `CommandMapTests.cs`. **Cited with plan 02-14 deliberately**: CMD-07 read as complete while shipping a live hazard — it turned `FUEL_SELECTOR_OFF` and `CROSS_FEED_*` from NACKs into real `TransmitClientEvent` calls with no safety rule behind them, at a default `AUTHORITY_LEVEL` of `full`. 02-14 added the six rules that close it. The ledger keeps both halves so "satisfied" is not read as "was safe on arrival")
- [x] **CMD-08** *(reshaped 2026-07-31 after research)*: `carb_heat` and `fuel_pump` refuse `"on"` / `"off"` with an explicit "cannot confirm current position" error rather than emitting a blind toggle. `"toggle"` continues to work. Original intent was telemetry-aware resolution; no carb-heat or fuel-pump state exists anywhere in the telemetry chain, so there is nothing to resolve against. (plan 02-04 delivered `UNCONFIRMABLE_POSITION_SYSTEMS` and the refusal; **plan 02-14 extended it to `parking_brake`** — the only one of the three that was actually reachable — added `UNCONFIRMABLE_REFUSED_ACTIONS` so verbs like `release` and `apply` are refused rather than falling through, and moved the refusal above the unknown-control return so a refused verb gets the explanation instead of a typo message)
- [ ] **CMD-09** *(deferred — NOT Phase 2)*: The six systems `_resolve_command` handles but the enum omits — `magnetos`, `carb_heat`, `fuel_pump`, `starter`, `primer`, `lights` — are exposed, with the ~11 adapter events they need. Deferred because the adapter cannot execute them today. **Sequencing constraint:** `execute_procedure` bypasses the enum, so `PROCEDURES["shutdown"]` becomes a working in-flight engine shutdown the moment those events are registered — do not land them before the authority gate and the procedure re-route.

Voice architecture (VARC series — see the Voice Architecture section):

- [x] **VARC-06**: Semantic turn detection reaches the web path. The browser gates on a short RMS silence probe and a server endpoint runs the existing `SmartTurnDetector`; degrades to fixed-silence endpointing at `vad_silence_ms` when the model is unavailable.

**Explicit non-goals for Phase 2:** no new envelope rules. Those are SAFE-*
territory and already exist.

> **Qualified 2026-08-02 — plan 02-14 added six rules, and this does not breach the
> non-goal.** The rules are `FUEL_SELECTOR_OFF` airborne (blocked), `FUEL_SELECTOR_SET`
> at index 0 airborne (blocked), `MIXTURE_SET` at idle cut-off airborne (blocked), the
> three `CROSS_FEED_OPEN`/`OFF`/`TOGGLE` events airborne (warning), `PARKING_BRAKES`
> on the ground above 5 kt (blocked), and `PARKING_BRAKES` airborne (warning).
> `DEFAULT_RULES` went 7 → 13.
>
> They add **no coverage beyond the surface this phase itself made reachable**.
> **CMD-07** — Phase 2's own work, in plan 02-02 — registered eight previously-NACKing
> events in the MSFS adapter's `CommandMap`, turning a refusal into a real
> `TransmitClientEvent` for systems that were already in the `set_aircraft_control`
> enum. Before that change those commands could not move the aircraft; after it they
> could, with nothing in front of them. The six rules restore the safety posture that
> Phase 2's own change removed — they do not extend the envelope to anything that was
> already reachable and unruled.
>
> The precedent is `MAGNETO_SET`, held back from the identical treatment under CMD-09
> on the stated grounds that registering it "turns a named tool call into a working
> in-flight engine shutdown with nothing in front of it". Fuel selector OFF in flight
> is that same shutdown by another route, and it had *less* in front of it than
> magnetos would have had. The reachable set and the deferred set have to follow one
> severity rationale; before 02-14 they followed two.
>
> **A phase that widens the write surface owns the rules for what it widened.** That is
> the boundary this qualification draws, and it is narrower than a general licence to
> add envelope rules. A broader `SAFE-*` envelope pass for the systems that remain
> unruled is still outstanding — `deice` is the one reachable enum system with real
> consequences and no rule of either severity, so `assisted` still behaves identically
> to `full` for it. Do not "resolve" this paragraph by deleting the six rules; that
> reopens an unguarded in-flight fuel-starvation path.

> The original non-goal "no new command types" was **narrowed** on 2026-07-31.
> CMD-07 adds no new capability — those six systems already resolve to SimConnect
> events in shipped code; it makes reachable what is already there. Genuinely new
> command types remain out of scope.

## Phase 3 — Automated Maneuvers ⬜ NOT STARTED

- [ ] **MNVR-01**: PID control loops for takeoff, landing, and go-around
- [ ] **MNVR-02**: Server-side control loop running at 20Hz
- [ ] **MNVR-03**: Long-running maneuvers modeled as cancellable tasks, building on `procedures.py` rather than duplicating its sequencing
- [ ] **MNVR-04**: Maneuvers respect the Phase 2 authority level and abort on pilot override

## Phase 4 — Vision Cockpit Reading ⬜ NOT STARTED

- [ ] **VIS-01**: Screen capture upgraded from `mss` to a lower-latency backend
- [ ] **VIS-02**: Claude vision reads instrument values from captured frames
- [ ] **VIS-03**: Third-party aircraft gauges interpreted where SimConnect exposes no variable
- [ ] **VIS-04**: Vision-derived values are validated through `validation.py` before use, never trusted raw

---

## Voice Architecture (from TECH-STACK-REVIEW.md)

Sequenced after Phase 2. Step 0 shipped in PR #75 as VOIC-03…09 and EVAL-01…04.

- [x] **VARC-01**: Semantic turn detection replaces the fixed 400ms silence timeout — Smart Turn v3 ONNX behind a `TurnDetector` protocol, with automatic fallback to fixed-silence
- [ ] **VARC-02**: Local streaming STT available as the default with cloud fallback, gated on aviation-term WER (EVAL-01…04), not published WER
- [ ] **VARC-03**: Local TTS confirmed at parity for time-to-first-audio and ICAO-preprocessor compatibility
- [ ] **VARC-04**: Architecture selection is flight-phase-routed — low-stakes phases may take a fast path; numerical, procedural, and command content always takes the validated cascade
- [ ] **VARC-05**: Speech-LLM front-end evaluated as a time-boxed spike measuring aviation-term accuracy, not adopted by default
- [x] **VARC-06**: Semantic turn detection on the web path (delivered in Phase 2, plan 02-03). `POST /api/turn-probe` runs the existing `SmartTurnDetector`; the browser probes at `turn_probe_silence_ms` (150) and falls back to `vad_silence_ms` (400), replacing the fixed 1200ms RMS timer.

**Recorded constraint:** every speech-to-speech and speech-LLM option requires an
open-weight LLM backbone. Claude is API-only. Adopting one means replacing Claude,
`validation.py`, and failure attribution — that requires an explicit ADR, not an
incremental slide. See `TECH-STACK-REVIEW.md` §2.

---

## Coverage

| Group | Total | Done | Open |
|---|---|---|---|
| CMD (Phase 1, +2 in Phase 2, +1 deferred) | 9 | 8 | 1 |
| SAFE | 8 | 8 | 0 |
| PROA | 6 | 6 | 0 |
| VALD | 3 | 3 | 0 |
| VOIC | 9 | 9 | 0 |
| EVAL | 7 | 6 | 1 |
| RAG | 3 | 3 | 0 |
| AUTH (Phase 2) | 8 | 8 | 0 |
| MNVR (Phase 3) | 4 | 0 | 4 |
| VIS (Phase 4) | 4 | 0 | 4 |
| VARC (voice arch) | 6 | 2 | 4 |
| **Total** | **67** | **53** | **14** |

35 of the 42 completed requirements are retroactive — they describe work that
existed before this file did. That ratio is the measure of the drift being
corrected here.

**Added 2026-07-31 (+3):** CMD-07, CMD-08, and VARC-06, all claimed by Phase 2.
They were found during Phase 2 context-gathering as work that was already agreed
but carried no requirement ID — the same untracked-scope pattern this file
exists to catch, caught this time before the code landed rather than after.
