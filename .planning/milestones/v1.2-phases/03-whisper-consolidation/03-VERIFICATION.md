---
phase: 03-whisper-consolidation
verified: 2026-03-26T00:00:00Z
re_verified: 2026-07-29T00:00:00Z
status: passed
score: 9/9 must-haves verified (3 originally failed, all resolved post-hoc)
re_verification: true
gaps: []
resolved_gaps:
  - truth: "VoiceInput.transcribe() delegates to the injected async WhisperClient instead of inline httpx"
    status: failed
    reason: "voice.py uses asyncio.to_thread(self._whisper_client.transcribe, wav_bytes) but transcribe() is async def. asyncio.to_thread wraps a coroutine object and passes it to a thread — the coroutine never executes. Transcription returns the coroutine object or raises, silently breaking voice input."
    artifacts:
      - path: "orchestrator/orchestrator/voice.py"
        issue: "Line 197: asyncio.to_thread(self._whisper_client.transcribe, wav_bytes) — transcribe() is async, not sync; should be: await self._whisper_client.transcribe(wav_bytes)"
    missing:
      - "Replace asyncio.to_thread(self._whisper_client.transcribe, wav_bytes) with await self._whisper_client.transcribe(wav_bytes) at voice.py:197"

  - truth: "Web server /api/transcribe and chat WS transcription use the shared WhisperClient"
    status: partial
    reason: "Web server correctly creates WhisperClient and routes transcription through it, but _transcribe_with_confidence() wraps the async transcribe_with_confidence() call in asyncio.to_thread (line 989-991) and the status endpoint does the same for is_available() (line 291). The async methods will not execute inside the thread pool — they return coroutine objects. Additionally, server.py calls _whisper_client.close() on shutdown (line 234) but WhisperClient only has aclose()."
    artifacts:
      - path: "web/server.py"
        issue: "Line 989-991: asyncio.to_thread(_whisper_client.transcribe_with_confidence, audio_bytes) — async method wrapped in asyncio.to_thread; line 291: asyncio.to_thread(_whisper_client.is_available) — same bug; line 234: _whisper_client.close() — method does not exist, only aclose()"
    missing:
      - "Replace asyncio.to_thread(_whisper_client.transcribe_with_confidence, audio_bytes) with await _whisper_client.transcribe_with_confidence(audio_bytes) in _transcribe_with_confidence()"
      - "Replace asyncio.to_thread(_whisper_client.is_available) with await _whisper_client.is_available() in /api/status handler"
      - "Replace _whisper_client.close() with await _whisper_client.aclose() in lifespan shutdown"

  - truth: "Client has aclose() for lifecycle management following TTS pattern"
    status: partial
    reason: "WhisperClient.aclose() exists and is correct (Plan 01). However both consumers call the non-existent .close() method instead of await .aclose() — main.py:166 and server.py:234. The orchestrator will raise AttributeError on every clean shutdown."
    artifacts:
      - path: "orchestrator/orchestrator/main.py"
        issue: "Line 166: self._whisper_client.close() — method does not exist; should be: await self._whisper_client.aclose(). Also line 176: await asyncio.to_thread(self._whisper_client.is_available) — is_available is async; should be: await self._whisper_client.is_available()"
      - path: "web/server.py"
        issue: "Line 234: _whisper_client.close() — method does not exist; should be: await _whisper_client.aclose()"
    missing:
      - "Replace self._whisper_client.close() with await self._whisper_client.aclose() in main.py Orchestrator.stop()"
      - "Replace await asyncio.to_thread(self._whisper_client.is_available) with await self._whisper_client.is_available() in main.py _check_whisper_health()"
      - "Replace _whisper_client.close() with await _whisper_client.aclose() in server.py lifespan shutdown"
---

# Phase 03: Whisper Consolidation Verification Report

**Phase Goal:** A single async WhisperClient with unified confidence scoring and retry logic replaces all three transcription implementations
**Verified:** 2026-03-26 (initial) · 2026-07-29 (re-verified)
**Status:** passed — all originally-failing consumer wiring resolved; see `## Post-hoc Resolution`
**Re-verification:** Yes — see `## Post-hoc Resolution` for current-code evidence

