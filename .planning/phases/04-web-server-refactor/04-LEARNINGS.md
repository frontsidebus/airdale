---
phase: 04
phase_name: "Web Server Refactor"
project: "MERLIN — Airdale"
generated: "2026-07-29"
counts:
  decisions: 10
  lessons: 8
  patterns: 8
  surprises: 6
missing_artifacts:
  - "04-VERIFICATION.md"
---

# Phase 04 Learnings: Web Server Refactor

## Decisions

### A single `AppState` dataclass replaces all 11 module-level mutable globals
Fields: `settings`, `sim_client`, `claude_client`, `context_store`, `phase_detector`, `whisper_client`, `tts_client`, `tts_cache`, `sim_connected`, `bridge_last_seen`, `bridge_connected`. Created once in the lifespan and assigned to `app.state.app_state`.

**Rationale:** The web server was untestable — every route read process-global mutable state, so tests could not substitute fakes. One typed container makes the whole surface injectable.
**Source:** 04-01-SUMMARY.md, 04-01-PLAN.md

### Access via a `get_app_state(request)` dependency, not direct `app.state` reads
`def get_app_state(request: Request) -> AppState: return request.app.state.app_state`, wired into route handlers with `Depends(get_app_state)`.

**Rationale:** Going through a dependency callable is what makes `dependency_overrides` possible in tests. Reading `request.app.state` inline in each handler would have been the same coupling in a new location.
**Source:** 04-01-PLAN.md, 04-01-SUMMARY.md

### `settings` lives in `AppState` *and* stays module-level
The module keeps `settings = load_settings()` while `AppState` also carries a `settings` field.

**Rationale:** Logging configuration runs at import time, before the lifespan exists, so something must be available that early. The `AppState` copy exists specifically so Phase 05 could override it. Recorded as an explicit trade-off: "settings included in AppState for Phase 5 testability (module-level kept for early logging)."
**Source:** 04-01-SUMMARY.md, 04-01-PLAN.md

### Immutable module-level values were deliberately left alone
`_LOW_CONFIDENCE_THRESHOLD`, `_POST_SPEECH_PAUSE_SECS`, `_CACHEABLE_PHRASES`, and `_STATIC_DIR` stayed at module scope.

**Rationale:** The problem was mutable shared state, not module scope. Constants are not a testability barrier, and moving them would have inflated the diff without benefit.
**Source:** 04-01-PLAN.md

### The barge-in cancellation closure was explicitly not restructured
`_cancel_active_response()` references only its enclosing locals (`active_response_task`, `interrupt_event`, `ws`), so the plan instructed: "per D-07, do NOT restructure it."

**Rationale:** Barge-in is the most timing-sensitive path in the server. Since the closure captured no globals, it needed no change — and touching it would have put the phase's riskiest behavior into a refactor with no test coverage.
**Source:** 04-01-PLAN.md, 04-01-SUMMARY.md

### Helper functions take `state: AppState` as an explicit parameter
Seven helpers were re-signed: `_stream_response`, `_tts_websocket_stream`, `_tts_rest_fallback`, `_send_tts_chunk_rest`, `_transcribe_with_confidence`, `_transcribe_audio_bytes_with_confidence`, `_prepopulate_tts_cache`.

**Rationale:** Non-route functions cannot use `Depends`. Explicit parameter threading keeps the data dependency visible in every signature — the alternative, a context variable, would have reintroduced invisible ambient state.
**Source:** 04-01-PLAN.md, 04-01-SUMMARY.md

### `whisper_client` was typed and constructed as a raw `httpx.AsyncClient`
Despite the plan's interfaces block declaring `whisper_client: WhisperClient | None`, execution created it as `httpx.AsyncClient(timeout=30.0)` in the lifespan, recorded as "matching existing REST pattern."

**Rationale:** As stated, consistency with the adjacent `tts_client` field. This walked back part of Phase 03's consolidation and was later corrected — see Surprises.
**Source:** 04-01-SUMMARY.md

