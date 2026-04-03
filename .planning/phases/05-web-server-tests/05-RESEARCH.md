# Phase 5: Web Server Tests - Research

**Researched:** 2026-03-26
**Domain:** FastAPI WebSocket/HTTP testing with mocked dependencies
**Confidence:** HIGH

## Summary

Phase 5 adds automated test coverage for all 6 endpoints in `web/server.py`. The web server uses a FastAPI `AppState` dataclass injected via `Depends(get_app_state)` (HTTP) and `Depends(get_ws_app_state)` (WebSocket), both established in Phase 4. This DI pattern makes testing straightforward via `app.dependency_overrides`.

Two testing approaches are viable. For WebSocket endpoints (`/ws/chat`, `/ws/telemetry`), use Starlette's `TestClient.websocket_connect()` which is synchronous, mature, and natively supports `dependency_overrides`. For REST endpoints (`/api/status`, `/api/transcribe`, `/api/tts`), use `httpx.AsyncClient` with `ASGITransport` for async testing. The `httpx-ws` library provides `aconnect_ws` with `ASGIWebSocketTransport` for async WebSocket tests but has known compatibility edge cases; the simpler `TestClient` approach is more reliable for this codebase's needs.

**Primary recommendation:** Use `TestClient.websocket_connect()` for WebSocket tests and `httpx.AsyncClient(transport=ASGITransport(app=app))` for REST tests. Mock all external clients via `dependency_overrides[get_app_state]` returning a pre-built `AppState` with `AsyncMock`/`MagicMock` fields.

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions
- **D-01:** Tests live in `web/tests/` with a dedicated `conftest.py` containing AppState fixtures and test app setup.
- **D-02:** Use `httpx` + `httpx-ws` for async HTTP and WebSocket testing. Async-native, matches the codebase pattern.
- **D-03:** Add `httpx-ws` to dev dependencies (web/requirements.txt or a test extras section).
- **D-04:** Tests must be runnable via `pytest web/tests/` independently from orchestrator tests.
- **D-05:** Tier 1 -- Fast mock tests (branch commits): Full mock via `dependency_overrides[get_app_state]` returning a mock `AppState`. No Docker, no APIs, runs in seconds. Primary tests.
- **D-06:** Tier 2 -- Integration tests (PRs only): Use real TTSClient/WhisperClient pointed at Docker services. Mark with `@pytest.mark.integration`.
- **D-07:** Default `pytest` run (no markers) executes only Tier 1 fast tests. Integration tests require explicit `pytest -m integration`.
- **D-08:** Create a `conftest.py` fixture that builds a mock `AppState` with AsyncMock clients (tts_client, whisper_client, claude_client, sim_client, context_store, settings).
- **D-09:** Use `app.dependency_overrides[get_app_state] = lambda: mock_state` and `app.dependency_overrides[get_ws_app_state] = lambda: mock_state` to inject mocks.
- **D-10:** All 7 requirements (WTST-01 through WTST-07) treated equally. No special ordering.
- **D-11:** Tier 1 test suite must run in under 30 seconds.

### Claude's Discretion
- Exact test function names and organization within `web/tests/`
- Whether to split into multiple test files (e.g., `test_rest.py`, `test_websocket.py`, `test_barge_in.py`) or one file
- How to simulate barge-in in tests (task cancellation timing)
- Integration test fixture design (Docker service health checks before running)

### Deferred Ideas (OUT OF SCOPE)
None -- discussion stayed within phase scope.
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| WTST-01 | Chat WebSocket flow tested (send message, receive streaming response) | TestClient.websocket_connect + mock claude_client.chat yielding chunks |
| WTST-02 | Barge-in interruption tested (new message cancels in-flight response) | Send second text message while first response streams; verify "interrupted" + "done" sequence |
| WTST-03 | TTS streaming tested (audio chunks delivered via WebSocket) | Mock tts_client for REST fallback path; verify tts_audio JSON + binary frame sequence |
| WTST-04 | Transcription endpoint tested (audio upload, confidence scoring) | httpx AsyncClient POST multipart with mock whisper_client.transcribe_with_confidence |
| WTST-05 | TTS phrase cache tested (cache hits return pre-generated audio) | Pre-populate AppState.tts_cache dict, POST /api/tts with cached phrase, verify no tts_client call |
| WTST-06 | Telemetry WebSocket proxy tested | TestClient.websocket_connect; mock the upstream `websockets.connect` call |
| WTST-07 | Status endpoint tested (subsystem health reporting) | httpx AsyncClient GET /api/status with mock AppState fields |
</phase_requirements>

