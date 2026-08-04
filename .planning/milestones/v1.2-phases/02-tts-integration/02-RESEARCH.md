# Phase 2: TTS Integration - Research

**Researched:** 2026-03-26
**Domain:** TTS abstraction layer, ElevenLabs WebSocket streaming, pydantic-settings config
**Confidence:** HIGH

## Summary

Phase 2 wires the existing TTS abstraction layer (TTSClient protocol with ElevenLabs and Kokoro backends) into the two consumers that currently bypass it: the web server (`web/server.py`) and the CLI voice module (`orchestrator/orchestrator/voice.py`). Both consumers have inline httpx calls to ElevenLabs with hardcoded voice settings. The work extends the protocol with a WebSocket streaming method, consolidates voice settings into config, adds persistent HTTP clients, and adds missing config fields.

The codebase is well-structured for this change. The `TTSClient` protocol, `create_tts_client()` factory, and both backend implementations already exist. The web server already has a persistent httpx client pattern (`_get_tts_client()`). The test file (`test_tts_client.py`) already has 20 tests, some of which reference config fields that don't yet exist (`tts_backend`, `tts_configured`, `voice_id` returning different values per backend). These tests are ahead of the implementation and will pass once config fields are added.

**Primary recommendation:** Implement in three waves: (1) config fields + voice settings injection + persistent client, (2) wire consumers to use TTSClient, (3) add `synthesize_ws_stream()` for WebSocket streaming.

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions
- **D-01:** Voice settings (stability, similarity_boost, style) become configurable via .env fields: `TTS_STABILITY`, `TTS_SIMILARITY_BOOST`, `TTS_STYLE`.
- **D-02:** Default values are the web server's current values: `{stability: 0.75, similarity_boost: 0.80, style: 0.15}`. These are used when not explicitly set in .env.
- **D-03:** The `ElevenLabsClient` must read voice settings from config instead of hardcoding them. Pass them via constructor or settings object.
- **D-04:** All 4 hardcoded voice settings in `web/server.py` and the 1 in `orchestrator/orchestrator/voice.py` must be replaced with the shared config values.
- **D-05:** Add a `synthesize_ws_stream()` method to the `TTSClient` protocol for WebSocket-based incremental streaming. Signature: accepts an `AsyncIterator[str]` of text chunks (as Claude streams), returns `AsyncIterator[bytes]` of audio chunks.
- **D-06:** Backends that don't support WebSocket streaming (e.g., Kokoro) should implement `synthesize_ws_stream()` by buffering text chunks and falling back to `synthesize_stream()` on flush.
- **D-07:** The web server's `_tts_websocket_stream()` function must be replaced with the protocol's `synthesize_ws_stream()`.
- **D-08:** Phrase cache stays in the web server, not in the TTSClient. The client synthesizes, the server caches. Clean separation of concerns.
- **D-09:** The web server's `_prepopulate_tts_cache()` calls `TTSClient.synthesize()` instead of inline httpx calls.
- **D-10:** New Settings fields with `TTS_` prefix: `tts_backend`, `tts_local_url`, `tts_voice_id_local`, `tts_stability`, `tts_similarity_boost`, `tts_style`.
- **D-11:** Update `.env.example` with all new TTS fields and documentation.
- **D-12:** The `ElevenLabsClient` must use a persistent `httpx.AsyncClient` (created once, reused across calls) instead of creating a new client per synthesis call.
- **D-13:** Add `close()` or `aclose()` method to `TTSClient` protocol for cleanup.

### Claude's Discretion
- Internal implementation of `synthesize_ws_stream()` for ElevenLabs (WS connection management, reconnection)
- How to structure the Kokoro fallback in `synthesize_ws_stream()` (buffer size, flush trigger)
- Whether to add `aclose()` to the protocol or just implement it on concrete classes

