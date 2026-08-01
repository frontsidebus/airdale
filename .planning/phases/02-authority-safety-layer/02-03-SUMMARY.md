---
phase: 02-authority-safety-layer
plan: 03
subsystem: voice
tags: [turn-detection, smart-turn-v3, fastapi, mediarecorder, webm, ffmpeg, vad, endpointing]

# Dependency graph
requires:
  - phase: v1.3 pre-phase (VARC-01, PR #77)
    provides: "TurnDetector protocol, SmartTurnDetector, SilenceTurnDetector, create_turn_detector factory, numpy log-mel feature path"
  - phase: 04-web-server-refactor (v1.2)
    provides: "AppState dataclass + FastAPI dependency injection, in-process ASGI web test harness"
provides:
  - "decode_webm_to_samples: a webm decode path that deliberately performs no preprocessing"
  - "POST /api/turn-probe: rate-limited, size-bounded, never-raising semantic turn decision endpoint"
  - "/api/status endpointing fields: turn_probe_available, turn_probe_silence_ms, vad_silence_ms"
  - "Browser probe loop with in-flight guard, spacing check, abort timeout, and an independent 400ms fallback"
affects: [voice-architecture, VARC-02, VARC-04, web-ui, latency-work]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Browser asks / server decides: the cheap acoustic gate picks when to ask, the model decides whether the turn ended"
    - "Capability advertised through /api/status so the browser never duplicates server configuration"
    - "Never-raise HTTP endpoint owned at the handler, not delegated to the collaborator"
    - "Structural + behavioural paired guard on a negative property (no preprocessing)"

key-files:
  created:
    - orchestrator/tests/test_audio_processing.py
    - web/tests/test_turn_probe.py
  modified:
    - orchestrator/orchestrator/audio_processing.py
    - web/server.py
    - web/static/app.js
    - docs/VOICE_PIPELINE.md

key-decisions:
  - "Turn detector built through create_turn_detector, not SmartTurnDetector directly, so the smart->silence fallback resolves at startup rather than mid-utterance"
  - "turn_probe_available reports False for the SilenceTurnDetector: the fallback would only re-derive what the browser already times locally"
  - "Detector inference offloaded via asyncio.to_thread so a probe cannot stutter concurrent TTS streaming"
  - "Added _int_setting to coerce the two new /api/status thresholds; getattr alone yields a MagicMock in tests and a non-numeric JSON value in production if a field is ever missing"
  - "The 2 MiB cap and per-client throttle live server-side even though the browser has matching guards, because the endpoint is unauthenticated and spawns ffmpeg per call"

patterns-established:
  - "Negative properties get two guards: a structural assertion on source text and a behavioural assertion on output, because either alone is easy to defeat by accident"
  - "Transient vs permanent failure is expressed in the response shape (available=true/false), so a client knows whether to retry or degrade for the session"

requirements-completed: [VARC-06]

# Metrics
duration: 23min
completed: 2026-07-31
---

# Phase 02 Plan 03: Semantic Turn Detection on the Web Path Summary

**Browser endpointing moves from a hardcoded 1200ms RMS timer to a semantic decision at 150ms via `POST /api/turn-probe`, with an independent 400ms fallback and no turn model in the browser.**

## Performance

- **Duration:** 23 min
- **Started:** 2026-07-31T21:56Z (base commit)
- **Completed:** 2026-08-01T03:19Z
- **Tasks:** 3
- **Files modified:** 6 (2 created, 4 modified)

## Accomplishments

- `decode_webm_to_samples` gives turn detection its own decode path: ffmpeg to 16 kHz mono float32, no high-pass filter, no silence trim, no normalisation. Returns `None` on failure rather than the input bytes, so the caller gets an unambiguous signal.
- `POST /api/turn-probe` runs the existing `SmartTurnDetector` server-side. It never raises, is throttled per client at half `turn_probe_silence_ms`, and rejects bodies over 2 MiB before any ffmpeg spawn.
- `/api/status` now tells the browser in one call whether to probe and at what thresholds. No existing key was removed or renamed.
- The browser's `pollVAD` silence branch probes at the candidate endpoint with an in-flight guard, a `performance.now()` spacing check, and an `AbortController` timeout — then ends the turn on its own at `vad_silence_ms` regardless of what the probe did or did not say.
- Test count rose from 38 to 55 in `web/tests/`, and `orchestrator/tests/test_audio_processing.py` is new with 11 tests.

## Task Commits

1. **Task 1: Non-preprocessing webm decode helper** — `7543880` (feat)
2. **Task 2: Turn-probe endpoint and /api/status fields** — `2e44400` (feat)
3. **Task 3: Browser probe loop replacing fixed 1200ms endpointing** — `2282171` (feat)

**Plan metadata:** see final commit (docs: complete plan)

## Files Created/Modified

- `orchestrator/orchestrator/audio_processing.py` — added `decode_webm_to_samples`, forked from the ffmpeg block in `convert_webm_to_wav_normalized` and diverging in exactly two ways: raw float32 return instead of a WAV re-wrap, and no `preprocess_audio` call. The docstring carries the reason so nobody "fixes" it later by reusing the transcribe path.
- `orchestrator/tests/test_audio_processing.py` — new. 11 tests: decode success/failure/empty, ffmpeg argv assertions pinning `-ar 16000`, the structural no-preprocessing guard, and the behavioural counterpart asserting a 1s silent tail survives the decode while `preprocess_audio` provably eats it.
- `web/server.py` — `AppState.turn_detector` (defaulted `None`) and `AppState.turn_probe_seen`; detector construction in `lifespan` via `create_turn_detector`; `TurnProbeResponse` model; `POST /api/turn-probe`; three new `/api/status` keys; `_int_setting` helper.
- `web/tests/test_turn_probe.py` — new. 17 in-process ASGI tests with a fake ONNX session, covering the happy path, every degradation shape, both abuse bounds, and the `/api/status` contract including a regression guard that no pre-existing key was dropped.
- `web/static/app.js` — `VAD_SILENCE_MS = 1200` removed; thresholds learned from `/api/status`; `probeTurnEnd()` and `stopVadRecording()` added; silence branch reworked.
- `docs/VOICE_PIPELINE.md` — new `## End-of-Turn Detection` section covering the two-path table (Silero gate locally, JS RMS gate in the browser, same detector), the 1200ms → 150/400ms change, the endpoint contract, and the two constraints that shaped the design.

## Decisions Made

**Detector built through the factory, not the concrete class.** `create_turn_detector(settings)` resolves the smart → silence fallback at startup and logs the `tools/fetch_turn_model.py` hint. A fallback discovered mid-utterance is the worst time to find out.

**`turn_probe_available` is false for the silence fallback.** `SilenceTurnDetector.evaluate` just compares `silence_ms` against a threshold — exactly what the browser already times locally. Advertising it as available would spend a round trip and an ffmpeg spawn per utterance to learn nothing. The endpoint still works with it; `/api/status` just tells the browser not to bother.

**Inference offloaded to a thread.** ONNX inference is sub-20ms but synchronous, and this is the same event loop streaming TTS audio over the chat WebSocket. `asyncio.to_thread` follows the pattern already established for the sync `WhisperClient` (Phase 03 decision) and costs nothing.

**Server-side bounds duplicate browser-side bounds on purpose.** The browser spaces probes and guards in-flight count. The server throttles anyway, because `/api/turn-probe` is unauthenticated, spawns ffmpeg per call, and is driven from a `requestAnimationFrame` loop at ~60 Hz. A client bug should not be a local fork bomb.

**Transient and permanent failure are distinguished in the response.** `available: false` means stop asking for the session; `decode_failed`, `throttled`, `too_large`, and `error` all keep `available: true` so one bad blob does not permanently degrade responsiveness.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] `orchestrator/tests/test_audio_processing.py` did not exist**
- **Found during:** Task 1
- **Issue:** The plan said "extend `orchestrator/tests/test_audio_processing.py`" and listed it under `files_modified`, but no such file was in the tree — `audio_processing.py` had no dedicated test module.
- **Fix:** Created the file, following the conventions of the sibling test modules (module docstring stating what is pinned and why, `_Fake*` scaffolding, class-grouped tests). Added a small `TestPreprocessAudio` class alongside the decode tests so the *contrast* between the two paths stays pinned, not just the decode path in isolation.
- **Files modified:** `orchestrator/tests/test_audio_processing.py`
- **Verification:** `python3 -m pytest orchestrator/tests/test_audio_processing.py -q` → 11 passed
- **Committed in:** `7543880`

