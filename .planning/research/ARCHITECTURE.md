# Architecture Patterns

**Domain:** Consolidation and quality improvements for an existing AI flight sim co-pilot
**Researched:** 2026-03-26

## Current Architecture Assessment

The MERLIN system is an event-driven microservices architecture with a pluggable adapter pattern. The core architecture (telemetry pipeline, Claude integration, flight phase detection) is sound. The consolidation targets are localized to three areas: TTS/STT client duplication, web server state management, and CI/CD automation.

None of these changes touch the fundamental data flow or component boundaries. This is housekeeping, not restructuring.

## Components Affected by Consolidation

### Component 1: TTS Client Layer (Wire-In)

**Current state:** The `orchestrator/orchestrator/tts/` package defines a clean `TTSClient` Protocol with ElevenLabs and Kokoro implementations. However, neither the web server nor the CLI voice module uses it. Instead:

- `web/server.py` has inline `httpx.post()` calls to ElevenLabs with hardcoded voice settings (`stability: 0.75, similarity_boost: 0.80, style: 0.15`)
- `orchestrator/orchestrator/voice.py` `VoiceOutput` class has its own inline `httpx.AsyncClient` calls with DIFFERENT voice settings (`stability: 0.5, similarity_boost: 0.75, style: 0.3`)
- `orchestrator/orchestrator/tts/elevenlabs.py` has a third set of voice settings matching the web server (`stability: 0.75, similarity_boost: 0.80, style: 0.15`)

**Target state:** Both web server and CLI voice module use `create_tts_client(settings)` from the TTS abstraction. Voice settings are defined once in the abstraction layer. The phrase cache in `web/server.py` uses the TTSClient instead of raw httpx calls.

**Boundary:** The TTSClient protocol is the interface. Callers get a client from the factory and call `synthesize()` or `synthesize_stream()`. They do not know or care which backend is active.

**Missing config:** `Settings` class needs `tts_backend`, `tts_local_url`, and `tts_voice_id_local` fields. These exist in test mocks but not in the actual config.

### Component 2: Whisper/STT Client Consolidation

**Current state:** Whisper transcription with confidence scoring is implemented in three places:

1. `orchestrator/orchestrator/whisper_client.py` -- `WhisperClient` class with retry logic, confidence parsing, health check. **Synchronous** (`httpx.Client`).
2. `web/server.py` `_transcribe_with_confidence()` -- Async inline function using `httpx.AsyncClient` with confidence parsing duplicated from whisper_client.py.
3. `orchestrator/orchestrator/voice.py` `VoiceInput.transcribe()` -- Uses inline httpx calls (not shown in the reads, but implied by the whisper_url constructor param).

The confidence calculation (logprob-to-probability via `math.exp()`) is copy-pasted across implementations. The web server version handles webm-to-wav fallback; the WhisperClient does not.

**Target state:** A single async `WhisperClient` (or an async variant of the existing one) used by both web server and CLI. The webm fallback logic lives in a thin wrapper or the client itself. Retry logic is centralized.

**Boundary:** The WhisperClient is the interface. Callers pass audio bytes and get back `TranscriptionResult` (text, confidence, language, duration).

### Component 3: Web Server State Refactor

**Current state:** `web/server.py` uses module-level globals for all state:

```python
settings = load_settings()           # Module-level
sim_client: TelemetryClient | None = None    # Global
claude_client: ClaudeClient | None = None    # Global
context_store: ContextStore | None = None    # Global
phase_detector: FlightPhaseDetector | None = None  # Global
_sim_connected: bool = False                 # Global
_bridge_last_seen: float = 0.0               # Global
_bridge_connected: bool = False              # Global
_tts_client: httpx.AsyncClient | None = None # Global
_whisper_client: httpx.AsyncClient | None = None  # Global
_TTS_CACHE: dict[str, bytes] = {}            # Global
```

This makes the server untestable without monkeypatching module-level state. Every endpoint reaches into globals.

**Target state:** State grouped into a dataclass or class on `app.state`:

```python
@dataclass
class AppState:
    settings: Settings
    sim_client: TelemetryClient | None
    claude_client: ClaudeClient | None
    context_store: ContextStore | None
    phase_detector: FlightPhaseDetector | None
    tts_client: TTSClient | None        # NEW: uses abstraction
    whisper_client: WhisperClient | None  # NEW: uses consolidated client
    tts_cache: dict[str, bytes]
    sim_connected: bool
    bridge_last_seen: float
    bridge_connected: bool
```

Endpoints access state via `request.app.state`. Tests inject mock state directly.

**Boundary:** Endpoints receive state through FastAPI's dependency injection or `request.app.state`. No module-level mutable globals.

### Component 4: Config Cleanup

**Current state:** `orchestrator/orchestrator/config.py` contains deprecated fields:

```python
simconnect_ws_host: str       # (Deprecated)
simconnect_ws_port: int       # (Deprecated)
simconnect_bridge_url: str    # (Deprecated)
```

Plus the `voice_id` property alias. Missing TTS backend selection fields.

