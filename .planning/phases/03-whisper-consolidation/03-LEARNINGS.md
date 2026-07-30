---
phase: 03
phase_name: "Whisper Consolidation"
project: "MERLIN — Airdale"
generated: "2026-07-29"
counts:
  decisions: 11
  lessons: 9
  patterns: 7
  surprises: 5
missing_artifacts:
  - "03-UAT.md"
---

# Phase 03 Learnings: Whisper Consolidation

## Decisions

### Reuse Phase 02's TTS client lifecycle pattern verbatim for STT
`WhisperClient` creates a persistent `httpx.AsyncClient` in `__init__`, exposes `aclose()`, and implements `__aenter__`/`__aexit__`. The plan listed `orchestrator/orchestrator/tts/base.py` in `read_first` and the summary declares `requires: phase 02-tts-integration provides "TTSClient lifecycle pattern (aclose) used as reference"`.

**Rationale:** Two client wrappers in the same codebase should have the same shape. Naming the dependency in the plan frontmatter made the reuse explicit rather than coincidental.
**Source:** 03-01-PLAN.md, 03-01-SUMMARY.md

### Keep the confidence formula byte-identical during the rewrite
`confidence = min(1.0, max(0.0, math.exp(avg_logprob)))`, averaged across `verbose_json` segments, falling back to `0.5` when no segments are returned.

**Rationale:** The rewrite's purpose was consolidation, not recalibration. Changing the scoring formula in the same change would have made any downstream confidence-threshold regression impossible to attribute.
**Source:** 03-01-SUMMARY.md, 03-01-PLAN.md

### Standardize on `/v1/audio/transcriptions` and drop `/asr`
The OpenAI-compatible endpoint became the only endpoint; all `/asr` references were removed and asserted absent.

**Rationale:** The three prior implementations had diverged onto different endpoints. Picking the OpenAI-compatible one keeps the client usable against any compatible server, not just `faster-whisper-server`.
**Source:** 03-01-PLAN.md

### Keep both `transcribe()` and `transcribe_with_confidence()` rather than one method with a flag
Two methods: one returning `str`, one returning `TranscriptionResult`.

**Rationale:** The two call sites want genuinely different things — the CLI voice path wants text, the web server wants text plus a score to gate on. A boolean parameter changing the return type is worse than two names.
**Source:** 03-01-PLAN.md

### Retry 3 times with `1.5 * attempt` backoff, never on 4xx
Retries cover connect errors, timeouts, and 5xx; 400 and 422 raise immediately.

**Rationale:** 4xx means the request is wrong and will stay wrong — retrying wastes a multiple of the timeout budget on a guaranteed failure. Backoff uses `asyncio.sleep`, never `time.sleep`.
**Source:** 03-01-SUMMARY.md, 03-01-PLAN.md

### Retain no backward-compatible sync API
`httpx.Client`, `time.sleep`, `close()`, and `__enter__`/`__exit__` were all removed, leaving a clean async-only surface. The summary states plainly: "No backward-compatible sync API retained — consumers must be updated in Plan 02."

**Rationale:** A dual sync/async surface doubles the retry and lifecycle logic. The cost was accepted knowingly — and is exactly where the phase went wrong.
**Source:** 03-01-SUMMARY.md

### Audio preprocessing stays in `VoiceInput`, not in `WhisperClient`
`preprocess_audio` and `samples_to_wav_bytes` remain on the caller's side; the client receives finished WAV bytes.

**Rationale:** Preprocessing is microphone-capture-specific (high-pass, trim, normalize). The web server uploads already-encoded audio and must not be forced through a mic pipeline.
**Source:** 03-02-PLAN.md

### `VoiceInput` takes a `WhisperClient`, not a `whisper_url` string
The constructor parameter changed from `whisper_url: str` to `whisper_client: WhisperClient`; `Orchestrator` constructs the client and injects it.

**Rationale:** Same inversion Phase 02 applied to `VoiceOutput`. One client instance per process, owned and closed by whoever created it.
**Source:** 03-02-SUMMARY.md, 03-02-PLAN.md