**2. [Rule 2 - Missing critical functionality] `/api/status` thresholds could ship a non-numeric value**
- **Found during:** Task 2
- **Issue:** The plan specified the existing `getattr(state.settings, "x", default)` idiom. That idiom returns a `MagicMock` under the web test fixtures, which FastAPI serialises as `{}` — and would do the same in production for any settings object missing the field. The browser does arithmetic with both thresholds; `{}` produces NaN comparisons and silently disables endpointing.
- **Fix:** Added `_int_setting(settings, name, default)`, which keeps the `getattr` idiom and coerces with `int()`, falling back to the default on `TypeError`/`ValueError`. Pinned by `test_status_thresholds_are_integers_even_with_odd_settings`.
- **Files modified:** `web/server.py`
- **Verification:** `python3 -m pytest web/tests/ -q` → 55 passed, 1 skipped
- **Committed in:** `2e44400`

**3. [Rule 2 - Missing critical functionality] Unbounded throttle table on an unauthenticated endpoint**
- **Found during:** Task 2
- **Issue:** The plan specified a `client_host -> last_probe_monotonic` dict for rate limiting but no eviction. On an unauthenticated endpoint, that dict grows with every distinct source address seen.
- **Fix:** Capped at `_MAX_TURN_PROBE_CLIENTS` (64) with least-recently-seen eviction. Pinned by `test_throttle_table_is_bounded`.
- **Files modified:** `web/server.py`
- **Verification:** `python3 -m pytest web/tests/test_turn_probe.py -q` → 17 passed
- **Committed in:** `2e44400`