### Deferred Ideas (OUT OF SCOPE)
None -- discussion stayed within phase scope.
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| TTS-01 | Web server uses TTSClient protocol instead of inline ElevenLabs httpx calls | D-07, D-09 -- replace `_tts_websocket_stream()`, `/api/tts`, and `_prepopulate_tts_cache()` with TTSClient calls |
| TTS-02 | CLI voice module uses TTSClient protocol instead of inline ElevenLabs httpx calls | VoiceOutput._synthesize() replaced with TTSClient.synthesize(); VoiceOutput accepts TTSClient in constructor |
| TTS-03 | TTS protocol extended to support incremental WebSocket streaming | D-05, D-06 -- add `synthesize_ws_stream()` to protocol; ElevenLabs uses WS API, Kokoro buffers+falls back |
| TTS-04 | Voice settings consolidated into single config source | D-01, D-02, D-03, D-04 -- three float fields in Settings, passed to ElevenLabsClient constructor |
| TTS-05 | Persistent httpx client for TTS calls | D-12 -- ElevenLabsClient creates `httpx.AsyncClient` once in constructor, reuses across calls |
| TTS-06 | Config fields for tts_backend, tts_local_url, tts_voice_id_local added | D-10 -- six new fields in Settings class, factory already reads `tts_backend` |
| TTS-07 | Kokoro TTS backend selectable via config without code changes | Factory already handles this; D-10 ensures all fields exist; D-06 ensures WS streaming fallback works |
</phase_requirements>

## Project Constraints (from CLAUDE.md)

- **Async throughout:** All orchestrator code uses `async`/`await`. TTS clients must be async.
- **pydantic-settings:** All config via `BaseSettings` with `.env` files. No hardcoded keys or magic numbers.
- **Pydantic BaseModel:** For all data structures crossing boundaries.
- **ruff:** Linter/formatter with 100-char line length. Rules: E, F, I, N, UP, B, SIM.
- **Type hints:** Required on all function signatures.
- **Config naming:** `snake_case` for Python, `TTS_` prefix for env vars (auto-mapped by pydantic-settings).
- **Testing:** pytest + pytest-asyncio. Mock WebSocket and API in unit tests.

## Standard Stack

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| httpx | 0.28.1 | Persistent async HTTP client for ElevenLabs REST | Already used throughout codebase; supports async context management and streaming |
| websockets | 16.0 | ElevenLabs WebSocket streaming connection | Already used by web server for ElevenLabs WS TTS |
| pydantic-settings | (installed) | Settings fields for TTS config | Project standard for all configuration |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| pytest | (installed) | Test runner | All tests |
| pytest-asyncio | (installed) | Async test support | Tests for synthesize, synthesize_ws_stream |

No new dependencies are needed. All required libraries are already installed.

## Architecture Patterns

### Current TTS Module Structure (extend, don't replace)
```
orchestrator/orchestrator/tts/
    __init__.py         # Factory: create_tts_client(settings) -> TTSClient
    base.py             # TTSClient Protocol (synthesize, synthesize_stream)
    elevenlabs.py       # ElevenLabsClient -- REST API
    kokoro.py           # KokoroClient -- local HTTP API
```

### Pattern 1: Voice Settings Injection via Constructor
**What:** Pass voice settings as constructor parameters to ElevenLabsClient instead of hardcoding them.
**When to use:** Every ElevenLabsClient instantiation (via factory).
**Example:**
```python
# In elevenlabs.py
class ElevenLabsClient:
    def __init__(
        self,
        api_key: str,
        voice_id: str,
        model_id: str = "eleven_multilingual_v2",
        stability: float = 0.75,
        similarity_boost: float = 0.80,
        style: float = 0.15,
    ) -> None:
        self._api_key = api_key
        self._voice_id = voice_id
        self._model_id = model_id
        self._stability = stability
        self._similarity_boost = similarity_boost
        self._style = style
        # Persistent client -- reused across all calls
        self._http = httpx.AsyncClient(timeout=30.0)

# In __init__.py factory
return ElevenLabsClient(
    api_key=settings.elevenlabs_api_key,
    voice_id=settings.elevenlabs_voice_id,
    model_id=settings.elevenlabs_model_id,
    stability=settings.tts_stability,
    similarity_boost=settings.tts_similarity_boost,
    style=settings.tts_style,
)
```

### Pattern 2: Persistent httpx.AsyncClient
**What:** Create `httpx.AsyncClient` once in the constructor, close in `aclose()`.
**When to use:** ElevenLabsClient and KokoroClient.
**Why:** The current code creates a new client per `synthesize()` call (visible in both `elevenlabs.py` and `voice.py`). This wastes TCP connections and adds latency. The web server already has this pattern with `_get_tts_client()`.
**Example:**
```python
class ElevenLabsClient:
    def __init__(self, ...) -> None:
        ...
        self._http = httpx.AsyncClient(timeout=30.0)

    async def aclose(self) -> None:
        await self._http.aclose()

    async def synthesize(self, text: str) -> bytes:
        resp = await self._http.post(url, headers=headers, json=payload)
        resp.raise_for_status()
        return resp.content
```

