---
phase: 03-whisper-consolidation
plan: 02
subsystem: orchestrator, web
tags: [whisper, stt, consolidation, dependency-injection, model-upgrade]
dependency_graph:
  requires: [03-01]
  provides: [unified-whisper-transcription, large-v3-turbo-default]
  affects: [voice-pipeline, web-transcription, docker-config]
tech_stack:
  added: []
  patterns: [dependency-injection, asyncio-to-thread-bridge]
key_files:
  created: []
  modified:
    - orchestrator/orchestrator/voice.py
    - orchestrator/orchestrator/main.py
    - web/server.py
    - docker-compose.yml
    - docker-compose.dev.yml
    - .env.example
    - orchestrator/orchestrator/config.py
    - orchestrator/tests/test_config.py
decisions:
  - "Sync WhisperClient bridged to async via asyncio.to_thread() since Plan 01 implemented sync httpx.Client"
  - "httpx import retained in voice.py because VoiceOutput._synthesize still uses it for TTS"
  - "WhisperClient._DEFAULT_MODEL left as 'medium' (client fallback) while config.py default updated to large-v3-turbo"
metrics:
  duration: 4min
  completed: "2026-03-27T21:50:29Z"
  tasks_completed: 3
  tasks_total: 3
  files_modified: 8
  tests_passed: 370
requirements:
  - WHSP-04
---

# Phase 03 Plan 02: Wire WhisperClient into Consumers and Upgrade Model Summary

Unified all transcription through WhisperClient with dependency injection into both VoiceInput and web server, eliminating divergent inline httpx Whisper implementations and upgrading the default model to large-v3-turbo.

## What Changed

### Task 1: Wire WhisperClient into VoiceInput and Orchestrator (05c67f9)
- Changed `VoiceInput.__init__` to accept `whisper_client: WhisperClient` instead of `whisper_url: str`
- Rewrote `VoiceInput.transcribe()` to delegate to `WhisperClient.transcribe()` via `asyncio.to_thread()` after audio preprocessing
- Orchestrator creates `WhisperClient(base_url=settings.whisper_url, model=settings.whisper_model)` and injects into VoiceInput
- Health check now uses `WhisperClient.is_available()` instead of ad-hoc httpx GET to `/docs`
- Lifecycle cleanup calls `whisper_client.close()` on shutdown
- Removed `AVIATION_PROMPT` import from voice.py (handled by WhisperClient internally)

### Task 2: Wire WhisperClient into Web Server (fbf252e)
- Replaced `_whisper_client: httpx.AsyncClient` global with `_whisper_client: WhisperClient`
- Deleted `_get_whisper_client()` helper function entirely
- WhisperClient created in lifespan, closed on shutdown
- Rewrote `_transcribe_with_confidence()` to delegate to `WhisperClient.transcribe_with_confidence()`
- Status endpoint uses `WhisperClient.is_available()` for health checks
- Removed unused `math` and `AVIATION_PROMPT` imports

### Task 3: Upgrade Whisper Model to large-v3-turbo (9bdfc3f)
- Production docker-compose.yml: `WHISPER__MODEL` default changed from `medium` to `large-v3-turbo`
- Dev docker-compose.dev.yml: tiny override preserved with comment referencing production default
- .env.example: documents new model options and large-v3-turbo recommendation
- config.py: `whisper_model` default updated from `medium` to `large-v3-turbo`
- Updated test assertion for new default value

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Sync WhisperClient bridged to async via asyncio.to_thread**
- **Found during:** Task 1
- **Issue:** Plan interfaces described async methods (`async def transcribe`, `async def aclose`), but the actual WhisperClient from Plan 01 uses synchronous `httpx.Client` with blocking `time.sleep` retries
- **Fix:** Wrapped all WhisperClient calls in `asyncio.to_thread()` to avoid blocking the event loop, used `close()` instead of `aclose()`
- **Files modified:** orchestrator/orchestrator/voice.py, orchestrator/orchestrator/main.py, web/server.py

**2. [Rule 1 - Bug] Updated test for new config default**
- **Found during:** Task 3
- **Issue:** `test_default_whisper_model` asserted `whisper_model == "medium"` which fails after config change
- **Fix:** Updated assertion to `"large-v3-turbo"`
- **Files modified:** orchestrator/tests/test_config.py
- **Commit:** 9bdfc3f

## Decisions Made

1. **asyncio.to_thread bridge pattern** -- Since WhisperClient uses sync httpx with blocking retries (time.sleep), all async callers use `asyncio.to_thread()` to run transcription off the event loop. This is the standard Python pattern for sync-to-async bridging.

2. **httpx retained in voice.py** -- The `import httpx` stays because `VoiceOutput._synthesize()` still uses `httpx.AsyncClient` for ElevenLabs TTS. Only the Whisper-related httpx code was removed.

3. **WhisperClient default model unchanged** -- Left `_DEFAULT_MODEL = "medium"` in whisper_client.py as a safe fallback for standalone usage. The config.py default (large-v3-turbo) is what's actually passed in production.

## Known Stubs

None -- all transcription paths are fully wired to WhisperClient.

## Self-Check: PASSED
