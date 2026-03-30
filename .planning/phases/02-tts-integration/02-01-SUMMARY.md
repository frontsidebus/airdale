---
phase: 02-tts-integration
plan: 01
subsystem: tts
tags: [elevenlabs, kokoro, httpx, pydantic-settings, tts]

# Dependency graph
requires: []
provides:
  - TTS config fields (tts_backend, tts_stability, tts_similarity_boost, tts_style, tts_local_url, tts_voice_id_local)
  - TTSClient protocol with aclose() lifecycle method
  - Persistent httpx clients in ElevenLabsClient and KokoroClient
  - Voice settings injection via factory
affects: [02-tts-integration, web-server]

# Tech tracking
tech-stack:
  added: []
  patterns: [persistent-httpx-client, protocol-with-lifecycle, config-driven-voice-settings]

key-files:
  created:
    - orchestrator/orchestrator/tts/base.py
    - orchestrator/orchestrator/tts/elevenlabs.py
    - orchestrator/orchestrator/tts/kokoro.py
    - orchestrator/orchestrator/tts/__init__.py
    - orchestrator/tests/test_tts_client.py
  modified:
    - orchestrator/orchestrator/config.py
    - .env.example

key-decisions:
  - "Persistent httpx.AsyncClient per TTS backend eliminates per-call TCP overhead"
  - "Voice settings (stability, similarity_boost, style) flow from config through factory to ElevenLabsClient constructor"

patterns-established:
  - "Persistent HTTP client pattern: create in __init__, close via aclose()"
  - "Backend-aware config properties: voice_id and tts_configured switch on tts_backend"

requirements-completed: [TTS-04, TTS-05, TTS-06, TTS-07]

# Metrics
duration: 4min
completed: 2026-03-27
---

# Phase 02 Plan 01: TTS Config & Backend Refactor Summary

**TTS config fields with backend-aware voice_id, persistent httpx clients in both ElevenLabs and Kokoro backends, and aclose() lifecycle method on TTSClient protocol**

## Performance

- **Duration:** 4 min
- **Started:** 2026-03-27T15:39:54Z
- **Completed:** 2026-03-27T15:44:35Z
- **Tasks:** 2
- **Files modified:** 7

## Accomplishments
- Added 6 TTS config fields to Settings with correct defaults (stability=0.75, similarity_boost=0.80, style=0.15)
- Refactored both TTS backends to use persistent httpx.AsyncClient (no per-call creation)
- Added aclose() to TTSClient protocol for lifecycle management
- Factory passes voice settings from config to ElevenLabsClient

## Task Commits

Each task was committed atomically:

1. **Task 1: Add TTS config fields to Settings and update .env.example** - `c3d7992` (feat)
2. **Task 2: Refactor TTS backends with persistent client, voice settings, aclose** - `fbdba2d` (feat)

## Files Created/Modified
- `orchestrator/orchestrator/config.py` - Added 6 TTS fields, tts_configured property, backend-aware voice_id
- `.env.example` - Documented all new TTS fields in new section
- `orchestrator/orchestrator/tts/base.py` - Added aclose() to TTSClient protocol
- `orchestrator/orchestrator/tts/elevenlabs.py` - Persistent httpx, configurable voice settings, aclose()
- `orchestrator/orchestrator/tts/kokoro.py` - Persistent httpx, aclose()
- `orchestrator/orchestrator/tts/__init__.py` - Factory passes voice settings to ElevenLabsClient
- `orchestrator/tests/test_tts_client.py` - Updated mocking for persistent client pattern

## Decisions Made
- Persistent httpx.AsyncClient per TTS backend eliminates per-call TCP overhead
- Voice settings flow from config through factory -- no hardcoded values in backends
- Test mocking updated to patch client._http directly instead of context manager pattern

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered
None

## User Setup Required
None - no external service configuration required. Existing .env files continue to work with defaults.

## Next Phase Readiness
- TTS config and backend refactoring complete
- Ready for web server TTS integration (02-02) and CLI voice module integration (02-03)
- All 20 TTS tests passing

## Known Stubs
None - all config fields have proper defaults, all methods are fully implemented.

---
*Phase: 02-tts-integration*
*Completed: 2026-03-27*