### Pattern 3: WebSocket Streaming Method (synthesize_ws_stream)
**What:** New protocol method that accepts streaming text input and yields audio chunks.
**When to use:** Web server chat flow where Claude streams text and TTS converts incrementally.
**Example:**
```python
# In base.py protocol
async def synthesize_ws_stream(
    self, text_chunks: AsyncIterator[str],
) -> AsyncIterator[bytes]:
    ...
    if False:
        yield  # type: ignore[misc]

# In elevenlabs.py -- opens ElevenLabs WS connection
async def synthesize_ws_stream(
    self, text_chunks: AsyncIterator[str],
) -> AsyncIterator[bytes]:
    ws_url = (
        f"wss://api.elevenlabs.io/v1/text-to-speech/{self._voice_id}"
        f"/stream-input?model_id={self._model_id}&output_format=mp3_44100_128"
    )
    async with ws_lib.connect(
        ws_url, additional_headers={"xi-api-key": self._api_key}
    ) as tts_ws:
        # Send init message with voice settings
        await tts_ws.send(json.dumps({
            "text": " ",
            "voice_settings": {
                "stability": self._stability,
                "similarity_boost": self._similarity_boost,
                "style": self._style,
            },
        }))

        # Concurrently: feed text in, yield audio out
        ...
```

### Pattern 4: Kokoro Fallback for WebSocket Streaming
**What:** Buffer incoming text chunks, flush to `synthesize_stream()` at sentence boundaries.
**When to use:** KokoroClient.synthesize_ws_stream() -- Kokoro has no WS API.
**Example:**
```python
async def synthesize_ws_stream(
    self, text_chunks: AsyncIterator[str],
) -> AsyncIterator[bytes]:
    buffer = ""
    sentence_endings = ".!?\n"
    async for chunk in text_chunks:
        buffer += chunk
        # Find last sentence boundary
        last_boundary = max(buffer.rfind(ch) for ch in sentence_endings)
        if last_boundary >= 0:
            sentence = buffer[: last_boundary + 1].strip()
            buffer = buffer[last_boundary + 1 :]
            if sentence:
                async for audio_chunk in self.synthesize_stream(sentence):
                    yield audio_chunk
    # Flush remaining
    if buffer.strip():
        async for audio_chunk in self.synthesize_stream(buffer.strip()):
            yield audio_chunk
```

### Pattern 5: VoiceOutput Refactored to Accept TTSClient
**What:** Replace VoiceOutput's inline ElevenLabs calls with TTSClient dependency injection.
**When to use:** CLI voice module integration.
**Example:**
```python
class VoiceOutput:
    def __init__(
        self,
        tts_client: TTSClient,
        sample_rate: int = 24000,
    ) -> None:
        self._tts = tts_client
        self._sample_rate = sample_rate
        self._cancelled = False
        self._playing = False

    async def _synthesize(self, text: str) -> bytes | None:
        try:
            return await self._tts.synthesize(text)
        except Exception as e:
            logger.warning("TTS synthesis failed: %s", e)
            return None
```

### Anti-Patterns to Avoid
- **Per-call httpx.AsyncClient:** Creating `async with httpx.AsyncClient() as client` inside every `synthesize()` call wastes connections. Use persistent client.
- **Hardcoded voice_settings dicts:** Five separate locations currently hardcode `{stability, similarity_boost, style}`. All must read from config.
- **Mixing TTS concerns in consumers:** The web server should not import `websockets` for TTS or know about ElevenLabs URLs. It should call `tts_client.synthesize_ws_stream()`.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| ElevenLabs WS protocol | Custom WS framing | `websockets.connect()` + ElevenLabs stream-input API | The API handles text buffering, audio chunking, and flush signals |
| HTTP connection pooling | Manual socket management | `httpx.AsyncClient` with default pool | httpx manages connection reuse, keepalive, and cleanup |
| Config field validation | Manual env var parsing | pydantic-settings `BaseSettings` with `Field(default=...)` | Auto-maps TTS_STABILITY env var to `tts_stability` field with type validation |

## Common Pitfalls