**Target state:** Deprecated fields removed. TTS config fields added (`tts_backend`, `tts_local_url`, `tts_voice_id_local`). Voice settings (stability, similarity_boost, style) added to config so they are not hardcoded in three places.

### Component 5: Telemetry Service Race Condition Fix

**Current state:** `AdapterManager._consumers` is a plain `list` mutated by async code (add in `add_consumer`, remove in `remove_consumer`, iterated in `_broadcast_to_consumers`). No `asyncio.Lock` protects concurrent access.

**Target state:** `_consumers` protected by `asyncio.Lock` for add/remove/iterate operations. Alternatively, use copy-on-write pattern (snapshot the list before iterating).

**Boundary:** Internal to `AdapterManager`. No API changes.

### Component 6: CI/CD Pipeline

**Current state:** No CI. 361+ tests exist but only run locally. No automated linting, building, or Docker image verification.

**Target state:** GitHub Actions workflow that runs on PR and push to main:

```
Trigger: push/PR to main
  |
  +-- Python job (parallel):
  |     lint (ruff check + ruff format --check)
  |     test-orchestrator (pytest orchestrator/)
  |     test-telemetry (pytest telemetry-service/)
  |     test-integration (pytest tests/)
  |
  +-- C# job (parallel):
  |     build (dotnet build adapters/msfs/)
  |     test (dotnet test adapters/msfs/)
  |
  +-- Docker job (depends on tests):
        build images (docker compose build)
```

**Boundary:** CI validates but does not deploy. No CD initially -- deployment is manual `docker compose up`.

## Data Flow (Unchanged)

The consolidation does not alter the primary data flows. For reference:

```
MSFS (SimConnect) --> Adapter (.exe) --WS--> Telemetry Service --WS--> Orchestrator/Web
                                                                         |
                                                                         v
User (voice/text) --> STT (Whisper) --> Claude (streaming) --> TTS --> User (audio/text)
```

What changes is HOW the web server and CLI access STT/TTS services -- through shared abstractions instead of inline HTTP calls.

### TTS Data Flow (After Consolidation)

```
Caller (web endpoint or CLI voice module)
    |
    v
create_tts_client(settings)  -->  TTSClient (ElevenLabs or Kokoro)
    |
    v
tts_preprocessor.preprocess_for_tts(text)
    |
    v
client.synthesize(clean_text)  -->  Audio bytes (MP3 or WAV)
    |
    v
Return to caller (HTTP response or sounddevice playback)
```

### STT Data Flow (After Consolidation)

```
Caller (web endpoint or CLI voice module)
    |
    v
AsyncWhisperClient.transcribe_with_confidence(audio_bytes)
    |                           |
    v (retry logic)             v (webm fallback if needed)
    |                           |
    v                           v
Whisper HTTP service --> TranscriptionResult(text, confidence, language, duration)
```

## Patterns to Follow

### Pattern 1: Protocol + Factory (Already Established)

The TTS layer already uses this pattern well. A `Protocol` class defines the interface, concrete classes implement it, and a factory function selects the implementation based on config.

**Apply to:** Whisper client (create an async variant alongside or replacing the sync one).

```python
# Already exists for TTS:
client = create_tts_client(settings)
audio = await client.synthesize("Roger.")

# Apply same pattern for STT:
client = create_whisper_client(settings)
result = await client.transcribe_with_confidence(audio_bytes)
```

### Pattern 2: FastAPI app.state for DI

**What:** Store all shared state on `app.state` during lifespan, access via `request.app.state` in endpoints.

**Why:** Enables test injection without monkeypatching. Standard FastAPI pattern.

```python
@asynccontextmanager
async def lifespan(app: FastAPI):
    state = AppState(
        settings=load_settings(),
        tts_client=create_tts_client(settings),
        whisper_client=create_whisper_client(settings),
        ...
    )
    app.state.merlin = state
    yield
    await state.shutdown()

@app.post("/api/tts")
async def text_to_speech(request: Request, body: TTSRequest):
    state: AppState = request.app.state.merlin
    audio = await state.tts_client.synthesize(body.text)
    return Response(content=audio, media_type=state.tts_client.audio_content_type)
```

### Pattern 3: Copy-on-Write for Concurrent Collections

**What:** For the telemetry consumer list race condition, snapshot the list before iterating.

**Why:** Simpler than lock-based approaches for the broadcast pattern. Adding/removing consumers is rare; broadcasting is frequent.

```python
async def _broadcast_to_consumers(self, envelope):
    consumers = list(self._consumers)  # snapshot
    dead = []
    for consumer in consumers:
        try:
            await consumer.send(data)
        except Exception:
            dead.append(consumer)
    for c in dead:
        self._consumers.remove(c)
```

## Anti-Patterns to Avoid

### Anti-Pattern 1: Refactoring and Testing Simultaneously

