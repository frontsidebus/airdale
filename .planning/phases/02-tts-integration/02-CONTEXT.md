# Phase 2: TTS Integration - Context

**Gathered:** 2026-03-27
**Status:** Ready for planning

<domain>
## Phase Boundary

Wire the existing TTS abstraction layer (`TTSClient` protocol with ElevenLabs and Kokoro backends) into the web server and CLI voice module. Replace all inline ElevenLabs httpx calls with the protocol. Extend the protocol for WebSocket-based incremental streaming. Consolidate voice settings into configurable Settings fields. Add missing config fields needed by the factory.

</domain>

<decisions>
## Implementation Decisions

### Voice Settings
- **D-01:** Voice settings (stability, similarity_boost, style) become configurable via .env fields: `TTS_STABILITY`, `TTS_SIMILARITY_BOOST`, `TTS_STYLE`.
- **D-02:** Default values are the web server's current values: `{stability: 0.75, similarity_boost: 0.80, style: 0.15}`. These are used when not explicitly set in .env.
- **D-03:** The `ElevenLabsClient` must read voice settings from config instead of hardcoding them. Pass them via constructor or settings object.
- **D-04:** All 4 hardcoded voice settings in `web/server.py` and the 1 in `orchestrator/orchestrator/voice.py` must be replaced with the shared config values.

### Streaming Protocol
- **D-05:** Add a `synthesize_ws_stream()` method to the `TTSClient` protocol for WebSocket-based incremental streaming. Signature: accepts an `AsyncIterator[str]` of text chunks (as Claude streams), returns `AsyncIterator[bytes]` of audio chunks.
- **D-06:** Backends that don't support WebSocket streaming (e.g., Kokoro) should implement `synthesize_ws_stream()` by buffering text chunks and falling back to `synthesize_stream()` on flush.
- **D-07:** The web server's `_tts_websocket_stream()` function must be replaced with the protocol's `synthesize_ws_stream()`.

### TTS Phrase Cache
- **D-08:** Phrase cache stays in the web server, not in the TTSClient. The client synthesizes, the server caches. Clean separation of concerns.
- **D-09:** The web server's `_prepopulate_tts_cache()` calls `TTSClient.synthesize()` instead of inline httpx calls.

### Config Fields
- **D-10:** New Settings fields with `TTS_` prefix:
  - `tts_backend: str = "elevenlabs"` — selects backend ("elevenlabs" or "local")
  - `tts_local_url: str = "http://localhost:8880"` — Kokoro server URL
  - `tts_voice_id_local: str = "af_heart"` — Kokoro voice ID
  - `tts_stability: float = 0.75` — ElevenLabs stability
  - `tts_similarity_boost: float = 0.80` — ElevenLabs similarity boost
  - `tts_style: float = 0.15` — ElevenLabs style
- **D-11:** Update `.env.example` with all new TTS fields and documentation.

### Persistent HTTP Client
- **D-12:** The `ElevenLabsClient` must use a persistent `httpx.AsyncClient` (created once, reused across calls) instead of creating a new client per synthesis call. Current `voice.py` creates a new client per `_synthesize()` call.
- **D-13:** Add `close()` or `aclose()` method to `TTSClient` protocol for cleanup. The web server's lifespan handler and CLI's shutdown path should call it.

### Claude's Discretion
- Internal implementation of `synthesize_ws_stream()` for ElevenLabs (WS connection management, reconnection)
- How to structure the Kokoro fallback in `synthesize_ws_stream()` (buffer size, flush trigger)
- Whether to add `aclose()` to the protocol or just implement it on concrete classes

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### TTS Abstraction Layer (existing)
- `orchestrator/orchestrator/tts/__init__.py` — Factory function `create_tts_client()` and lazy imports
- `orchestrator/orchestrator/tts/base.py` — `TTSClient` Protocol definition (synthesize, synthesize_stream)
- `orchestrator/orchestrator/tts/elevenlabs.py` — ElevenLabs REST client (hardcoded voice settings)
- `orchestrator/orchestrator/tts/kokoro.py` — Kokoro local TTS client

### Web Server TTS (inline code to replace)
- `web/server.py` — Lines 84-91 (`_get_tts_client`), 125-155 (`_prepopulate_tts_cache`), 369-407 (`/api/tts` endpoint), 643+ (`_tts_websocket_stream`)
- Voice settings at lines 148, 394, 668, 961

### CLI Voice Module (inline code to replace)
- `orchestrator/orchestrator/voice.py` — Lines 329-340 (`_synthesize` with per-call httpx.AsyncClient), voice settings at line 333

### Config
- `orchestrator/orchestrator/config.py` — `Settings` class (needs new TTS fields)
- `.env.example` — Env var documentation (needs TTS section)

### Tests
- `orchestrator/tests/test_tts_client.py` — Existing TTS client tests (untracked, 20 tests)

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `TTSClient` Protocol with `synthesize()` and `synthesize_stream()` — extend, don't replace
- `create_tts_client()` factory — already handles backend selection via `settings.tts_backend`
- `ElevenLabsClient` and `KokoroClient` — need voice settings injection and persistent client
- Web server's `_get_tts_client()` — persistent httpx client pattern to replicate in ElevenLabsClient

### Established Patterns
- pydantic-settings `BaseSettings` for all config (TTS fields follow this)
- Factory pattern in `tts/__init__.py` for backend selection
- `async with httpx.AsyncClient` for HTTP calls throughout codebase

### Integration Points
- `web/server.py` must import and use `create_tts_client(settings)` in lifespan
- `orchestrator/orchestrator/voice.py` `VoiceOutput` must use `TTSClient` instead of inline httpx
- Settings class gains 6 new fields
- `.env.example` gains TTS section
- `ElevenLabsClient` constructor changes (voice settings params)

</code_context>

<specifics>
## Specific Ideas

- The web server currently uses ElevenLabs WebSocket streaming (`wss://api.elevenlabs.io/v1/text-to-speech/{voice_id}/stream-input`) for lowest time-to-first-audio. This is a different endpoint than the REST streaming used in the current `ElevenLabsClient`. The new `synthesize_ws_stream()` must target this WebSocket endpoint.
- The phrase cache pre-generation happens at startup and should use `synthesize()` (not streaming) since it needs complete audio bytes for caching.

</specifics>

<deferred>
## Deferred Ideas

None — discussion stayed within phase scope.

</deferred>

---

*Phase: 02-tts-integration*
*Context gathered: 2026-03-27*