### Pitfall 1: Voice Settings Divergence Between Consumers
**What goes wrong:** The CLI voice module currently uses `{stability: 0.5, similarity_boost: 0.75, style: 0.3}` while the web server uses `{stability: 0.75, similarity_boost: 0.80, style: 0.15}`. After consolidation, both will use the web server's defaults (D-02). This is intentional per the user decision, but the CLI's voice character will change.
**Why it happens:** The two consumers were developed independently with different tuning.
**How to avoid:** Apply D-02 defaults consistently. The user has explicitly decided on the web server values as the canonical set.
**Warning signs:** If someone reports "MERLIN sounds different in CLI mode" after this phase, that's expected.

### Pitfall 2: ElevenLabs WebSocket Audio Format
**What goes wrong:** The ElevenLabs WS API returns audio as base64-encoded strings in JSON messages (field `"audio"`), NOT as binary WebSocket frames. The current web server code handles both cases (lines 684-704), but a new implementation might assume binary frames.
**Why it happens:** The REST streaming endpoint returns raw bytes; the WS endpoint returns JSON with base64 audio.
**How to avoid:** In `synthesize_ws_stream()`, always `base64.b64decode(data["audio"])` from the JSON message. Check for `isFinal` to know when the stream ends.
**Warning signs:** Empty audio chunks or decode errors.

### Pitfall 3: WebSocket Connection Initialization
**What goes wrong:** The ElevenLabs WS API requires a specific initialization message with `"text": " "` (a single space) before any actual text can be sent. Missing this causes the connection to fail silently.
**Why it happens:** The API uses the first message to configure voice settings and establish the generation context.
**How to avoid:** Always send the init message immediately after connection. Voice settings can only be set in this first message and cannot be changed mid-stream.

### Pitfall 4: Persistent Client Lifecycle
**What goes wrong:** If `aclose()` is not called, httpx logs warnings about unclosed connections at shutdown. If called too early, subsequent synthesis calls fail.
**Why it happens:** Async resource cleanup requires explicit lifecycle management.
**How to avoid:** Call `aclose()` in the web server's lifespan teardown and the CLI's shutdown handler. The web server already has this pattern (lines 234-238).
**Warning signs:** "Unclosed client session" warnings in logs.

### Pitfall 5: Text Flushing in WS Streaming
**What goes wrong:** ElevenLabs WS API buffers text internally. If the final text chunk doesn't trigger generation (too short), audio for the last segment is never produced.
**Why it happens:** The API's `chunk_length_schedule` means small text fragments get buffered. Without an explicit flush, the last fragment may be lost.
**How to avoid:** After all text chunks are sent, send `{"text": ""}` (empty string) to signal end-of-input and flush remaining audio. The current web server does this at line 747.

### Pitfall 6: Concurrent Send/Receive on ElevenLabs WebSocket
**What goes wrong:** The `synthesize_ws_stream()` method must send text AND receive audio concurrently on the same WS connection. A naive sequential approach (send all text, then receive all audio) will deadlock because the server's send buffer fills up while the client isn't reading.
**Why it happens:** WebSocket is full-duplex; the API starts sending audio as soon as enough text is buffered.
**How to avoid:** Use `asyncio.create_task()` to run the receive loop concurrently with the send loop, exactly as the current web server does (line 710). Use an `asyncio.Queue` to bridge the receive task's output to the async iterator yield.

### Pitfall 7: Protocol Method Requires Async Iterator Stub
**What goes wrong:** Python Protocol methods that are async generators need a special stub form to satisfy the type checker.
**Why it happens:** A Protocol method can't just have `yield` -- it needs the `if False: yield` pattern.
**How to avoid:** Follow the existing pattern in `base.py` line 31: `if False: yield  # type: ignore[misc]`

## Code Examples

### Config Fields Addition (config.py)
```python
# --- TTS settings --------------------------------------------------------
tts_backend: str = Field(
    default="elevenlabs",
    description="TTS backend: 'elevenlabs' (cloud) or 'local' (Kokoro)",
)
tts_local_url: str = Field(
    default="http://localhost:8880",
    description="URL of the local Kokoro TTS server",
)
tts_voice_id_local: str = Field(
    default="af_heart",
    description="Voice ID for local Kokoro TTS",
)
tts_stability: float = Field(
    default=0.75,
    description="ElevenLabs voice stability (0.0-1.0)",
)
tts_similarity_boost: float = Field(
    default=0.80,
    description="ElevenLabs similarity boost (0.0-1.0)",
)
tts_style: float = Field(
    default=0.15,
    description="ElevenLabs style (0.0-1.0, V2+ models only)",
)
```