## Standard Stack

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| pytest | >=8.0 | Test framework | Already used across project |
| pytest-asyncio | >=0.24 | Async test support | Already in orchestrator dev deps |
| httpx | 0.28.1 (installed) | Async HTTP test client | Already a project dependency |
| httpx-ws | 0.9.0 | WebSocket testing transport for httpx | Per D-02, adds ASGIWebSocketTransport |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| unittest.mock | stdlib | AsyncMock, MagicMock, patch | All mock AppState fields |
| fastapi.testclient | (bundled) | Sync WebSocket testing | Fallback for simple WS tests |
| respx | >=0.21 | Mock httpx requests | Integration test HTTP mocking (already in orchestrator test deps) |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| httpx-ws ASGIWebSocketTransport | TestClient.websocket_connect() | TestClient is sync, simpler, but D-02 specifies httpx-ws |
| Manual AsyncMock setup | pytest-mock fixtures | AsyncMock from stdlib is sufficient; no extra dep needed |

**Installation (for web/tests):**
```bash
pip install httpx-ws==0.9.0 pytest pytest-asyncio
```

**Version verification:** httpx-ws 0.9.0 is the latest release (confirmed via pip index). httpx 0.28.1 is installed.

## Architecture Patterns

### Recommended Project Structure
```
web/
├── tests/
│   ├── __init__.py
│   ├── conftest.py          # AppState mock fixture, test app setup, overrides
│   ├── test_rest.py          # /api/status, /api/transcribe, /api/tts
│   ├── test_chat_ws.py       # /ws/chat round-trip + barge-in
│   └── test_telemetry_ws.py  # /ws/telemetry proxy
├── server.py
├── requirements.txt
└── static/
```

### Pattern 1: AppState Mock Fixture with dependency_overrides
**What:** A `conftest.py` fixture that creates a mock `AppState`, overrides both DI functions, and yields a test client.
**When to use:** Every Tier 1 test.
**Example:**
```python
# web/tests/conftest.py
import pytest
from unittest.mock import AsyncMock, MagicMock
from dataclasses import dataclass, field
from web.server import app, AppState, get_app_state, get_ws_app_state

@pytest.fixture
def mock_app_state():
    """Build a fully mocked AppState for Tier 1 tests."""
    state = AppState(
        settings=MagicMock(
            elevenlabs_api_key="test-key",
            voice_id="test-voice",
            elevenlabs_model_id="eleven_multilingual_v2",
            claude_model="claude-sonnet-4-20250514",
            telemetry_service_url="ws://localhost:8080/ws/telemetry",
            whisper_url="http://localhost:9090",
            chromadb_url="http://localhost:8000",
            log_level="DEBUG",
        ),
    )
    state.whisper_client = AsyncMock()
    state.claude_client = AsyncMock()
    state.tts_client = AsyncMock()
    state.sim_client = MagicMock()
    state.context_store = MagicMock(available=True, document_count=42)
    return state


@pytest.fixture
def test_app(mock_app_state):
    """Override DI and return the app for testing."""
    app.dependency_overrides[get_app_state] = lambda: mock_app_state
    app.dependency_overrides[get_ws_app_state] = lambda: mock_app_state
    yield app
    app.dependency_overrides.clear()
```

### Pattern 2: REST Endpoint Testing with httpx AsyncClient
**What:** Use `httpx.AsyncClient` with `ASGITransport` for async HTTP tests.
**When to use:** Testing `/api/status`, `/api/transcribe`, `/api/tts`.
**Example:**
```python
# Source: FastAPI async testing docs
import httpx
from httpx import ASGITransport

@pytest.mark.asyncio
async def test_status_endpoint(test_app, mock_app_state):
    mock_app_state.whisper_client.is_available.return_value = True
    transport = ASGITransport(app=test_app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/status")
    assert resp.status_code == 200
    data = resp.json()
    assert data["whisper_available"] is True
    assert data["chromadb_available"] is True
```