### Upgrade the production Whisper model to `large-v3-turbo`, keep `tiny` in dev
`docker-compose.yml` default moved from `medium` to `large-v3-turbo`; `docker-compose.dev.yml` keeps `WHISPER__MODEL=tiny` with a comment pointing at the production default.

**Rationale:** `large-v3-turbo` gives better accuracy (~7.7% WER) and roughly 3x the speed of `medium` — a rare strict improvement on both axes. Dev keeps `tiny` for startup time.
**Source:** 03-02-SUMMARY.md, 03-02-PLAN.md

### Leave `WhisperClient._DEFAULT_MODEL` at `"medium"` while the config default becomes `large-v3-turbo`
The two defaults were deliberately allowed to diverge.

**Rationale:** The client constant is a fallback for standalone use of the class; the config value is what production actually passes. Documented as an explicit decision rather than an oversight.
**Source:** 03-02-SUMMARY.md

### Keep unused `filename` and `mime_type` parameters on the web server's transcription helper
`_transcribe_with_confidence(audio_bytes, filename="audio.wav", mime_type="audio/wav")` retains both parameters even though the client always sends `audio.wav` internally.

**Rationale:** Preserves the signature for existing callers; the Whisper server auto-detects format, so the values were never load-bearing. Explicitly noted in the plan as acceptable.
**Source:** 03-02-PLAN.md

---

## Lessons

### An executor's stated premise about a prior plan's output can be wrong, and everything built on it inherits the error
Plan 02's deviation log records: "Plan interfaces described async methods, but the actual WhisperClient from Plan 01 uses synchronous `httpx.Client` with blocking `time.sleep` retries." This was false — Plan 01 delivered a fully async client, verified at `whisper_client.py:73` (`httpx.AsyncClient`), line 131 (`async def transcribe`), and line 277 (`aclose`).

**Context:** On that false premise, plan 02 wrapped every call in `asyncio.to_thread()` and switched `aclose()` to `close()`, producing four blocker defects across three files. The deviation was logged as "Rule 3 - Blocking," which is the exact severity that should have triggered re-reading the artifact rather than working around it.
**Source:** 03-02-SUMMARY.md, 03-VERIFICATION.md

### `asyncio.to_thread()` on an `async def` method fails silently
It passes the coroutine *function* to the thread pool as a plain callable. Calling it there produces a coroutine object that is never awaited, so the caller receives the coroutine instead of the result — no exception at the wrap site, no warning at the call site.

**Context:** Applied at `voice.py:197`, `server.py:989`, `server.py:291`, and `main.py:176`. The verifier's data-flow trace classified both transcription paths as HOLLOW.
**Source:** 03-VERIFICATION.md

### A fully green test suite proves nothing about consumer wiring when tests mock the client in isolation
390 orchestrator tests passed — including all 35 new `WhisperClient` tests — while voice transcription and web transcription were both completely non-functional at runtime.

**Context:** The verifier stated it directly: "Tests pass because they test WhisperClient in isolation. The broken consumer wiring is not covered by the test suite." This is the strongest argument in the milestone for the integration tests that Phase 05 went on to add.
**Source:** 03-VERIFICATION.md, 03-02-SUMMARY.md

### Renaming a lifecycle method breaks only the shutdown path — the least-exercised code in the system
`close()` → `aclose()` meant `Orchestrator.stop()` and the web server lifespan teardown would raise `AttributeError` on every clean shutdown, potentially masking other teardown errors.

**Context:** Two call sites (`main.py:166`, `server.py:234`) shipped broken. Nothing in the test suite or in normal development exercises a clean shutdown, so the defect was invisible until static verification.
**Source:** 03-VERIFICATION.md

### Goal-backward verification at the call-site level catches what test-suite verification cannot
The verifier did not stop at "does the artifact exist and is it substantive" — it traced whether each call site would actually produce data, and marked artifacts `STUB` when construction was correct but invocation was not.