### The `_on_state` callback parameter was renamed to `sim_state`
The telemetry callback's parameter previously shadowed the name now used for the `AppState` instance.

**Rationale:** Introducing a variable named `state` across the whole file makes any existing `state` parameter a silent shadowing bug. Renaming the narrower one is the safer direction.
**Source:** 04-01-SUMMARY.md

### WebSocket routes get their own dependency callable, `get_ws_app_state`
`ws_chat` and `ws_telemetry` use `Depends(get_ws_app_state)`; the three HTTP routes use `Depends(get_app_state)`.

**Rationale:** FastAPI WebSocket handlers cannot accept a `Request` parameter, so the `Request`-based callable does not work there. Two callables, one per protocol, rather than one callable with a union parameter.
**Source:** 04-02-SUMMARY.md, 04-SECURITY.md

### Plan 02 was declared non-autonomous with a blocking human checkpoint
`autonomous: false`, with a `type="checkpoint:human-verify" gate="blocking"` task listing eight concrete browser steps and a `resume-signal` of "approved".

**Rationale:** The refactor's success criterion was "identical runtime behavior," which no static check can establish. Structural correctness was automated; behavior preservation was gated on a human driving the UI.
**Source:** 04-02-PLAN.md

---

## Lessons

### FastAPI WebSocket handlers cannot take a `Request` parameter
A dependency built around `Request` works for HTTP routes and fails for WebSocket routes, which need a `WebSocket`-based callable instead.

**Context:** Discovered when the plan's `Depends(get_app_state)` count came up short. The resolution — a parallel `get_ws_app_state` — is now the established pattern for the two WebSocket endpoints.
**Source:** 04-02-SUMMARY.md

### A grep-count acceptance criterion can fail while the code is right
The criterion `grep -c "Depends(get_app_state)" web/server.py == 5` returned 3. The intent — five DI-wired handlers — was satisfied as 3 HTTP + 2 WebSocket sites.

**Context:** Plan 02 logged it as a stale criterion rather than a defect, and recorded the arithmetic explicitly. Counting a specific string is brittle when the implementation legitimately needs two spellings of the same idea; counting the *concept* (total DI sites) would have survived.
**Source:** 04-02-SUMMARY.md, 04-01-PLAN.md

### Introducing a variable named `state` across a large file creates shadowing hazards
Any pre-existing `state` parameter silently becomes a different object mid-function.

**Context:** Caught for `_on_state`'s parameter, which was renamed to `sim_state`. Worth scanning for the new name before threading it through ~40 call sites, not after.
**Source:** 04-01-SUMMARY.md

### Import-time work pins some state at module level no matter how thorough the DI refactor
Logging is configured from `settings` before the lifespan runs, so `settings = load_settings()` had to stay at module scope even though `AppState` also carries it.

**Context:** The plan anticipated this and carved out the exception up front rather than discovering it at runtime. It is the one intentional survivor of the "zero module-level mutable state" goal.
**Source:** 04-01-PLAN.md, 04-01-SUMMARY.md

### That one surviving global was enough to undercut the refactor's stated purpose
Phase 04 existed so Phase 05 could use `dependency_overrides`. Phase 05 ended up monkeypatching module globals instead, and the reason recorded at milestone close is the early-boot module state in `web/server.py`.

**Context:** Logged as a v1.2 deferred item: "`web/server.py` early-boot module state — tests monkeypatch globals rather than use DI overrides — acknowledged (acceptable for v1.2; revisit if logging infra changes)." A partial DI refactor buys partial testability.
**Source:** .planning/STATE.md, 04-01-SUMMARY.md

### Converting bare globals to attribute access surfaces missing None checks
Where code previously read a global that was assumed non-`None`, the refactor had to add explicit guards for `tts_client` and `whisper_client`.

**Context:** Noted in plan 01's Task 2 outcome: "Added None checks for tts_client and whisper_client where bare globals were previously used." The optional-typed dataclass field makes the latent assumption visible; the bare global hid it.
**Source:** 04-01-SUMMARY.md