### Pattern 3: WebSocket Testing with httpx-ws ASGIWebSocketTransport
**What:** Use `httpx-ws` transport for async WebSocket testing.
**When to use:** Testing `/ws/chat` and `/ws/telemetry`.
**Example:**
```python
# Source: httpx-ws ASGI docs
import httpx
from httpx_ws import aconnect_ws
from httpx_ws.transport import ASGIWebSocketTransport

@pytest.mark.asyncio
async def test_chat_round_trip(test_app, mock_app_state):
    # Mock claude_client.chat to yield text chunks
    async def fake_chat(text, sim_state=None):
        yield "Roger"
        yield " that."
    mock_app_state.claude_client.chat = fake_chat
    # Disable TTS for simple round-trip test
    mock_app_state.settings.elevenlabs_api_key = ""

    async with httpx.AsyncClient(
        transport=ASGIWebSocketTransport(test_app)
    ) as client:
        async with aconnect_ws("http://test/ws/chat", client) as ws:
            await ws.send_json({"text": "Hello MERLIN"})
            # Collect streamed responses
            messages = []
            while True:
                msg = await ws.receive_json()
                messages.append(msg)
                if msg.get("type") in ("done", "error"):
                    break
            text_chunks = [m["content"] for m in messages if m["type"] == "text"]
            assert "".join(text_chunks) == "Roger that."
```

### Pattern 4: Barge-in Cancellation Test
**What:** Verify that sending a second message during an active response cancels the first.
**When to use:** WTST-02 requirement.
**Example:**
```python
@pytest.mark.asyncio
async def test_barge_in(test_app, mock_app_state):
    # Mock a slow-streaming Claude response
    async def slow_chat(text, sim_state=None):
        for word in ["This ", "is ", "a ", "long ", "response."]:
            await asyncio.sleep(0.05)  # Simulate streaming delay
            yield word
    mock_app_state.claude_client.chat = slow_chat
    mock_app_state.settings.elevenlabs_api_key = ""  # No TTS

    async with httpx.AsyncClient(
        transport=ASGIWebSocketTransport(test_app)
    ) as client:
        async with aconnect_ws("http://test/ws/chat", client) as ws:
            # Send first message
            await ws.send_json({"text": "First question"})
            # Wait for streaming to start
            first_msg = await ws.receive_json()
            assert first_msg["type"] == "text"

            # Barge in with second message
            await ws.send_json({"text": "Interrupt!"})

            # Collect all remaining messages
            messages = []
            while True:
                msg = await ws.receive_json()
                messages.append(msg)
                if msg.get("type") == "done":
                    break
            types = [m["type"] for m in messages]
            assert "interrupted" in types
```

### Anti-Patterns to Avoid
- **Starting real services in tests:** Never start Docker, Whisper, ChromaDB, or ElevenLabs in Tier 1 tests. The entire point of DI overrides is to avoid this.
- **Testing the lifespan context manager:** Do NOT test `lifespan()` -- it creates real clients. Tests bypass lifespan via `dependency_overrides`.
- **Using `app=app` with httpx.AsyncClient for WS:** This triggers the deprecated ASGI mounting path. Use `ASGIWebSocketTransport(app)` explicitly.
- **Blocking event loop in WebSocket tests:** Async generators for `claude_client.chat` must use `asyncio.sleep()` not `time.sleep()` to allow task switching needed for barge-in.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| WebSocket test transport | Custom ASGI adapter | `httpx-ws` `ASGIWebSocketTransport` | Handles WS upgrade negotiation correctly |
| HTTP test transport | Manual request crafting | `httpx.ASGITransport` | Standard FastAPI testing pattern |
| Mock AppState builder | Ad-hoc mocks per test | Shared `conftest.py` fixture | Consistency, DRY, matches orchestrator pattern |
| Barge-in simulation | Thread-based timing hacks | `asyncio.sleep` in mock generator + immediate second send | Natural async flow, no race conditions |

**Key insight:** The `dependency_overrides` pattern eliminates the need for any test-specific code in `server.py`. Tests inject mocks at the DI boundary, testing real routing, serialization, and flow control while replacing all I/O.

## Common Pitfalls

### Pitfall 1: Lifespan Runs During Testing
**What goes wrong:** Tests fail because `lifespan()` tries to connect to real Whisper/ChromaDB/telemetry services.
**Why it happens:** By default, `TestClient` and httpx transports execute the lifespan.
**How to avoid:** httpx `ASGITransport(app=app)` does NOT run lifespan by default. For `TestClient`, use `with TestClient(app, raise_server_exceptions=False) as client:` or ensure `dependency_overrides` are set BEFORE the client context opens. The `ASGIWebSocketTransport` also skips lifespan.
**Warning signs:** `ConnectionRefusedError` or timeout in test setup.

