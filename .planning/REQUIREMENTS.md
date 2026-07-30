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
- [ ] **EVAL-05**: Corpus audio recorded for all phrases, and thresholds set from measured incumbent performance rather than placeholders

## RAG Enhancements ✅ COMPLETE (undocumented until now)

- [x] **RAG-01** (retroactive): Cross-encoder re-ranking gives two-stage retrieval — top-K from the vector store, then top-N by re-rank — `reranker.py`
- [x] **RAG-02** (retroactive): Structure-aware semantic chunking preserves checklist items, procedure steps, and limitation entries — `chunking.py`
- [x] **RAG-03** (retroactive): Aviation data tools cover NOTAM, METAR/TAF, ADS-B, charts, performance, and airspace — `aviation_tools.py`

---

## Phase 2 — Authority & Safety Layer 🚧 RESCOPED

Original scope listed four items; two were already delivered as SAFE-01…04.
What remains is the part that decides **whether MERLIN may act at all**, as
distinct from whether a specific command is safe right now.

- [ ] **AUTH-01**: `authority_level` config field with values `advisory` | `assisted` | `full`, enforced at the single point where `set_aircraft_control` reaches SimConnect
- [ ] **AUTH-02**: `advisory` describes the intended action and sends nothing to the sim
- [ ] **AUTH-03**: `assisted` executes commands that pass safety cleanly but withholds any that raise a `warning` severity, deferring to the pilot
- [ ] **AUTH-04**: `full` preserves current behavior — execute unless `blocked`
- [ ] **AUTH-05**: Pilot override detection identifies manual control input contradicting a MERLIN-issued command
- [ ] **AUTH-06**: A detected override drops authority to `advisory` for a cooldown period and informs the pilot
- [ ] **AUTH-07**: Watchdog bounds the interval between command dispatch and `AdapterCommandAck`; on expiry MERLIN stops issuing commands and says so
- [ ] **AUTH-08**: Authority level is surfaced in `/api/status` and the web UI so the current mode is never ambiguous

**Explicit non-goals for Phase 2:** no new command types, no new envelope rules.
Those are SAFE-* territory and already exist.

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

- [ ] **VARC-01**: Semantic turn detection replaces the fixed 400ms silence timeout
- [ ] **VARC-02**: Local streaming STT available as the default with cloud fallback, gated on aviation-term WER (EVAL-01…04), not published WER
- [ ] **VARC-03**: Local TTS confirmed at parity for time-to-first-audio and ICAO-preprocessor compatibility
- [ ] **VARC-04**: Architecture selection is flight-phase-routed — low-stakes phases may take a fast path; numerical, procedural, and command content always takes the validated cascade
- [ ] **VARC-05**: Speech-LLM front-end evaluated as a time-boxed spike measuring aviation-term accuracy, not adopted by default

**Recorded constraint:** every speech-to-speech and speech-LLM option requires an
open-weight LLM backbone. Claude is API-only. Adopting one means replacing Claude,
`validation.py`, and failure attribution — that requires an explicit ADR, not an
incremental slide. See `TECH-STACK-REVIEW.md` §2.

---

## Coverage

| Group | Total | Done | Open |
|---|---|---|---|
| CMD (Phase 1) | 6 | 6 | 0 |
| SAFE | 8 | 8 | 0 |
| PROA | 6 | 6 | 0 |
| VALD | 3 | 3 | 0 |
| VOIC | 9 | 9 | 0 |
| EVAL | 5 | 4 | 1 |
| RAG | 3 | 3 | 0 |
| AUTH (Phase 2) | 8 | 0 | 8 |
| MNVR (Phase 3) | 4 | 0 | 4 |
| VIS (Phase 4) | 4 | 0 | 4 |
| VARC (voice arch) | 5 | 0 | 5 |
| **Total** | **61** | **39** | **22** |

35 of the 39 completed requirements are retroactive — they describe work that
existed before this file did. That ratio is the measure of the drift being
corrected here.