> **Reading this report:** the Observable Truths, Anti-Patterns, and Gaps Summary sections below
> record the state as of 2026-03-26 and are preserved unedited as history. Every FAIL and BLOCKER
> in them has since been fixed — the `## Post-hoc Resolution` section at the end maps each one to
> the current file:line that resolves it.

---

## Goal Achievement

### Observable Truths

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | A single async WhisperClient exists with persistent httpx.AsyncClient | VERIFIED | whisper_client.py:73 — `self._client = httpx.AsyncClient(timeout=self.timeout)` |
| 2 | Confidence scoring uses exp(avg_logprob) from verbose_json segments, falling back to 0.5 | VERIFIED | whisper_client.py:110 — `confidence = min(1.0, max(0.0, math.exp(avg_logprob)))` with 0.5 fallback at line 112 |
| 3 | Failed requests retry 3 times with exponential backoff; 4xx errors do not retry | VERIFIED | whisper_client.py:156–198 — loop over `_MAX_RETRIES`, break on 4xx, `asyncio.sleep` backoff |
| 4 | Client exposes transcribe() and transcribe_with_confidence() async methods | VERIFIED | whisper_client.py:131 `async def transcribe`, line 200 `async def transcribe_with_confidence` |
| 5 | Client has aclose() for lifecycle management following TTS pattern | VERIFIED (client) / FAILED (consumers) | aclose() exists at whisper_client.py:277; but main.py:166 calls `.close()` (AttributeError) and server.py:234 calls `.close()` (AttributeError) |
| 6 | VoiceInput.transcribe() delegates to the injected async WhisperClient instead of inline httpx | FAILED | voice.py:197 uses `asyncio.to_thread(self._whisper_client.transcribe, wav_bytes)` — transcribe() is async def; this passes the unawaited coroutine to a thread |
| 7 | Web server /api/transcribe and chat WS transcription use the shared WhisperClient | PARTIAL | WhisperClient is created and wired. However server.py:989 wraps the async transcribe_with_confidence() in asyncio.to_thread; server.py:291 wraps async is_available() in asyncio.to_thread |
| 8 | No inline httpx Whisper calls remain in voice.py or web/server.py | VERIFIED | No `httpx.AsyncClient` Whisper calls in voice.py or server.py; httpx in voice.py is ElevenLabs TTS only |
| 9 | Whisper model defaults to large-v3-turbo in production docker-compose | VERIFIED | docker-compose.yml:26 `WHISPER__MODEL=${WHISPER_MODEL:-large-v3-turbo}`; config.py:62 `default="large-v3-turbo"` |

**Score:** 6/9 truths verified (3 failed or partial due to async/sync mismatch in consumer wiring)

---

## Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `orchestrator/orchestrator/whisper_client.py` | Async WhisperClient with retry, confidence, aclose | VERIFIED | 286 lines; fully async; exports WhisperClient, TranscriptionResult, WhisperClientError |
| `orchestrator/tests/test_whisper_client.py` | Async tests for WhisperClient, min 200 lines | VERIFIED | 578 lines; 35 tests; all use pytest.mark.asyncio |
| `orchestrator/orchestrator/voice.py` | VoiceInput using injected WhisperClient | STUB | Accepts WhisperClient via constructor (correct) but calls it as if sync via asyncio.to_thread |
| `web/server.py` | Web server using WhisperClient from lifespan | STUB | Creates WhisperClient in lifespan (correct) but calls async methods as sync; uses non-existent .close() |
| `orchestrator/orchestrator/main.py` | Orchestrator creating and injecting WhisperClient | STUB | Creates and injects correctly; health check and shutdown use wrong call patterns |
| `docker-compose.yml` | Whisper model set to large-v3-turbo | VERIFIED | Line 26: `WHISPER__MODEL=${WHISPER_MODEL:-large-v3-turbo}` |