### Pitfall 2: WebSocket Test Hangs on receive
**What goes wrong:** Test hangs forever waiting for a WebSocket message.
**Why it happens:** The server-side handler is waiting for something (Claude stream, TTS) that never completes because mocks aren't configured to terminate.
**How to avoid:** Always ensure mock async generators have a finite number of yields. Set `elevenlabs_api_key=""` to disable TTS in tests that don't test TTS. Use `asyncio.wait_for()` with a timeout in tests.
**Warning signs:** Test takes > 5 seconds, pytest hangs.

### Pitfall 3: Module-Level Settings Import
**What goes wrong:** `web/server.py` calls `load_settings()` at module import time (line 64). This reads `.env` and may fail without `ANTHROPIC_API_KEY`.
**Why it happens:** Module-level execution happens before test fixtures run.
**How to avoid:** Set `ANTHROPIC_API_KEY=test-key` as an env var in the test environment (via `conftest.py` `monkeypatch` or `pytest.ini` `env` setting), OR use a `conftest.py` fixture with `autouse=True` that patches the env before importing.
**Warning signs:** `ValidationError` on Settings during test collection.

### Pitfall 4: Missing pytest.ini / pyproject.toml for web/tests
**What goes wrong:** `pytest web/tests/` doesn't find tests or uses wrong asyncio mode.
**Why it happens:** No `pyproject.toml` or `pytest.ini` in `web/`.
**How to avoid:** Create `web/pyproject.toml` (or `web/pytest.ini`) with `asyncio_mode = "auto"` and `testpaths = ["tests"]` and the `integration` marker definition. Alternatively, add a `conftest.py` that configures pytest-asyncio mode.
**Warning signs:** `PytestUnraisableExceptionWarning` or tests not collected.

### Pitfall 5: dependency_overrides Not Cleared
**What goes wrong:** Test pollution -- one test's mocks leak into another.
**Why it happens:** `dependency_overrides` is a mutable dict on the app singleton.
**How to avoid:** Always clear overrides in fixture teardown: `yield app; app.dependency_overrides.clear()`.
**Warning signs:** Tests pass individually but fail when run together.

### Pitfall 6: Telemetry WebSocket Test Requires Upstream Mock
**What goes wrong:** `/ws/telemetry` endpoint tries to `websockets.connect()` to the real telemetry service.
**Why it happens:** The telemetry proxy uses the `websockets` library directly (not through AppState), connecting to `state.settings.telemetry_service_url`.
**How to avoid:** Patch `websockets.connect` or `ws_lib.connect` in tests. The mock should yield messages and then close.
**Warning signs:** `ConnectionRefusedError` in telemetry WS tests.

## Code Examples

### Mock Settings Object
```python
# Minimal mock Settings for tests. Uses MagicMock with explicit attributes
# to avoid needing real env vars or .env file.
from unittest.mock import MagicMock

def make_test_settings(**overrides):
    defaults = {
        "elevenlabs_api_key": "test-key",
        "voice_id": "test-voice",
        "elevenlabs_model_id": "eleven_multilingual_v2",
        "claude_model": "claude-sonnet-4-20250514",
        "telemetry_service_url": "ws://localhost:8080/ws/telemetry",
        "whisper_url": "http://localhost:9090",
        "chromadb_url": "http://localhost:8000",
        "log_level": "DEBUG",
    }
    defaults.update(overrides)
    mock = MagicMock()
    for k, v in defaults.items():
        setattr(mock, k, v)
    return mock
```

### Mock WhisperClient transcribe_with_confidence
```python
from unittest.mock import AsyncMock, MagicMock

# Create a mock that returns a TranscriptionResult-like object
whisper_mock = AsyncMock()
result = MagicMock(text="Set heading three six zero", confidence=0.85)
whisper_mock.transcribe_with_confidence.return_value = result
whisper_mock.is_available.return_value = True
```