**Context:** Yielded 4 blockers and 1 warning against a passing suite, with exact file:line locations and the mechanical fix for each. Score was 6/9 truths, and the phase was correctly marked `gaps_found` rather than passed.
**Source:** 03-VERIFICATION.md

### Removing a sync API before its consumers are migrated creates a real window of breakage
Plan 01's decision to retain no sync surface was sound, but it made plan 02 a hard dependency for a working system rather than an improvement to a working one.

**Context:** Plan 01's own summary flagged this: "No backward-compatible sync API retained — consumers must be updated in Plan 02." When plan 02 then misread the interface, there was no fallback path — the old sync code was already gone.
**Source:** 03-01-SUMMARY.md, 03-VERIFICATION.md

### Verification gaps can be fixed incidentally by later work and go unnoticed for weeks
All four FAILs were resolved during Phase 04/05 and the `8587ba5` CI-unblocking commit, but nothing linked those fixes back to the Phase 03 report.

**Context:** The resolution was only discovered on 2026-04-18 during a `/gsd-next` spot-check before the v1.2 milestone close-out — roughly three weeks after the gaps were logged. The report now carries a `## Post-hoc Resolution` section mapping each original FAIL to its current file:line.
**Source:** 03-VERIFICATION.md

### Annotating a resolution in the file body does not change the machine-readable status
The frontmatter still reads `status: gaps_found` and `score: 6/9`, so tooling continues to report Phase 03 as having gaps even though the body documents all four as RESOLVED with evidence.

**Context:** Acknowledged as a deferred item at milestone close: "tool still reads `gaps_found`; evidence in 03-VERIFICATION.md." Frontmatter and body can disagree, and automation trusts the frontmatter.
**Source:** 03-VERIFICATION.md, .planning/STATE.md

### The fix for a whole class of async/sync defects can be purely mechanical
The verifier could state all four repairs as literal find-and-replace pairs and explicitly noted "No human verification required for these gaps."

**Context:** Worth recognizing early — a defect class this uniform does not need investigation, only application. The delay in fixing them was not a difficulty problem.
**Source:** 03-VERIFICATION.md

---

## Patterns

### Async client lifecycle: persistent client in `__init__`, `aclose()`, plus async context manager
`self._client = httpx.AsyncClient(timeout=self.timeout)` in the constructor, `async def aclose()`, and `__aenter__`/`__aexit__` for scoped usage.

**When to use:** Every HTTP client wrapper in this codebase — established by Phase 02's TTS clients and deliberately mirrored here. The context manager adds a second, scope-safe way to guarantee cleanup for callers who do not manage lifetime themselves.
**Source:** 03-01-SUMMARY.md (`patterns-established`)

### Retry with `asyncio.sleep` backoff and a 4xx short-circuit
Loop to `_MAX_RETRIES`, `break` immediately on 4xx, `await asyncio.sleep(1.5 * attempt)` between attempts, raise a domain error (`WhisperClientError`) after exhaustion.

**When to use:** Any client calling a service that can be transiently unavailable. The 4xx break is the part most often missed.
**Source:** 03-01-SUMMARY.md (`patterns-established`), 03-VERIFICATION.md

### TDD with separate RED and GREEN commits
Plan 01 produced `5ec90f6` (test) — failing async tests — then `ee5314c` (feat) — the implementation that makes them pass.

**When to use:** Rewrites of an existing component where behavior must be preserved. Writing the async tests first pinned the exact retry timing, confidence formula, and 4xx behavior before the implementation could drift. This is also the one plan in the phase with zero deviations.
**Source:** 03-01-SUMMARY.md

### A `<behavior>` block enumerating every test case before the action block
Plan 01 listed 14 specific test expectations ("Backoff timing is 1.5*attempt seconds (uses asyncio.sleep, not time.sleep)", "Low avg_logprob (-1.5) produces confidence < 0.3") ahead of any implementation instruction.

