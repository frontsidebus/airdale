# Phase 4: Web Server Refactor - Context

**Gathered:** 2026-03-27
**Status:** Ready for planning

<domain>
## Phase Boundary

Replace all module-level mutable state in `web/server.py` with a typed `AppState` dataclass on `app.state`, accessed via FastAPI `Depends()` in route handlers. Preserve identical runtime behavior — especially the barge-in cancellation flow. This refactor makes the web server testable (Phase 5 depends on it).

</domain>

<decisions>
## Implementation Decisions

### State Container
- **D-01:** Single `AppState` dataclass containing all mutable shared state. Fields include: `sim_client`, `claude_client`, `context_store`, `phase_detector`, `tts_client`, `whisper_client`, `tts_cache`, `sim_connected`, `bridge_last_seen`, `bridge_connected`, `settings`.
- **D-02:** `AppState` stored on `app.state.app_state` via lifespan. Accessed by route handlers via `Depends(get_app_state)`.
- **D-03:** Constants (`_LOW_CONFIDENCE_THRESHOLD`, `_POST_SPEECH_PAUSE_SECS`, `_CACHEABLE_PHRASES`, `_STATIC_DIR`) stay module-level — they are immutable and don't need injection.

### Dependency Injection
- **D-04:** Full DI for all route handlers — every route and WebSocket handler receives `AppState` via `Depends(get_app_state)`. No global access to mutable state anywhere.
- **D-05:** Internal helper functions (e.g., `_stream_response`, `_tts_stream_to_browser`, `_transcribe_with_confidence`) receive `AppState` as a parameter. They don't use `Depends()` — only route-level handlers do.
- **D-06:** `get_app_state(request: Request) -> AppState` is the single dependency callable. Returns `request.app.state.app_state`.

### Barge-in Preservation
- **D-07:** Minimal touch — pass `AppState` into barge-in functions as a parameter instead of accessing globals. Do NOT restructure the cancellation logic, task management, or event signaling. The proven behavior is preserved.
- **D-08:** Replace `nonlocal` references to global variables with `state.X` parameter access. Closure structure and cancellation flow stay identical.

### Bridge Connection Tracking
- **D-09:** `sim_connected: bool`, `bridge_last_seen: float`, and `bridge_connected: bool` become simple fields on `AppState`. No lock needed — asyncio is single-threaded, assignments are atomic.

### Lifespan Refactor
- **D-10:** Lifespan creates `AppState` instance, populates all fields, assigns to `app.state.app_state`. No more `global` statements.
- **D-11:** Lifespan cleanup calls `aclose()` on TTSClient and WhisperClient from the `AppState` instance.

### Globals to Remove
- **D-12:** These module-level variables must be completely removed (not just renamed):
  - `sim_client`, `claude_client`, `context_store`, `phase_detector`
  - `_sim_connected`, `_bridge_last_seen`, `_bridge_connected`
  - `_tts_client_instance`, `_whisper_client`
  - `_TTS_CACHE`
  - `_get_tts_client()` function (httpx wrapper — TTSClient handles this now)
  - `_get_whisper_client()` function (if still present)
  - All `global X` statements

### Claude's Discretion
- Whether `AppState` is a `dataclass` or `attrs` class (dataclass is standard)
- Whether to add type narrowing helpers (e.g., `assert state.claude_client is not None` vs Optional handling)
- How to handle the `settings` object — include in AppState or keep as module-level (it's immutable after load)

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Web Server (target file)
- `web/server.py` — Full file, focus on: globals (lines 57-100), lifespan (lines 137-232), `global` statements (lines 85, 158-159, 419), barge-in flow (search for `_stream_response`, `_tts_stream_to_browser`)

### FastAPI DI Pattern
- FastAPI docs: `app.state` + lifespan context manager + `Depends()` — canonical pattern

### Prior Phase Patterns
- `orchestrator/orchestrator/tts/base.py` — TTSClient protocol (already injected in lifespan)
- `orchestrator/orchestrator/whisper_client.py` — WhisperClient (already injected in lifespan)

### Phase 5 Dependency
- Phase 5 (Web Server Tests) will mock `AppState` to test route handlers in isolation. The `Depends(get_app_state)` pattern enables `app.dependency_overrides[get_app_state] = lambda: mock_state`.

</canonical_refs>

<code_context>
## Existing Code Insights

### Current Globals (to migrate)
- `sim_client`, `claude_client`, `context_store`, `phase_detector` — service clients (created in lifespan)
- `_sim_connected`, `_bridge_last_seen`, `_bridge_connected` — connection tracking (mutated in ws_telemetry handler)
- `_tts_client_instance` — TTSClient (created in lifespan, Phase 2)
- `_whisper_client` — WhisperClient (created in lifespan, Phase 3)
- `_TTS_CACHE` — phrase cache dict (populated at startup)

### Lifespan Already Does Most Creation
- Phases 2 & 3 moved TTSClient and WhisperClient creation into the lifespan
- The refactor mostly moves the remaining clients and adds the `AppState` wrapper

### Integration Points
- Every route handler signature changes to include `state: AppState = Depends(get_app_state)`
- Every helper function gains a `state: AppState` parameter
- Lifespan creates `AppState` instead of setting globals

</code_context>

<specifics>
## Specific Ideas

- The `_get_tts_client()` httpx wrapper may have been left over from Phase 2. If it still exists, remove it — TTSClient handles persistent connections internally.
- `settings` is loaded once at module level (`settings = load_settings()`). It could stay module-level since it's immutable, or move into AppState for consistency. Claude's discretion.

</specifics>

<deferred>
## Deferred Ideas

None — discussion stayed within phase scope.

</deferred>

---

*Phase: 04-web-server-refactor*
*Context gathered: 2026-03-27*