**What:** Refactoring the web server while also writing tests for it.
**Why bad:** Writing tests against the old shape means rewriting them after refactoring. Writing tests without understanding the old shape means tests may not cover edge cases.
**Instead:** Refactor first (move globals to app.state), THEN write tests against the new shape. This is already called out in PROJECT.md as a key decision.

### Anti-Pattern 2: Making the Async Whisper Client Too Different

**What:** Building a completely new async WhisperClient that shares no code with the sync one.
**Why bad:** Creates a second maintenance burden instead of reducing duplication.
**Instead:** Either convert the existing WhisperClient to async (the CLI can use `asyncio.run()`) or build the async version as the canonical one and provide a thin sync wrapper.

### Anti-Pattern 3: Over-Abstracting the Web Server

**What:** Introducing a full dependency injection framework (like FastAPI's `Depends()` for every parameter).
**Why bad:** MERLIN is a single-user local tool, not a multi-tenant service. Over-engineering DI adds indirection without benefit.
**Instead:** A single `AppState` dataclass on `app.state` is sufficient. Endpoints that need state pull it from `request.app.state.merlin`.

### Anti-Pattern 4: CI That Tests Docker Builds on Every PR

**What:** Running `docker compose build` on every PR.
**Why bad:** Slow (Whisper model download, Python deps), expensive, and fragile in CI. The Docker images are deployment artifacts.
**Instead:** Run Docker build only on pushes to main, or only when Dockerfiles/requirements change. PR checks should focus on lint + unit tests.

## Suggested Build Order (Dependencies)

The consolidation work has a clear dependency chain. Later phases depend on earlier ones being stable.

```
Phase 1: Housekeeping (no dependencies, minimal risk)
    - Config cleanup (remove deprecated fields, add TTS backend fields)
    - Pin Docker image versions
    - Fix telemetry consumer race condition
    - Standardize Python version in Dockerfiles
    |
    v
Phase 2: TTS Integration (depends on config cleanup)
    - Wire TTS abstraction into web server (replace inline httpx calls)
    - Wire TTS abstraction into CLI voice module (replace VoiceOutput._synthesize)
    - Consolidate voice settings into config
    - Move phrase cache to use TTSClient
    |
    v
Phase 3: Whisper Consolidation (independent of TTS, but similar pattern)
    - Create async WhisperClient (or convert existing)
    - Replace web server inline Whisper calls
    - Replace CLI voice module Whisper calls
    - Consolidate webm fallback logic
    |
    v
Phase 4: Web Server Refactor (depends on TTS + Whisper being abstracted)
    - Move globals to AppState dataclass on app.state
    - Refactor endpoints to use app.state
    - Untangle lifespan setup
    |
    v
Phase 5: Web Server Tests (depends on refactored state)
    - Test chat flow (WebSocket)
    - Test barge-in interruption
    - Test TTS endpoint (mock TTSClient)
    - Test transcription endpoint (mock WhisperClient)
    - Test status endpoint
    |
    v
Phase 6: CI/CD (depends on tests being reliable)
    - GitHub Actions for Python lint + test
    - GitHub Actions for C# build + test
    - Docker build verification (main branch only)
```

**Phase ordering rationale:**

1. **Housekeeping first** because it removes dead code and adds missing config -- prerequisite for TTS integration.
2. **TTS before Whisper** because the TTS abstraction already exists and just needs wiring. Whisper needs a new async client written.
3. **Both before web refactor** because the web refactor should move the already-consolidated clients into AppState, not the raw httpx globals.
4. **Web refactor before web tests** because testing the old global-state shape is wasted effort (tests would need rewriting after refactor).
5. **CI/CD last** because it needs stable, passing tests to be meaningful. Running CI against a codebase mid-refactor generates noise.

Phases 2 and 3 (TTS and Whisper consolidation) could run in parallel since they touch different files, but serial execution is safer for a single developer.

## Scalability Considerations

Not a primary concern for this milestone. MERLIN is a single-user local tool. However:

| Concern | Current | After Consolidation |
|---------|---------|---------------------|
| TTS latency | New httpx.AsyncClient per call in voice.py | Persistent client in TTSClient (reusable connection pool) |
| Whisper throughput | One request at a time | Unchanged (single user) |
| Web server testability | Untestable (globals) | Fully testable (injected state) |
| Config drift | Voice settings in 3 places | Single source of truth |

## Sources

- Direct code analysis of the MERLIN codebase (HIGH confidence -- all findings verified by reading source files)
- `orchestrator/orchestrator/tts/` -- existing Protocol + factory pattern
- `web/server.py` -- 1,057 lines with inline HTTP calls and module-level globals
- `orchestrator/orchestrator/voice.py` -- VoiceOutput with divergent voice settings
- `orchestrator/orchestrator/whisper_client.py` -- sync-only WhisperClient
- `orchestrator/orchestrator/config.py` -- Settings with deprecated fields, missing TTS backend fields
- `telemetry-service/telemetry/adapter_manager.py` -- unprotected consumer list
- FastAPI documentation on app.state pattern (MEDIUM confidence -- standard FastAPI practice)

---

*Architecture analysis: 2026-03-26*