---

## Key Link Verification

| From | To | Via | Status | Details |
|------|----|-----|--------|---------|
| `whisper_client.py` | `/v1/audio/transcriptions` | httpx.AsyncClient.post | WIRED | Line 152: `url = f"{self.base_url}/v1/audio/transcriptions"`, line 158: `await self._client.post(url, ...)` |
| `whisper_client.py` | `audio_processing.py` | AVIATION_PROMPT import | WIRED | Line 18: `from .audio_processing import AVIATION_PROMPT` |
| `main.py` | `whisper_client.py` | WhisperClient constructor + injection into VoiceInput | WIRED (construction) / BROKEN (lifecycle) | Lines 54-61: creates WhisperClient and injects into VoiceInput correctly. Line 166: `self._whisper_client.close()` — AttributeError at shutdown |
| `voice.py` | `whisper_client.py` | self._whisper_client.transcribe | BROKEN | Line 197: `asyncio.to_thread(self._whisper_client.transcribe, wav_bytes)` — async method passed to thread pool; coroutine never executes |
| `web/server.py` | `whisper_client.py` | WhisperClient created in lifespan, used in routes | BROKEN | Lines 197-200: creation correct. Line 989: `asyncio.to_thread(_whisper_client.transcribe_with_confidence, ...)` — async method called as sync. Line 234: `.close()` does not exist |

---

## Data-Flow Trace (Level 4)

| Artifact | Data Variable | Source | Produces Real Data | Status |
|----------|---------------|--------|--------------------|--------|
| `voice.py` VoiceInput.transcribe() | `text` (return value) | `asyncio.to_thread(self._whisper_client.transcribe, wav_bytes)` | No — coroutine object passed to thread, not executed | HOLLOW — call site broken |
| `web/server.py` _transcribe_with_confidence() | `result` (TranscriptionResult) | `asyncio.to_thread(_whisper_client.transcribe_with_confidence, audio_bytes)` | No — async method not awaited correctly | HOLLOW — call site broken |

**Root cause:** All three async method calls in consumers (`transcribe`, `transcribe_with_confidence`, `is_available`) are wrapped in `asyncio.to_thread()`. This pattern is correct for *sync* callables. For *async* callables, it passes the coroutine object itself as the callable to the thread, which does not execute the coroutine. The WhisperClient methods are all `async def`.

---

## Behavioral Spot-Checks

| Behavior | Command | Result | Status |
|----------|---------|--------|--------|
| WhisperClient unit tests pass | `python3 -m pytest tests/test_whisper_client.py -q` | 35 passed in 0.62s | PASS |
| Full orchestrator test suite passes | `python3 -m pytest tests/ -q` | 390 passed in 2.49s | PASS |
| WhisperClient imports correctly | import check | TranscriptionResult, WhisperClient, WhisperClientError all importable | PASS |
| voice.py Whisper call is correctly async | inspect voice.py:197 | `asyncio.to_thread(self._whisper_client.transcribe, wav_bytes)` — transcribe is async def | FAIL (runtime breakage) |
| server.py Whisper shutdown uses aclose | inspect server.py:234 | `_whisper_client.close()` — method does not exist | FAIL (AttributeError on shutdown) |

Note: Tests pass because they test WhisperClient in isolation. The broken consumer wiring is not covered by the test suite.

---

## Requirements Coverage

| Requirement | Source Plan | Description | Status | Evidence |
|-------------|-------------|-------------|--------|----------|
| WHSP-01 | 03-01 | Single async WhisperClient replaces three separate transcription implementations | SATISFIED | whisper_client.py is fully async; no other transcription implementations found in voice.py or server.py |
| WHSP-02 | 03-01 | Confidence scoring logic unified across all call sites | SATISFIED | exp(avg_logprob) formula implemented in WhisperClient._parse_verbose_response(); all confidence scoring routes through this single method |
| WHSP-03 | 03-01 | Retry logic available in the shared client | SATISFIED | 3-retry loop with exponential backoff in both transcribe() and transcribe_with_confidence(); no retry on 4xx |
| WHSP-04 | 03-02 | Web server and voice module both use the shared async WhisperClient | BLOCKED | Both consumers import and instantiate WhisperClient. However, they call async methods via asyncio.to_thread (which does not work for async callables) and call non-existent .close() on shutdown. The integration is structurally present but functionally broken at runtime. |

