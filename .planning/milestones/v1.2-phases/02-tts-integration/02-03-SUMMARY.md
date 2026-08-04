---
phase: 02-tts-integration
plan: 03
subsystem: tts
tags: [elevenlabs, websocket, streaming, kokoro, tts-protocol]

requires:
  - phase: 02-tts-integration plan 01
    provides: TTSClient protocol with synthesize/synthesize_stream/aclose
  - phase: 02-tts-integration plan 02
    provides: Web server and VoiceOutput wired to TTSClient for REST TTS
provides:
  - synthesize_ws_stream() on TTSClient protocol for incremental WebSocket streaming
  - ElevenLabs WebSocket stream-input implementation with concurrent send/receive
  - Kokoro sentence-boundary buffering fallback for synthesize_ws_stream
  - Web server chat TTS fully backend-agnostic via TTSClient protocol
affects: [web-server, voice, tts]

tech-stack:
  added: []
  patterns:
    - "Queue-to-AsyncIterator bridge for adapting chat sentence queues to TTSClient streaming"
    - "Cache-aware TTS streaming: phrase cache checked before delegating to backend"

key-files:
  created: []
  modified:
    - orchestrator/orchestrator/tts/base.py
    - orchestrator/orchestrator/tts/elevenlabs.py
    - orchestrator/orchestrator/tts/kokoro.py
    - web/server.py

key-decisions:
  - "ElevenLabs WS streaming uses asyncio.Queue for concurrent send/receive instead of sequential pattern"
  - "Phrase cache remains in web server layer, checked before uncached text reaches TTSClient"
  - "Kokoro fallback buffers to sentence boundaries using rfind on .!?\\n characters"

patterns-established:
  - "TTSClient.synthesize_ws_stream() pattern: AsyncIterator[str] in, AsyncIterator[bytes] out"
  - "Queue-to-iterator adapter pattern for bridging asyncio.Queue to Protocol methods"

requirements-completed: [TTS-03]

duration: 4min
completed: 2026-03-27
---

# Phase 02 Plan 03: WebSocket Streaming TTS via Protocol Summary

**synthesize_ws_stream() added to TTSClient protocol with ElevenLabs WebSocket and Kokoro sentence-buffering implementations, replacing 120 lines of inline ElevenLabs code in web server**

## Performance

- **Duration:** 4 min
- **Started:** 2026-03-27T15:55:00Z
- **Completed:** 2026-03-27T15:59:00Z
- **Tasks:** 2
- **Files modified:** 4

## Accomplishments
- Added synthesize_ws_stream(AsyncIterator[str]) -> AsyncIterator[bytes] to TTSClient protocol
- ElevenLabsClient implements native WebSocket streaming with concurrent send/receive, base64 audio decoding, and flush signal
- KokoroClient implements sentence-boundary buffering fallback via synthesize_stream
- Web server chat TTS replaced ~120 lines of inline ElevenLabs WebSocket code with TTSClient protocol call
- All ElevenLabs-specific URLs, voice_settings, and WebSocket protocol handling removed from server.py
- Phrase cache integration preserved via cache-aware queue-to-iterator bridge

## Task Commits

Each task was committed atomically:

1. **Task 1: Add synthesize_ws_stream to protocol and implement in both backends** - `06c622d` (feat)
2. **Task 2: Wire web server to use TTSClient.synthesize_ws_stream for chat TTS** - `ebe3550` (feat)

## Files Created/Modified
- `orchestrator/orchestrator/tts/base.py` - Added synthesize_ws_stream to Protocol definition
- `orchestrator/orchestrator/tts/elevenlabs.py` - WebSocket stream-input implementation with concurrent send/receive
- `orchestrator/orchestrator/tts/kokoro.py` - Sentence-boundary buffering fallback
- `web/server.py` - Replaced inline ElevenLabs WS code with TTSClient.synthesize_ws_stream()

## Decisions Made
- ElevenLabs WebSocket streaming uses asyncio.Queue[bytes|None] to decouple the receiver task from the yielding coroutine, matching the existing codebase pattern
- Phrase cache checking stays in the web server's queue-to-iterator bridge rather than in the TTSClient, per D-08 (server caches, client synthesizes)
- Kokoro sentence buffering uses rfind on ".!?\n" characters with greedy boundary detection

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Fixed ruff UP041 lint error for asyncio.TimeoutError**
- **Found during:** Task 1
- **Issue:** ruff requires `TimeoutError` instead of `asyncio.TimeoutError` (UP041 rule)
- **Fix:** Changed `asyncio.TimeoutError` to `TimeoutError` in elevenlabs.py
- **Files modified:** orchestrator/orchestrator/tts/elevenlabs.py
- **Verification:** ruff check passes
- **Committed in:** 06c622d (Task 1 commit)

---

**Total deviations:** 1 auto-fixed (1 bug)
**Impact on plan:** Minor lint fix, no scope change.

## Issues Encountered
None

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- TTS protocol is now complete: synthesize, synthesize_stream, synthesize_ws_stream, aclose
- Web server is fully backend-agnostic for TTS -- switching tts_backend config switches all synthesis paths
- Phase 02 (tts-integration) is complete with all three plans executed

---
*Phase: 02-tts-integration*
*Completed: 2026-03-27*
