---
phase: 02-tts-integration
plan: 02
subsystem: tts
tags: [elevenlabs, tts, voice, fastapi, refactor]

# Dependency graph
requires:
  - phase: 02-tts-integration/01
    provides: TTSClient protocol, create_tts_client factory, ElevenLabsClient, KokoroClient
provides:
  - VoiceOutput wired to TTSClient (CLI voice module)
  - Web server /api/tts endpoint using TTSClient
  - Web server phrase cache using TTSClient.synthesize()
  - Web server lifespan managing TTSClient lifecycle
  - main.py creating TTSClient via factory
affects: [02-tts-integration/03, web-server-refactor]

# Tech tracking
tech-stack:
  added: []
  patterns: [consumer-delegates-to-protocol, factory-based-dependency-injection]

key-files:
  created: []
  modified:
    - orchestrator/orchestrator/voice.py
    - orchestrator/orchestrator/main.py
    - web/server.py

key-decisions:
  - "VoiceOutput no longer checks api_key/voice_id guards; TTSClient encapsulates readiness"
  - "Web server uses _tts_client_instance module global instead of app.state for consistency with existing patterns"
  - "TTS warmup (pre-flight HEAD request) removed; persistent httpx client in TTSClient handles connection reuse"
  - "Status endpoint uses settings.tts_configured property for backend-agnostic TTS detection"

patterns-established:
  - "Consumer delegation: consumers call TTSClient.synthesize() instead of inline httpx"
  - "Factory injection: create_tts_client(settings) at startup, passed to consumers"
  - "Lifecycle management: TTSClient.aclose() called in shutdown paths"

requirements-completed: [TTS-01, TTS-02]

# Metrics
duration: 4min
completed: 2026-03-27
---

# Phase 02 Plan 02: TTS Consumer Wiring Summary

**CLI VoiceOutput and web server REST TTS paths refactored to delegate to TTSClient protocol, eliminating 4 hardcoded voice_settings dicts and all inline ElevenLabs httpx calls from consumers**

## Performance

- **Duration:** 4 min
- **Started:** 2026-03-27T15:47:30Z
- **Completed:** 2026-03-27T15:51:38Z
- **Tasks:** 2
- **Files modified:** 3

## Accomplishments
- VoiceOutput accepts TTSClient in constructor, _synthesize delegates to protocol
- Web server /api/tts and REST fallback use TTSClient.synthesize() with dynamic content type
- Phrase cache pre-population uses TTSClient instead of inline httpx with hardcoded settings
- All 4 hardcoded voice_settings dicts removed from REST TTS paths (1 remains in WebSocket streaming for Plan 03)
- TTSClient lifecycle managed in both orchestrator.stop() and web server lifespan teardown

## Task Commits

Each task was committed atomically:

1. **Task 1: Refactor VoiceOutput to accept TTSClient and update main.py** - `c5a4154` (feat)
2. **Task 2: Wire web server to use TTSClient for /api/tts and phrase cache** - `76c46c4` (feat)

## Files Created/Modified
- `orchestrator/orchestrator/voice.py` - VoiceOutput refactored: constructor accepts TTSClient, _synthesize delegates to protocol, removed inline httpx TTS calls and hardcoded settings
- `orchestrator/orchestrator/main.py` - Creates TTSClient via factory, passes to VoiceOutput, closes on shutdown, uses tts_configured property
- `web/server.py` - TTSClient created in lifespan, /api/tts uses synthesize(), phrase cache uses synthesize(), _get_tts_client() removed, REST voice_settings removed

## Decisions Made
- Kept httpx import in voice.py because VoiceInput.transcribe still uses it for Whisper (only TTS httpx usage was removed)
- Used module-level `_tts_client_instance` global in server.py rather than `app.state` to match the existing pattern for other globals (sim_client, claude_client, etc.)
- Removed the TTS warmup task from _stream_response since the TTSClient already uses a persistent httpx.AsyncClient
- Changed tts_enabled checks from raw key inspection to `settings.tts_configured` / `_tts_client_instance is not None`

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered
- Pre-existing SIM105 ruff warning in main.py (contextlib.suppress suggestion) -- out of scope, not caused by our changes.

## User Setup Required
None - no external service configuration required.

## Known Stubs
None - all TTS paths are fully wired to TTSClient.

## Next Phase Readiness
- WebSocket streaming TTS (`_tts_websocket_stream`) still uses inline ElevenLabs WebSocket API with hardcoded voice_settings -- ready for Plan 03
- Both CLI and web server REST TTS paths are fully abstracted

---
*Phase: 02-tts-integration*
*Completed: 2026-03-27*