**When to use:** `tdd="true"` tasks. It makes the RED commit writable without inventing the spec, and it doubles as the acceptance criteria.
**Source:** 03-01-PLAN.md

### Declare cross-phase pattern reuse in the plan's dependency graph
The plan put `orchestrator/orchestrator/tts/base.py` in `read_first` and the summary recorded a `requires:` edge on Phase 02 for the *pattern*, not for code.

**When to use:** When a phase should mirror an earlier phase's shape. Turns "be consistent" from a hope into a plan input.
**Source:** 03-01-PLAN.md, 03-01-SUMMARY.md

### `Post-hoc Resolution` appendix with a FAIL → current-evidence table
Rather than editing or deleting the failed findings, the report appends a dated section mapping each original FAIL to the current file:line that resolves it, plus an explicit `**Override:**` statement.

**When to use:** Reconciling stale verification reports at milestone close. Preserves the original finding as history while recording the resolution — but note it does not update the frontmatter status.
**Source:** 03-VERIFICATION.md

### Keep the thin client thin: preprocessing belongs to the caller
`WhisperClient` accepts WAV bytes and nothing else; capture-specific transforms stay in `VoiceInput`.

**When to use:** Shared clients with heterogeneous callers. Any transform that only one caller needs is a reason to keep it out of the shared layer.
**Source:** 03-02-PLAN.md

---

## Surprises

### The deviation log asserted the exact opposite of what the previous plan delivered
Plan 02 recorded that Plan 01 had produced a sync client with `time.sleep` retries. Plan 01's own summary, one directory over, says: "Rewrote WhisperClient from sync httpx.Client to async httpx.AsyncClient" and "Replaced time.sleep with asyncio.sleep in retry loops."

**Impact:** Four blocker defects and one warning across `voice.py`, `main.py`, and `server.py`, shipping the phase with `status: gaps_found`. The verifier had to diagnose it as a single root cause rather than five separate bugs — which it did, in one paragraph.
**Source:** 03-02-SUMMARY.md, 03-01-SUMMARY.md, 03-VERIFICATION.md

### Two user-facing features were entirely broken while the test suite reported 390 passing
Voice input and web transcription both returned coroutine objects instead of text. Both shutdown paths would raise `AttributeError`. The suite was green.

**Impact:** The clearest evidence in the milestone that unit coverage of a client says nothing about whether consumers call it correctly — and direct motivation for the Phase 05 web server test work.
**Source:** 03-VERIFICATION.md

### A plan self-reported "Self-Check: PASSED" while introducing four blockers
Plan 02's summary closes with `## Self-Check: PASSED` and `Known Stubs: None -- all transcription paths are fully wired to WhisperClient`.

**Impact:** Executor self-assessment was confidently wrong, because the executor was checking its work against its own mistaken model of the interface. Independent verification, not self-check, is what caught it.
**Source:** 03-02-SUMMARY.md, 03-VERIFICATION.md

### The gaps outlived the phase by three weeks and were fixed by unrelated work
No remediation plan was ever written. The four defects were repaired incidentally during Phase 04/05 and the CI-unblocking commit, and the resolution surfaced only during a pre-close-out spot-check on 2026-04-18.

**Impact:** The phase carried a `gaps_found` status through the rest of the milestone. It was closed by annotation rather than by re-verification, leaving a permanent frontmatter/body disagreement that the milestone had to explicitly defer.
**Source:** 03-VERIFICATION.md, .planning/STATE.md

### The verification report predates the work it verifies by over a day
`03-VERIFICATION.md` frontmatter reads `verified: 2026-03-26T00:00:00Z`; plan 01 completed `2026-03-27T21:43:43Z` and plan 02 at `2026-03-27T21:50:29Z`.

**Impact:** Same timestamp inconsistency as Phase 02. The report's content is clearly post-hoc — it cites exact line numbers in the finished files — so the finding stands, but verification timestamps in this milestone cannot be used to reconstruct order of events.
**Source:** 03-VERIFICATION.md, 03-01-SUMMARY.md, 03-02-SUMMARY.md