All four requirement IDs declared in the plans appear in REQUIREMENTS.md Phase 3 mapping. No orphaned requirements.

---

## Anti-Patterns Found

| File | Line | Pattern | Severity | Impact |
|------|------|---------|----------|--------|
| `orchestrator/orchestrator/voice.py` | 197 | `asyncio.to_thread(self._whisper_client.transcribe, wav_bytes)` — async method called as sync callable | Blocker | Voice transcription silently broken; coroutine object is passed to thread pool instead of being awaited |
| `orchestrator/orchestrator/main.py` | 166 | `self._whisper_client.close()` — non-existent method | Blocker | AttributeError raised on every clean Orchestrator.stop(); could mask other shutdown errors |
| `orchestrator/orchestrator/main.py` | 176 | `await asyncio.to_thread(self._whisper_client.is_available)` — async method called as sync | Blocker | Health check passes coroutine object to thread; whisper health status always wrong |
| `web/server.py` | 234 | `_whisper_client.close()` — non-existent method | Blocker | AttributeError on every web server shutdown |
| `web/server.py` | 989–991 | `asyncio.to_thread(_whisper_client.transcribe_with_confidence, audio_bytes)` — async method called as sync | Blocker | Web transcription (/api/transcribe and /ws/chat audio) broken at runtime |
| `web/server.py` | 291 | `await asyncio.to_thread(_whisper_client.is_available)` — async method called as sync | Warning | Status endpoint Whisper health check broken |

**Root cause of all consumer bugs:** The Plan 02 SUMMARY documents a deviation: "Sync WhisperClient bridged to async via asyncio.to_thread() since Plan 01 implemented sync httpx.Client." However, Plan 01 actually produced a fully async WhisperClient (as specified). The consumers were written for a sync client that does not exist, using asyncio.to_thread as a bridge — but then Plan 01 correctly delivered async methods. The bridge pattern was applied to already-async methods, breaking the calls.

---

## Human Verification Required

No human verification required for these gaps — all failures are code defects verifiable programmatically. The fixes are mechanical:

1. Replace all `asyncio.to_thread(self._whisper_client.transcribe, ...)` with `await self._whisper_client.transcribe(...)`
2. Replace all `asyncio.to_thread(self._whisper_client.is_available)` with `await self._whisper_client.is_available()`
3. Replace all `asyncio.to_thread(_whisper_client.transcribe_with_confidence, ...)` with `await _whisper_client.transcribe_with_confidence(...)`
4. Replace all `_whisper_client.close()` / `self._whisper_client.close()` with `await _whisper_client.aclose()` / `await self._whisper_client.aclose()`

---

## Gaps Summary

Three truths fail due to a single root cause: the consumer wiring (voice.py, main.py, web/server.py) was written assuming WhisperClient methods are synchronous callables, then wrapped in `asyncio.to_thread()` to bridge them to async contexts. But Plan 01 delivered a fully async WhisperClient — all methods are `async def`. Wrapping an async method in `asyncio.to_thread` passes the coroutine function as a callable, but when called in the thread it returns a coroutine object without executing it.

Concrete failures at runtime (not caught by existing tests because tests mock WhisperClient in isolation):
- **Voice transcription is broken**: `VoiceInput.transcribe()` returns a coroutine object or raises instead of the transcribed string
- **Web transcription is broken**: `_transcribe_with_confidence()` in server.py does not actually call `transcribe_with_confidence()`
- **Health checks are broken**: both `_check_whisper_health()` in main.py and `/api/status` in server.py use `asyncio.to_thread` on an async method
- **Shutdown crashes**: both `Orchestrator.stop()` and the server.py lifespan call `_whisper_client.close()` which does not exist; `aclose()` is the correct method