### tts_configured Property and voice_id Update
```python
@property
def tts_configured(self) -> bool:
    """Whether TTS is configured enough to synthesize audio."""
    if self.tts_backend == "local":
        return bool(self.tts_local_url)
    return bool(self.elevenlabs_api_key and self.elevenlabs_voice_id)

@property
def voice_id(self) -> str:
    """Return the effective voice ID based on backend."""
    if self.tts_backend == "local":
        return self.tts_voice_id_local
    return self.elevenlabs_voice_id
```

### Web Server Integration (lifespan)
```python
from orchestrator.tts import TTSClient, create_tts_client

# In lifespan():
tts_client = create_tts_client(settings)

# In teardown:
if hasattr(tts_client, 'aclose'):
    await tts_client.aclose()
```

### Web Server _prepopulate_tts_cache Replacement
```python
async def _prepopulate_tts_cache(tts: TTSClient) -> None:
    for phrase in _CACHEABLE_PHRASES:
        sanitized = preprocess_for_tts(phrase)
        if not sanitized or sanitized in _TTS_CACHE:
            continue
        try:
            _TTS_CACHE[sanitized] = await tts.synthesize(sanitized)
        except Exception as exc:
            logger.debug("Failed to cache TTS phrase '%s': %s", sanitized, exc)
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Per-call httpx.AsyncClient | Persistent httpx.AsyncClient | httpx 0.23+ | Eliminates TCP handshake per request; ~50-100ms savings per call |
| REST-only TTS streaming | WebSocket stream-input API | ElevenLabs 2024 | Lower time-to-first-audio; text can be fed incrementally as Claude streams |
| Hardcoded voice settings | Config-driven voice settings | This phase | Single source of truth; no drift between consumers |

## Open Questions

1. **aclose() on Protocol vs Concrete Classes**
   - What we know: Python Protocols can define any method. Adding `aclose()` to TTSClient Protocol means all implementations must have it.
   - What's unclear: Whether to make it a required protocol method or duck-type it (`hasattr(client, 'aclose')` check).
   - Recommendation: Add it to the protocol. Both ElevenLabsClient and KokoroClient have persistent httpx clients that need cleanup. A no-op `aclose()` is fine if a future backend doesn't need it. This is cleaner than `hasattr` checks scattered across consumers.

2. **Kokoro Buffer Flush Strategy**
   - What we know: Kokoro has no WebSocket API; `synthesize_ws_stream()` must buffer and call `synthesize_stream()`.
   - What's unclear: Optimal buffer size/trigger. Sentence boundaries work for English but may miss edge cases.
   - Recommendation: Use sentence-boundary flushing (`.!?\n`) matching the existing pattern in `voice.py` line 293. This is good enough for aviation phraseology which uses clear sentence structure.

3. **Test File Ahead of Implementation**
   - What we know: `test_tts_client.py` has tests for `settings.tts_backend`, `settings.tts_configured`, and `settings.voice_id` returning different values per backend. These tests currently fail because the config fields don't exist.
   - What's unclear: Whether these tests match the exact implementation that will be built.
   - Recommendation: Implement config fields to match what the tests expect. The tests appear well-written and aligned with D-10. Any mismatches can be fixed during implementation.

## Sources

### Primary (HIGH confidence)
- Codebase inspection: `orchestrator/orchestrator/tts/` -- protocol, factory, both backends
- Codebase inspection: `web/server.py` -- all inline ElevenLabs calls (lines 84-91, 125-155, 366-408, 643-750, 950-975)
- Codebase inspection: `orchestrator/orchestrator/voice.py` -- VoiceOutput._synthesize (lines 321-349)
- Codebase inspection: `orchestrator/orchestrator/config.py` -- current Settings class (no TTS fields beyond elevenlabs_*)
- Codebase inspection: `orchestrator/tests/test_tts_client.py` -- 20 existing tests including forward-looking config tests
- [ElevenLabs WebSocket API docs](https://elevenlabs.io/docs/api-reference/text-to-speech/v-1-text-to-speech-voice-id-stream-input) -- WS protocol spec, message format, voice_settings

### Secondary (MEDIUM confidence)
- Installed package versions: httpx 0.28.1, websockets 16.0 (verified via pip show)

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH - no new dependencies; all libraries already installed and in use
- Architecture: HIGH - extending existing protocol pattern; all integration points inspected
- Pitfalls: HIGH - six of seven pitfalls identified from actual code patterns in the codebase; WS API format verified against official docs

**Research date:** 2026-03-26
**Valid until:** 2026-04-26 (stable domain; ElevenLabs WS API is established)
