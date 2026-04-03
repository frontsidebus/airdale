# Phase 4: Web Server Refactor - Research

**Researched:** 2026-03-28
**Domain:** FastAPI dependency injection, app.state lifecycle, async cancellation
**Confidence:** HIGH

## Summary

This phase migrates all module-level mutable state in `web/server.py` to a typed `AppState` container on `app.state`, accessed via FastAPI `Depends()`. The file currently has 11 module-level mutable variables, 3 `global` statement sites, and ~40 reference sites across 12 functions. The refactor is mechanical but high-risk because the barge-in cancellation flow spans nested async tasks with closures that reference globals.

The core pattern is well-established in FastAPI: lifespan context manager creates state, assigns it to `app.state`, and `Depends()` callables extract it for route handlers. Helper functions (not route handlers) receive state as an explicit parameter. The project already uses this lifespan pattern for object creation -- the refactor wraps existing creation into an `AppState` dataclass and eliminates `global` statements.

**Primary recommendation:** Define a single `AppState` dataclass, create it in lifespan, assign to `app.state.app_state`. Add `get_app_state(request: Request) -> AppState` dependency. Update all route handlers to use `Depends(get_app_state)` and pass state explicitly to helpers.

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions
- **D-01:** Single `AppState` dataclass containing all mutable shared state. Fields include: `sim_client`, `claude_client`, `context_store`, `phase_detector`, `tts_client`, `whisper_client`, `tts_cache`, `sim_connected`, `bridge_last_seen`, `bridge_connected`, `settings`.
- **D-02:** `AppState` stored on `app.state.app_state` via lifespan. Accessed by route handlers via `Depends(get_app_state)`.
- **D-03:** Constants (`_LOW_CONFIDENCE_THRESHOLD`, `_POST_SPEECH_PAUSE_SECS`, `_CACHEABLE_PHRASES`, `_STATIC_DIR`) stay module-level -- they are immutable and don't need injection.
- **D-04:** Full DI for all route handlers -- every route and WebSocket handler receives `AppState` via `Depends(get_app_state)`. No global access to mutable state anywhere.
- **D-05:** Internal helper functions (e.g., `_stream_response`, `_tts_stream_to_browser`, `_tts_websocket_stream`) receive `AppState` as a parameter. They don't use `Depends()` -- only route-level handlers do.
- **D-06:** `get_app_state(request: Request) -> AppState` is the single dependency callable. Returns `request.app.state.app_state`.
- **D-07:** Minimal touch -- pass `AppState` into barge-in functions as a parameter instead of accessing globals. Do NOT restructure the cancellation logic, task management, or event signaling. The proven behavior is preserved.
- **D-08:** Replace `nonlocal` references to global variables with `state.X` parameter access. Closure structure and cancellation flow stay identical.
- **D-09:** `sim_connected: bool`, `bridge_last_seen: float`, and `bridge_connected: bool` become simple fields on `AppState`. No lock needed -- asyncio is single-threaded, assignments are atomic.
- **D-10:** Lifespan creates `AppState` instance, populates all fields, assigns to `app.state.app_state`. No more `global` statements.
- **D-11:** Lifespan cleanup calls `aclose()` on TTSClient and WhisperClient from the `AppState` instance.
- **D-12:** These module-level variables must be completely removed (not just renamed): `sim_client`, `claude_client`, `context_store`, `phase_detector`, `_sim_connected`, `_bridge_last_seen`, `_bridge_connected`, `_tts_client_instance`, `_whisper_client`, `_TTS_CACHE`, `_get_tts_client()`, `_get_whisper_client()`, all `global X` statements.