The WhisperClient itself (Plan 01) is fully correct and all 35 unit tests pass. The model upgrade (docker-compose, config.py, .env.example) is fully correct. Only the consumer wiring in Plan 02 is broken.

---

_Verified: 2026-03-26_
_Verifier: Claude (gsd-verifier)_

---

## Post-hoc Resolution

_Added: 2026-04-18 during /gsd-next spot-check before v1.2 milestone close-out._

All four FAIL items above were fixed in subsequent work (likely during Phase 04/05 and the `8587ba5 fix: unblock python CI + close out v1.2 (#71)` commit). Current codebase evidence:

| Original FAIL | Current Resolution | Status |
|---|---|---|
| `voice.py:197` — `asyncio.to_thread(self._whisper_client.transcribe, wav_bytes)` on async def | `orchestrator/orchestrator/voice.py:184` — `text = await self._whisper_client.transcribe(wav_bytes)` | RESOLVED |
| `main.py:166` — `_whisper_client.close()` (AttributeError) | `orchestrator/orchestrator/main.py:148` — `await self._whisper_client.aclose()` | RESOLVED |
| `server.py:234` — `_whisper_client.close()` (AttributeError) | `web/server.py:279` — `await state.whisper_client.aclose()` | RESOLVED |
| `_transcribe_with_confidence()` in server.py does not call `transcribe_with_confidence()` | `web/server.py:1272` — `result = await state.whisper_client.transcribe_with_confidence(...)` | RESOLVED |

**Override:** These FAILs are superseded by current-code verification. No outstanding Phase 03 verification gaps remain.

### Re-verification: 2026-07-29

_Added during /gsd-extract-learnings follow-up. Frontmatter `status` flipped `gaps_found` → `passed`._

The 2026-04-18 spot-check listed four items. The original report's **Anti-Patterns Found** table
actually recorded **six** defects — it also flagged `is_available()` being wrapped in
`asyncio.to_thread` at `main.py:176` and `server.py:291`. All six were re-checked against the
current codebase:

| # | Original defect | Current code | Status |
|---|---|---|---|
| 1 | `voice.py:197` — `asyncio.to_thread(...transcribe, wav_bytes)` on an `async def` | `orchestrator/orchestrator/voice.py:184` — `await self._whisper_client.transcribe(wav_bytes)` | RESOLVED |
| 2 | `main.py:166` — `_whisper_client.close()` (AttributeError) | `orchestrator/orchestrator/main.py:148` — `await self._whisper_client.aclose()` | RESOLVED |
| 3 | `main.py:176` — `await asyncio.to_thread(...is_available)` on an `async def` | `orchestrator/orchestrator/main.py:158` — `available = await self._whisper_client.is_available()` | RESOLVED |
| 4 | `server.py:234` — `_whisper_client.close()` (AttributeError) | `web/server.py:279` — `await state.whisper_client.aclose()` | RESOLVED |
| 5 | `server.py:291` — `await asyncio.to_thread(...is_available)` on an `async def` | `web/server.py:349` — `whisper_ok = await state.whisper_client.is_available()` | RESOLVED |
| 6 | `server.py:989` — `asyncio.to_thread(...transcribe_with_confidence, audio_bytes)` | `web/server.py:1272` — `await state.whisper_client.transcribe_with_confidence(...)` | RESOLVED |

Negative check: `grep -rn "to_thread.*whisper\|whisper.*to_thread" orchestrator/ web/` returns zero
matches — no `asyncio.to_thread` wrapper on any WhisperClient method remains anywhere in the tree.

**Score reconciliation:** three Observable Truths (5, 6, 7) were scored FAILED or PARTIAL solely
because of these six call-site defects. With all six resolved, the score is 9/9. Frontmatter
`gaps:` is now `[]`; the original entries are preserved under `resolved_gaps:` so the history
survives without tooling reading the phase as blocked.
