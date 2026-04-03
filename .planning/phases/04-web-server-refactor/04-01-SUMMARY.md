---
phase: 04-web-server-refactor
plan: 01
subsystem: web-server
tags: [refactor, dependency-injection, fastapi, state-management]
dependency_graph:
  requires: []
  provides: [app-state-di, testable-web-server]
  affects: [web/server.py]
tech_stack:
  added: []
  patterns: [FastAPI Depends(), dataclass AppState, lifespan state management]
key_files:
  created: []
  modified:
    - web/server.py
decisions:
  - AppState dataclass with 11 fields replaces all module-level mutable state
  - settings included in AppState for Phase 5 testability (module-level kept for early logging)
  - whisper_client stored as httpx.AsyncClient (not WhisperClient) matching existing REST pattern
  - _on_state callback parameter renamed to sim_state to avoid shadowing AppState variable
metrics:
  duration: 5min
  completed: "2026-03-28T01:54:00Z"
  tasks: 2
  files: 1
---

# Phase 04 Plan 01: Web Server State Refactor Summary

AppState dataclass with DI via FastAPI Depends() replaces all 11 module-level mutable globals in web/server.py

## What Was Done

### Task 1: Define AppState dataclass, get_app_state dependency, and refactor lifespan
**Commit:** 4547ee6

- Defined `@dataclass class AppState` with 11 fields: settings, sim_client, claude_client, context_store, phase_detector, whisper_client, tts_client, tts_cache, sim_connected, bridge_last_seen, bridge_connected
- Added `get_app_state(request: Request) -> AppState` dependency callable returning `request.app.state.app_state`
- Refactored lifespan to create AppState instance, populate all fields, and assign to `app.state.app_state`
- Removed all 11 module-level mutable variables
- Removed `_get_tts_client()` and `_get_whisper_client()` helper functions
- Removed all `global` statements (3 sites)
- Updated `_prepopulate_tts_cache()` to accept `state: AppState` parameter
- Created `whisper_client` and `tts_client` as `httpx.AsyncClient(timeout=30.0)` in lifespan

### Task 2: Wire all route handlers and helpers to use AppState
**Commit:** 2d5077e

- Updated 5 route handlers with `Depends(get_app_state)`: get_status, transcribe_audio, text_to_speech, ws_telemetry, ws_chat
- Updated 7 helper functions with `state: AppState` parameter: _stream_response, _tts_websocket_stream, _tts_rest_fallback, _send_tts_chunk_rest, _transcribe_with_confidence, _transcribe_audio_bytes_with_confidence, _prepopulate_tts_cache
- Replaced all ~40 former global references with `state.X` access
- Barge-in cancellation closure (`_cancel_active_response`) unchanged -- only references local variables
- Added None checks for tts_client and whisper_client where bare globals were previously used

## Deviations from Plan

None -- plan executed exactly as written.

## Verification Results

| Check | Result |
|-------|--------|
| `python -c "import ast; ast.parse(...)"` | Syntax OK |
| `ruff check web/server.py` | All checks passed |
| `grep -c "global " web/server.py` | 0 |
| `grep -c "Depends(get_app_state)" web/server.py` | 5 |
| `grep -c "class AppState" web/server.py` | 1 |
| `grep -c "app.state.app_state" web/server.py` | 2 |
| `ruff format web/server.py` | Clean |

## Known Stubs

None -- all state fields are wired to real implementations.

## Self-Check: PASSED

- web/server.py: FOUND
- Commit 4547ee6: FOUND
- Commit 2d5077e: FOUND