### Structural refactors are grep-verifiable; behavior preservation is not
Plan 01 closed on seven mechanical checks (`ast.parse`, `ruff`, five grep counts). None of them could tell whether barge-in still worked.

**Context:** That gap is exactly what plan 02's blocking human checkpoint and the later 6-test UAT existed to fill — and the UAT is where barge-in, TTS playback, and telemetry streaming were actually confirmed.
**Source:** 04-01-SUMMARY.md, 04-02-PLAN.md, 04-UAT.md

### An exhaustive rewrite needs an explicit final-sweep step naming every identifier
Plan 01's Task 2 ended with a sweep instruction listing all ten old global names to search for, qualified as "NOT qualified with `state.` or inside the AppState class definition."

**Context:** ~40 references across 12 functions in one file. Enumerating the search terms in the plan turns "did I get them all" from a judgment call into a checklist — and plan 01 recorded zero deviations.
**Source:** 04-01-PLAN.md, 04-01-SUMMARY.md

---

## Patterns

### Typed state container on `app.state` behind a dependency callable
A `@dataclass AppState` created once in the lifespan, assigned to `app.state.app_state`, and reached only through `Depends(get_app_state)`.

**When to use:** Any FastAPI app whose handlers need shared, mutable, lifespan-scoped resources. The dataclass gives type checking; the dependency gives test overrides.
**Source:** 04-01-SUMMARY.md (`tech_stack.patterns`)

### Parallel HTTP and WebSocket dependency callables
`get_app_state(request: Request)` for HTTP routes, `get_ws_app_state(...)` for WebSocket routes, both returning the same object from `app.state`.

**When to use:** Whenever a FastAPI app serves both protocols and needs the same injected state. Necessary, not optional — the `Request`-based form does not work for WebSockets.
**Source:** 04-02-SUMMARY.md, 04-SECURITY.md

### Explicit state parameter threading for non-route helpers
Helpers accept `state: AppState` and pass it down; the call chain (`ws_chat` → `_stream_response` → `_tts_websocket_stream` → `_tts_rest_fallback` → `_send_tts_chunk_rest`) threads it the whole way.

**When to use:** Functions below the route layer, where `Depends` is unavailable. Verified as key links in the plan frontmatter with patterns like `_stream_response\(ws.*state\)`.
**Source:** 04-01-PLAN.md, 04-02-PLAN.md

### Final-sweep task step enumerating every identifier to eliminate
Close a large mechanical refactor with an explicit list of the old names plus the exception rule for legitimate remaining occurrences.

**When to use:** Any rename or rehoming touching dozens of references in one file. Pairs naturally with `grep -c "<old name>" == 0` acceptance criteria.
**Source:** 04-01-PLAN.md

### `ast.parse` plus inline Python assertions as the verify command
The verify block ran `python -c "import ast; ast.parse(open('web/server.py').read())"` followed by an inline script asserting `'global ' not in content` and `content.count('Depends(get_app_state)') >= 5`.

**When to use:** Refactors of a module too entangled to import cheaply in a test harness. Parsing proves syntactic validity without executing imports or requiring services.
**Source:** 04-01-PLAN.md

### Blocking human-verify checkpoint with numbered steps and a resume signal
A `checkpoint:human-verify` task carrying `<what-built>`, `<how-to-verify>` (eight ordered steps including the barge-in sequence and a `curl` of `/api/status`), and `<resume-signal>`.

**When to use:** Behavior-preserving refactors, and anything whose success criterion is subjective or requires live external services. Writing the steps out is what makes the approval meaningful.
**Source:** 04-02-PLAN.md

### Conversational UAT as a separate dated artifact with per-test expected/result
`04-UAT.md` records six tests (cold start, chat round-trip, telemetry display, TTS playback, barge-in, status endpoint), each with an `expected:` paragraph and a `result:` verdict, plus a summary tally and a `## Gaps` section.