**4. [Rule 2 - Missing critical functionality] Never-raise contract was untested at the endpoint**
- **Found during:** Task 2
- **Issue:** The plan's error-path test would have exercised a `SmartTurnDetector` with an exploding fake session — but `SmartTurnDetector.evaluate` catches its own exceptions and returns a not-ended decision, so the server's `try/except` around `evaluate` was never reached. The never-raise guarantee was structurally present but unverified.
- **Fix:** Added `_ExplodingDetector`, a detector that violates the contract by raising from `evaluate`, plus `test_a_raising_detector_still_returns_200`. The endpoint owns the guarantee rather than delegating it to whichever detector happens to be installed.
- **Files modified:** `web/tests/test_turn_probe.py`
- **Verification:** `python3 -m pytest web/tests/test_turn_probe.py -q` → 17 passed
- **Committed in:** `2e44400`

---

**Total deviations:** 4 auto-fixed (1× Rule 3, 3× Rule 2)
**Impact on plan:** All four are correctness or robustness requirements on paths the plan already specified. No scope creep — no new config fields, no new dependencies, no changes outside the six files the plan listed.

## Issues Encountered

**Worktree editable install shadowing.** `pip install -e orchestrator` in this environment points at the main checkout, not the worktree, so `web/tests/` imported the *main repo's* `orchestrator.audio_processing` and could not see `decode_webm_to_samples`. Resolved by running web tests with `PYTHONPATH=<worktree>/orchestrator`, which shadows the `.pth` entry. This is an environment artifact of worktree execution, not a code defect: CI runs `pip install -e orchestrator` from the checkout root, and `orchestrator/tests/` was unaffected because pytest inserts `orchestrator/` on `sys.path` for those.

## Verification

| Check | Result |
|---|---|
| `pytest orchestrator/tests/ -q` | 1100 passed, 2 xfailed |
| `pytest web/tests/ -q` | 55 passed, 1 skipped (was 38 passed, 1 skipped) |
| `node --check web/static/app.js` | exit 0 |
| `ruff check ... --config orchestrator/pyproject.toml` (CI form) | All checks passed |
| `ruff format --check ...` (CI form) | 104 files already formatted |
| `grep -c "1200" web/static/app.js` | 0 |
| `grep -c "api/turn-probe" web/server.py` | 4 |
| `grep -c "_vadChunks.slice\|slice(-" web/static/app.js` | 0 |

Not verified: the manual browser smoke check listed as optional in the plan. It needs a running sim-adjacent stack and the 8 MB Smart Turn model present locally, neither of which exists in this worktree. The degraded path (no model → `turn_probe_available: false` → 400ms fallback) is covered by tests; the semantic path is covered with a faked ONNX session but not against the real model.

## Threat Flags

None. The endpoint introduced here (`POST /api/turn-probe`) is the surface the plan's `<threat_model>` already registered, and every `mitigate` disposition in that register is implemented: T-02-03-01 (per-client throttle + browser guards), T-02-03-02 (2 MiB cap before subprocess spawn), T-02-03-03 (ffmpeg on `pipe:0`/`pipe:1` only, decode failure returns `None` and never raises), T-02-03-05 (structural + behavioural no-preprocessing guards), T-02-03-06 (`AbortController` plus the independent fallback stop). No packages were installed.

## User Setup Required

None. The Smart Turn model is optional — without it, `create_turn_detector` degrades to fixed-silence at startup, `/api/status` reports `turn_probe_available: false`, and the browser endpoints at 400ms. To enable the semantic path: `python3 tools/fetch_turn_model.py`.

## Next Phase Readiness

VARC-06 is complete and marked in `REQUIREMENTS.md` (VARC 1→2 done, total 42→43). This plan shares no logic with the concurrent authority plans (02-01, 02-02) and touches no file they touch, so the merge should be clean apart from the `REQUIREMENTS.md` coverage-table totals row, which every plan in this wave increments.

Open follow-ups, none blocking:

- `web/tests/conftest.py` still builds `AppState(settings=MagicMock())`, so `turn_probe_silence_ms` and `vad_silence_ms` resolve to `1` for any test that does not set them explicitly (`int(MagicMock())` returns 1 rather than raising). `test_turn_probe.py` sets them in its own fixture. Setting them once in the shared conftest would be tidier, but was deliberately avoided here to keep merge risk with the concurrent worktrees low.
- Threshold calibration on the web path is untuned. 150/400 are the server defaults inherited from VARC-01's local path; whether 150ms is the right probe point through a browser round trip is an empirical question that needs real speech.

## Self-Check: PASSED

All 7 claimed files verified present on disk. All 4 claimed commits verified in `git log`:
`7543880`, `2e44400`, `2282171`, `eb7e263`. Test counts re-verified against a live run and
corrected in this document (`test_audio_processing.py` is 11 tests, not 13).

---
*Phase: 02-authority-safety-layer*
*Completed: 2026-07-31*
