---
phase: 03-whisper-consolidation
plan: 01
subsystem: stt
tags: [whisper, httpx, async, faster-whisper, transcription, confidence-scoring]

# Dependency graph
requires:
  - phase: 02-tts-integration
    provides: "TTSClient lifecycle pattern (aclose) used as reference"
provides:
  - "Async WhisperClient with persistent httpx.AsyncClient"
  - "Unified confidence scoring via exp(avg_logprob)"
  - "Retry logic with exponential backoff (no retry on 4xx)"
  - "aclose() lifecycle and async context manager"
affects: [03-02-whisper-consumer-wiring, web-server]

# Tech tracking
tech-stack:
  added: []
  patterns: ["Async HTTP client with persistent connection for STT (mirrors TTS pattern)"]

key-files:
  created: []
  modified:
    - orchestrator/orchestrator/whisper_client.py
    - orchestrator/tests/test_whisper_client.py

key-decisions:
  - "Followed TTS client lifecycle pattern: persistent httpx.AsyncClient + aclose()"
  - "Kept identical confidence formula: exp(avg_logprob) averaged across segments, 0.5 fallback"

patterns-established:
  - "Async client lifecycle: __init__ creates persistent httpx.AsyncClient, aclose() tears it down"
  - "Retry with asyncio.sleep backoff: 1.5*attempt seconds, skip 4xx, retry 5xx/timeout/connect"

requirements-completed: [WHSP-01, WHSP-02, WHSP-03]

# Metrics
duration: 2min
completed: 2026-03-27
---

# Phase 03 Plan 01: Async WhisperClient Summary

**Async WhisperClient with persistent httpx.AsyncClient, exp(avg_logprob) confidence scoring, and exponential backoff retry**

## Performance

- **Duration:** 2 min
- **Started:** 2026-03-27T21:41:05Z
- **Completed:** 2026-03-27T21:43:43Z
- **Tasks:** 1
- **Files modified:** 2

## Accomplishments
- Rewrote WhisperClient from sync httpx.Client to async httpx.AsyncClient with persistent connection
- Converted all public methods (transcribe, transcribe_with_confidence, is_available) to async
- Added aclose() lifecycle and __aenter__/__aexit__ async context manager (matching TTS pattern)
- Replaced time.sleep with asyncio.sleep in retry loops
- Maintained 35 tests, all converted to async with pytest.mark.asyncio

## Task Commits

Each task was committed atomically:

1. **Task 1: Rewrite WhisperClient as async with persistent httpx.AsyncClient**
   - `5ec90f6` (test) - Add failing async tests for WhisperClient (TDD RED)
   - `ee5314c` (feat) - Rewrite WhisperClient as async with persistent httpx.AsyncClient (TDD GREEN)

## Files Created/Modified
- `orchestrator/orchestrator/whisper_client.py` - Async WhisperClient with persistent httpx.AsyncClient, retry, confidence scoring, aclose lifecycle
- `orchestrator/tests/test_whisper_client.py` - 35 async tests covering constructor, transcribe, confidence, retry, 4xx/5xx, timeout, health, aclose, context manager

## Decisions Made
- Followed TTS client lifecycle pattern: persistent httpx.AsyncClient created in __init__, aclose() for teardown
- Kept identical confidence formula: exp(avg_logprob) averaged across segments, 0.5 fallback when no segments
- Removed all sync references (httpx.Client, time.sleep, __enter__/__exit__) -- clean async-only API

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered
None

## User Setup Required
None - no external service configuration required.

## Known Stubs
None - all functionality is fully implemented.

## Next Phase Readiness
- Async WhisperClient ready for Plan 02 consumer wiring (voice.py, web server)
- aclose() lifecycle enables proper cleanup in orchestrator shutdown
- No backward-compatible sync API retained -- consumers must be updated in Plan 02

---
*Phase: 03-whisper-consolidation*
*Completed: 2026-03-27*