### Claude's Discretion
- Whether `AppState` is a `dataclass` or `attrs` class (dataclass is standard)
- Whether to add type narrowing helpers (e.g., `assert state.claude_client is not None` vs Optional handling)
- How to handle the `settings` object -- include in AppState or keep as module-level (it's immutable after load)

### Deferred Ideas (OUT OF SCOPE)
None -- discussion stayed within phase scope.
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| WSRV-01 | Module-level global variables replaced with `app.state` + lifespan context manager | Global inventory (11 variables, 3 global sites), AppState dataclass pattern, lifespan creation pattern |
| WSRV-02 | Shared state accessible via FastAPI `Depends()` dependency injection | `get_app_state` dependency callable, route handler signature updates, helper parameter threading |
| WSRV-03 | Barge-in cancellation flow preserved with identical behavior after refactor | Barge-in reference map showing exactly which globals to replace with `state.X` |
| WSRV-04 | All existing functionality verified working after refactor (no regressions) | Complete function-by-function reference map enabling mechanical replacement |
</phase_requirements>

## Standard Stack

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| FastAPI | 0.135.1 | Web framework with DI | Already installed, `app.state` + `Depends()` is the canonical pattern |
| Python dataclasses | stdlib | AppState container | Zero dependencies, standard for typed data containers |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| pydantic | (existing) | Request/response models | Already in use, no changes needed |

No new packages needed. This is a pure refactor using existing FastAPI features.

## Architecture Patterns

### Pattern 1: AppState Dataclass

**What:** Single typed container for all mutable shared state.
**When to use:** Always -- this is the D-01 locked decision.

```python
from dataclasses import dataclass, field

@dataclass
class AppState:
    """Mutable shared state for the MERLIN web server."""
    settings: Settings  # or keep module-level -- Claude's discretion
    sim_client: TelemetryClient | None = None
    claude_client: ClaudeClient | None = None
    context_store: ContextStore | None = None
    phase_detector: FlightPhaseDetector | None = None
    whisper_client: WhisperClient | None = None
    tts_client: httpx.AsyncClient | None = None  # REST fallback client
    tts_cache: dict[str, bytes] = field(default_factory=dict)
    sim_connected: bool = False
    bridge_last_seen: float = 0.0
    bridge_connected: bool = False
```

### Pattern 2: Lifespan Context Manager Creates AppState

**What:** Lifespan populates AppState and assigns to `app.state.app_state`.
**When to use:** Replaces the current global-setting lifespan.

```python
@asynccontextmanager
async def lifespan(app: FastAPI):
    state = AppState(settings=settings)

    # ... create clients, assign to state.sim_client, state.claude_client, etc. ...

    app.state.app_state = state
    yield

    # Cleanup from state
    if state.sim_connected and state.sim_client is not None:
        await state.sim_client.disconnect()
    if state.tts_client and not state.tts_client.is_closed:
        await state.tts_client.aclose()
    if state.whisper_client is not None:
        await state.whisper_client.aclose()
```

### Pattern 3: Dependency Callable

**What:** Single `get_app_state` function for route handler injection.
**When to use:** Every route handler and WebSocket handler.

```python
from fastapi import Depends, Request

def get_app_state(request: Request) -> AppState:
    return request.app.state.app_state

# Route handler usage:
@app.get("/api/status")
async def get_status(state: AppState = Depends(get_app_state)):
    whisper_ok = False
    if state.whisper_client is not None:
        whisper_ok = await state.whisper_client.is_available()
    ...
```

### Pattern 4: WebSocket Handler with Depends

**What:** WebSocket handlers use `Depends()` identically to REST handlers.
**When to use:** `ws_telemetry` and `ws_chat`.

```python
@app.websocket("/ws/chat")
async def ws_chat(ws: WebSocket, state: AppState = Depends(get_app_state)):
    # state is injected, no global access needed
    ...
```

### Pattern 5: Helper Functions Receive State as Parameter

**What:** Non-route functions get `AppState` passed explicitly.
**When to use:** `_stream_response`, `_tts_websocket_stream`, `_tts_rest_fallback`, `_send_tts_chunk_rest`, `_transcribe_with_confidence`, `_transcribe_audio_bytes_with_confidence`, `_prepopulate_tts_cache`.

```python
async def _stream_response(
    ws: WebSocket,
    user_text: str,
    interrupt: asyncio.Event,
    state: AppState,  # new parameter
) -> None:
    # Replace: assert claude_client is not None
    # With:    assert state.claude_client is not None
    ...
```

### Anti-Patterns to Avoid
- **Injecting AppState into non-route helpers via Depends():** Only route-level handlers use `Depends()`. Helpers receive state as a regular parameter. Attempting `Depends()` in a non-route function causes runtime errors.
- **Partial migration:** Leaving some globals and adding state creates confusion about which source of truth to use. All 11 mutable globals must be removed in one pass.
- **Restructuring barge-in logic:** D-07 explicitly forbids this. The cancellation flow works -- just thread `state` through it.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Dependency injection | Custom service locator | FastAPI `Depends()` | Built-in, tested, supports `dependency_overrides` for Phase 5 testing |
| State container | Dict or module namespace | `@dataclass` | Type-safe, IDE support, explicit fields |
| Lifecycle management | Manual init/cleanup | Lifespan context manager | Already in use, handles startup/shutdown cleanly |

## Common Pitfalls

### Pitfall 1: Missing a Global Reference Site
**What goes wrong:** A function still reads a module-level global that was removed, causing `NameError` at runtime.
**Why it happens:** With ~40 reference sites across 12 functions, it is easy to miss one.
**How to avoid:** Use the complete reference map below. After refactoring, run `ruff check` and search for any remaining references to the removed global names.
**Warning signs:** `NameError` or `UnboundLocalError` at runtime.

### Pitfall 2: Forgetting State in Nested Closures
**What goes wrong:** The `_on_state` callback inside lifespan and the `_receive_audio` closure inside `_tts_websocket_stream` reference globals via closure scope.
**Why it happens:** These are defined inside other functions and capture state from the enclosing scope.
**How to avoid:** The `_on_state` callback captures `state` from lifespan scope (where `state` is the AppState instance). The `_receive_audio` closure only accesses `tts_ws`, `ws`, and `interrupt` -- no globals, so it needs no changes.
**Warning signs:** `NameError` in callbacks that fire later.

### Pitfall 3: WebSocket Depends Requires `websocket` Parameter Name
**What goes wrong:** FastAPI WebSocket DI works identically to HTTP, but the first parameter must be `WebSocket` typed.
**Why it happens:** Non-issue for this codebase -- already using `ws: WebSocket` as first param.
**How to avoid:** Keep `ws: WebSocket` as first parameter, add `state: AppState = Depends(get_app_state)` after it.

### Pitfall 4: TTS Cache Prepopulation References State Before Assignment
**What goes wrong:** `_prepopulate_tts_cache()` is called in lifespan and currently accesses `_TTS_CACHE` and `_get_tts_client()` globals.
**Why it happens:** After removing globals, the function needs `state` passed to it.
**How to avoid:** Pass `state` to `_prepopulate_tts_cache(state)` and use `state.tts_cache` and `state.tts_client` internally.

### Pitfall 5: The `settings` Module-Level Load
**What goes wrong:** `settings = load_settings()` at module level is used for logging config before lifespan runs. If moved entirely into AppState, logging setup breaks.
**Why it happens:** Module-level code runs at import time, before lifespan.
**How to avoid:** Keep `settings = load_settings()` at module level (it is immutable). Per D-03 discretion, either include it in AppState for consistency or let routes access it from the module. Recommendation: include a reference in AppState for test override capability, but keep the module-level load for early logging setup.

## Code Examples

### Complete Global Reference Map

This is the critical artifact for planning. Every function that references a mutable global, and what it needs from AppState:

| Function | Line | Globals Referenced | AppState Fields Needed |
|----------|------|-------------------|----------------------|
| `_get_tts_client()` | 84-88 | `_tts_client` | **REMOVE ENTIRE FUNCTION** -- use `state.tts_client` directly |
| `_prepopulate_tts_cache()` | 115-148 | `_TTS_CACHE`, `_get_tts_client()`, `settings` | `state.tts_cache`, `state.tts_client`, `state.settings` |
| `lifespan()` | 157-234 | `sim_client`, `claude_client`, `context_store`, `phase_detector`, `_sim_connected`, `_whisper_client`, `_tts_client` | Creates `AppState`, no longer sets globals |
| `get_status()` | 286-316 | `_whisper_client`, `context_store`, `_bridge_connected`, `_bridge_last_seen`, `_sim_connected`, `settings` | `state.whisper_client`, `state.context_store`, `state.bridge_connected`, `state.bridge_last_seen`, `state.sim_connected`, `state.settings` |
| `transcribe_audio()` | 320-358 | (none directly -- calls `_transcribe_with_confidence`) | Needs state passed through to helper |
| `text_to_speech()` | 361-403 | `settings`, `_TTS_CACHE`, `_get_tts_client()` | `state.settings`, `state.tts_cache`, `state.tts_client` |
| `ws_telemetry()` | 411-478 | `_bridge_last_seen`, `_bridge_connected`, `phase_detector`, `settings` | `state.bridge_last_seen`, `state.bridge_connected`, `state.phase_detector`, `state.settings` |
| `ws_chat()` | 486-631 | (none directly -- delegates to `_stream_response`) | Pass state to helpers |
| `_tts_websocket_stream()` | 638-758 | `settings`, `_TTS_CACHE` | `state.settings`, `state.tts_cache` |
| `_tts_rest_fallback()` | 760-779 | (none directly -- calls `_send_tts_chunk_rest`) | Pass state through |
| `_stream_response()` | 782-878 | `_get_tts_client()`, `claude_client`, `_sim_connected`, `sim_client`, `phase_detector`, `settings` | `state.tts_client`, `state.claude_client`, `state.sim_connected`, `state.sim_client`, `state.phase_detector`, `state.settings` |
| `_send_tts_chunk_rest()` | 924-970 | `_TTS_CACHE`, `_get_tts_client()`, `settings` | `state.tts_cache`, `state.tts_client`, `state.settings` |
| `_transcribe_with_confidence()` | 973-996 | `_whisper_client` | `state.whisper_client` |
| `_transcribe_audio_bytes_with_confidence()` | 999-1020 | (none directly -- calls `_transcribe_with_confidence`) | Pass state through |

### Function Signature Changes Summary

Route handlers (add `Depends`):
- `get_status()` -> `get_status(state: AppState = Depends(get_app_state))`
- `transcribe_audio(file)` -> `transcribe_audio(file: UploadFile, state: AppState = Depends(get_app_state))`
- `text_to_speech(request)` -> `text_to_speech(request: TTSRequest, state: AppState = Depends(get_app_state))`
- `ws_telemetry(ws)` -> `ws_telemetry(ws: WebSocket, state: AppState = Depends(get_app_state))`
- `ws_chat(ws)` -> `ws_chat(ws: WebSocket, state: AppState = Depends(get_app_state))`

Helpers (add `state: AppState` parameter):
- `_prepopulate_tts_cache()` -> `_prepopulate_tts_cache(state: AppState)`
- `_stream_response(ws, user_text, interrupt)` -> `_stream_response(ws, user_text, interrupt, state)`
- `_tts_websocket_stream(ws, tts_queue, interrupt)` -> `_tts_websocket_stream(ws, tts_queue, interrupt, state)`
- `_tts_rest_fallback(ws, tts_queue, interrupt)` -> `_tts_rest_fallback(ws, tts_queue, interrupt, state)`
- `_send_tts_chunk_rest(ws, text)` -> `_send_tts_chunk_rest(ws, text, state)`
- `_transcribe_with_confidence(audio_bytes, ...)` -> `_transcribe_with_confidence(audio_bytes, ..., state)`
- `_transcribe_audio_bytes_with_confidence(audio_bytes, mime_type)` -> `_transcribe_audio_bytes_with_confidence(audio_bytes, mime_type, state)`

Functions unchanged:
- `_split_at_sentence(text)` -- pure function, no state access
- `index()` -- serves static file, no mutable state

### Barge-in Flow Preservation Detail

The barge-in flow in `ws_chat` uses:
1. `active_response_task` -- local variable (nonlocal in closure), stays as-is
2. `interrupt_event` -- local variable, stays as-is
3. `_cancel_active_response()` -- closure over locals only, no globals, stays as-is
4. `_stream_response()` -- references `claude_client`, `sim_client`, `_sim_connected`, `phase_detector` globals -> all become `state.X`

The closure structure (`_cancel_active_response` defined inside `ws_chat`) does NOT reference any globals. It only uses `active_response_task` and `interrupt_event` which are local. This means the barge-in cancellation mechanism itself needs zero changes -- only `_stream_response` and its callees need `state` threaded through.

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Module-level globals with `global` statements | `app.state` + lifespan + `Depends()` | FastAPI 0.93+ (2023) | Testable, no global mutation, `dependency_overrides` for testing |
| `@app.on_event("startup")` | `lifespan` context manager | FastAPI 0.93 | Already using lifespan -- no migration needed |

## Open Questions

1. **`settings` placement**
   - What we know: `settings = load_settings()` at module level is used for logging config at import time. It is immutable after creation.
   - What's unclear: Whether to duplicate the reference in AppState or let functions read the module-level `settings`.
   - Recommendation: Include `settings` in AppState for testability (Phase 5 can override it). Keep the module-level `settings` for the logging setup that runs before lifespan. This means two references to the same object -- acceptable since settings is immutable.

2. **`_prepopulate_tts_cache` uses inline httpx calls, not TTSClient**
   - What we know: This function manually calls ElevenLabs REST API via `_get_tts_client()` (bare httpx). It does NOT use the `TTSClient` protocol from Phase 2.
   - What's unclear: Whether to refactor it to use TTSClient or keep the inline httpx pattern.
   - Recommendation: Per D-07 minimal touch, keep the existing httpx pattern but route through `state.tts_client` (the httpx.AsyncClient). Do not introduce TTSClient dependency here -- that would be a behavior change beyond the refactor scope.

## Project Constraints (from CLAUDE.md)

- **Linter/Formatter:** ruff (config in `pyproject.toml`). Run `ruff check .` and `ruff format .` after changes.
- **Line length:** 100 characters
- **Type hints:** Required on all function signatures -- AppState parameter must be typed
- **Async:** Use `async`/`await` throughout -- maintained by this refactor
- **Models:** Use Pydantic `BaseModel` for data structures crossing boundaries. AppState is internal, so dataclass is appropriate.
- **Config:** Use `pydantic-settings` `BaseSettings` -- `settings` already follows this

## Sources

### Primary (HIGH confidence)
- `web/server.py` -- direct code analysis, complete global reference inventory
- `orchestrator/orchestrator/tts/base.py` -- TTSClient protocol pattern from Phase 2
- FastAPI 0.135.1 installed locally -- `app.state` and `Depends()` are core features

### Secondary (MEDIUM confidence)
- FastAPI official documentation patterns for lifespan + `app.state` + `Depends()` -- well-established canonical pattern

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH -- no new libraries, using existing FastAPI features
- Architecture: HIGH -- pattern is well-established in FastAPI, decisions are locked
- Pitfalls: HIGH -- complete code analysis with line-by-line reference map
- Barge-in preservation: HIGH -- verified that cancellation closures reference only locals, not globals

**Research date:** 2026-03-28
**Valid until:** 2026-04-28 (stable -- no framework changes expected)