### Multipart File Upload for /api/transcribe
```python
@pytest.mark.asyncio
async def test_transcribe(test_app, mock_app_state):
    result_mock = MagicMock(text="Roger", confidence=0.9)
    mock_app_state.whisper_client.transcribe_with_confidence.return_value = result_mock

    transport = ASGITransport(app=test_app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            "/api/transcribe",
            files={"file": ("audio.wav", b"RIFF" + b"\x00" * 100, "audio/wav")},
        )
    assert resp.status_code == 200
    assert resp.json()["text"] == "Roger"
    assert resp.json()["confidence"] == 0.9
```

### TTS Cache Hit Test
```python
@pytest.mark.asyncio
async def test_tts_cache_hit(test_app, mock_app_state):
    # Pre-populate cache with a known phrase
    mock_app_state.tts_cache["Roger."] = b"\xff\xfb\x90\x00" * 100  # fake MP3

    transport = ASGITransport(app=test_app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post("/api/tts", json={"text": "Roger."})
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "audio/mpeg"
    # tts_client.post should NOT have been called (cache hit)
    mock_app_state.tts_client.post.assert_not_called()
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| `TestClient(app)` sync only | `httpx.AsyncClient` + `ASGITransport` | httpx 0.23+ | Native async test support |
| `app=app` kwarg on AsyncClient | `transport=ASGITransport(app)` | httpx 0.27+ (deprecated app=) | Must use explicit transport |
| No WS test support in httpx | `httpx-ws` `ASGIWebSocketTransport` | httpx-ws 0.4+ | Async WS testing without running server |

**Deprecated/outdated:**
- `httpx.AsyncClient(app=app)`: The `app=` parameter is deprecated in httpx 0.27+. Use `ASGITransport` explicitly.
- `TestClient` for async tests: Still works but is synchronous under the hood. Use `httpx.AsyncClient` for truly async tests.

## Open Questions

1. **httpx-ws + lifespan interaction**
   - What we know: `ASGIWebSocketTransport` should skip lifespan by default. httpx `ASGITransport` has a `raise_app_exceptions` param but no explicit lifespan control.
   - What's unclear: Whether `ASGIWebSocketTransport` handles `dependency_overrides` identically to regular `ASGITransport`. The D-02 decision mandates httpx-ws, so we use it.
   - Recommendation: Test early. If `ASGIWebSocketTransport` causes lifespan issues, fall back to `TestClient.websocket_connect()` for WebSocket tests while using `AsyncClient` for REST (still satisfying the httpx requirement from D-02).

2. **Telemetry WS proxy test complexity**
   - What we know: `/ws/telemetry` calls `ws_lib.connect(telemetry_url)` directly, not through an injected client.
   - What's unclear: Whether patching `websockets.connect` cleanly in an async test context works with httpx-ws transport.
   - Recommendation: Use `unittest.mock.patch("web.server.ws_lib.connect")` as an async context manager returning a mock WebSocket.

## Sources

### Primary (HIGH confidence)
- `web/server.py` -- Full source code of the target module, read directly
- `orchestrator/tests/conftest.py` -- Existing project test patterns
- `orchestrator/tests/test_whisper_client.py` -- AsyncMock testing patterns
- `telemetry-service/tests/test_service.py` -- FastAPI TestClient + websocket_connect pattern
- `orchestrator/pyproject.toml` -- pytest config, markers, asyncio_mode

### Secondary (MEDIUM confidence)
- [httpx-ws ASGI testing docs](https://frankie567.github.io/httpx-ws/usage/asgi/) -- ASGIWebSocketTransport usage pattern
- [FastAPI WebSocket testing docs](https://fastapi.tiangolo.com/advanced/testing-websockets/) -- TestClient.websocket_connect
- [httpx-ws GitHub Discussion #67](https://github.com/frankie567/httpx-ws/discussions/67) -- Known issue with `app=` parameter (must use transport instead)

### Tertiary (LOW confidence)
- [FastAPI dependency injection testing patterns](https://thelinuxcode.com/dependency-injection-in-fastapi-2026-playbook-for-modular-testable-apis/) -- General DI override guidance

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH - all libraries verified installed or available via pip, versions confirmed
- Architecture: HIGH - DI pattern is already in server.py (Phase 4), test patterns match existing project conventions
- Pitfalls: HIGH - module-level Settings import and telemetry WS proxy are concrete issues visible in source code

**Research date:** 2026-03-26
**Valid until:** 2026-04-26 (stable domain, no fast-moving changes expected)