**When to use:** After a refactor that a human already spot-approved — the UAT turns "approved" into a re-runnable, itemized record. 6 passed, 0 issues here.
**Source:** 04-UAT.md

### Threat register verified against file:line evidence, not prose
`04-SECURITY.md` gives each of four threats a disposition, a CLOSED/OPEN status, and concrete evidence (`web/server.py:179,265`, `272-283`, `1269`, `377`), plus explicit "Unregistered Flags: None" and "Accepted Risks: None" sections.

**When to use:** Retroactive security audit of a completed phase. Citing lines makes the audit re-checkable later; it is also how the audit incidentally documented drift the phase artifacts had not.
**Source:** 04-SECURITY.md

---

## Surprises

### The plan's own acceptance criterion was wrong, and the code was right
`grep -c "Depends(get_app_state)" == 5` counted 3. The correct total was 3 HTTP + 2 WebSocket DI sites, because WebSocket handlers require a separate callable.

**Impact:** Plan 02 had to adjudicate the mismatch rather than fix code, and documented the reasoning in its deviations section. A brittle criterion cost a verification cycle on a refactor that had no defect.
**Source:** 04-02-SUMMARY.md

### The refactor typed `whisper_client` as a raw `httpx.AsyncClient`, undoing part of Phase 03
Phase 03 existed to make one `WhisperClient` the only transcription path. Phase 04's plan specified `whisper_client: WhisperClient | None`, but execution created `httpx.AsyncClient(timeout=30.0)` and justified it as "matching existing REST pattern."

**Impact:** A consolidation regression introduced one phase after the consolidation. It was fixed by later work — Phase 03's post-hoc resolution cites `web/server.py:1272 — result = await state.whisper_client.transcribe_with_confidence(...)` — but nothing in Phase 04's artifacts flags the regression or its repair.
**Source:** 04-01-SUMMARY.md, 04-01-PLAN.md, 03-VERIFICATION.md

### The security audit revealed two service clients that appear nowhere in the phase's artifacts
`04-SECURITY.md` documents lifespan teardown calling `deepgram_client.aclose()` and `cartesia_client.aclose()` — neither is among `AppState`'s 11 documented fields.

**Impact:** Additional STT/TTS backends had been added between plan execution (2026-03-28) and the audit (2026-04-16) without appearing in any phase plan or summary. This is the same drift STATE.md flags in its "Scope Divergence Note," found here by an audit looking at something else entirely.
**Source:** 04-SECURITY.md, 04-01-SUMMARY.md, .planning/STATE.md

### Zero deviations across a 40-reference, 12-function rewrite
Plan 01 rewrote every state access in the file, added a dataclass and a dependency, deleted 11 globals, 2 helper functions, and 3 `global` statements — and recorded "None -- plan executed exactly as written."

**Impact:** Attributable to the plan doing the analysis first: it enumerated every global with line numbers, listed every function's exact substitutions, and pre-declared which functions needed no change (`_split_at_sentence`, `index`).
**Source:** 04-01-SUMMARY.md, 04-01-PLAN.md

### The phase achieved its structural goal but not the downstream goal it was built for
"Purpose: Make the web server testable via dependency_overrides (Phase 5 depends on this)." Phase 05 monkeypatched module globals instead.

**Impact:** Carried into v1.2 close-out as an acknowledged deferred item rather than reopened. The refactor was still worth doing — it is what made the Phase 05 tests writable at all — but the specific mechanism it was justified by went unused.
**Source:** 04-01-PLAN.md, .planning/STATE.md

### The phase has no VERIFICATION.md at all
Unlike Phases 01–03, verification here was split across plan 02's automated smoke checks, a blocking human approval, a later 6-test UAT, and a retroactive security audit.

**Impact:** No single artifact scores the phase against its ROADMAP success criteria, and `gsd-sdk` reports `has_verification: false` for Phase 04. The coverage is arguably better in substance — a human actually exercised barge-in — but it is not machine-readable as phase verification.
**Source:** 04-UAT.md, 04-SECURITY.md, 04-02-SUMMARY.md
