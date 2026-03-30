# Technology Stack -- v1.2 Consolidation Additions

**Project:** MERLIN v1.2
**Researched:** 2026-03-26
**Focus:** TTS abstraction integration, FastAPI DI refactor, WebSocket testing, CI/CD

## Recommended Stack Additions

### FastAPI Dependency Injection Refactor

| Technology | Version | Purpose | Why |
|------------|---------|---------|-----|
| FastAPI `app.state` + `Depends()` | (built-in) | Replace module-level globals in `web/server.py` | Native FastAPI pattern -- no new deps. Lifespan creates singletons on `app.state`; `Depends()` callables expose them to routes. Well-documented, well-tested, zero learning curve for the team |

**Pattern:** Use the lifespan context manager to create singletons (TTS client, Claude client, telemetry client, context store, flight phase detector) and store them on `app.state`. Write thin `Depends()` functions that pull from `request.app.state`. This replaces the 7+ module-level globals in `web/server.py` with testable, overridable dependencies.

**Confidence:** HIGH -- this is the documented FastAPI pattern from official docs.

**Why NOT svcs (hynek's service locator library, v25.1.0):** svcs adds a service registry abstraction (`svcs.fastapi.lifespan` + `svcs.fastapi.DepContainer`) that is elegant for large apps with many services. MERLIN has ~5 singletons. The native `app.state` + `Depends()` pattern handles this without adding a dependency. If the service count grows significantly in future milestones, svcs becomes worth reconsidering.

**Why NOT dependency-injector:** Heavy framework with containers, providers, and wiring. Overkill for this project's needs. Adds complexity without proportional benefit.

### WebSocket Testing

| Technology | Version | Purpose | Why |
|------------|---------|---------|-----|
| `httpx-ws` | >= 0.6.2 | Async WebSocket testing for FastAPI endpoints | Provides `aconnect_ws()` for true async WebSocket testing with `httpx.AsyncClient`. The Starlette `TestClient.websocket_connect()` is synchronous and blocks the event loop -- problematic for testing barge-in, concurrent streams, and cancellation tokens |
| `pytest-asyncio` | >= 0.24 | Async test runner | Already in use. `asyncio_mode = "auto"` already configured in `pyproject.toml` |
| `respx` | >= 0.21 | Mock httpx requests (ElevenLabs, Whisper) | Already in use. Continue using for mocking outbound HTTP in TTS and STT tests |

**Confidence:** MEDIUM -- `httpx-ws` is the established library for this (referenced in httpx's own third-party packages page), but the project could also use Starlette's sync `TestClient.websocket_connect()` for simpler tests. Recommend `httpx-ws` specifically because MERLIN's WebSocket handlers involve async cancellation (barge-in) that requires a real async test client.

**Testing pattern for WebSocket endpoints:**

```python
import pytest
from httpx import ASGITransport, AsyncClient
from httpx_ws import aconnect_ws
from httpx_ws.transport import ASGIWebSocketTransport

@pytest.fixture
async def client(app):
    """Async client with dependency overrides for testing."""
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as ac:
        yield ac

@pytest.fixture
async def ws_client(app):
    """WebSocket client for testing WS endpoints."""
    async with AsyncClient(
        transport=ASGIWebSocketTransport(app=app),
        base_url="http://test",
    ) as ac:
        yield ac
```

**Why NOT plain `TestClient.websocket_connect()`:** Starlette's `TestClient` runs in a background thread with its own event loop. This makes it impossible to test async interactions like barge-in cancellation, concurrent WebSocket messages, or race conditions between chat and telemetry streams -- which are exactly the scenarios that need test coverage in `web/server.py`.

### TTS Abstraction Integration

| Technology | Version | Purpose | Why |
|------------|---------|---------|-----|
| `orchestrator.tts` (existing) | internal | TTS client protocol + factory | Already built with `TTSClient` protocol, `ElevenLabsClient`, `KokoroClient`, and `create_tts_client()` factory. No new libraries needed |
| `httpx.AsyncClient` (persistent) | >= 0.27.0 | Connection pooling for TTS clients | The existing `ElevenLabsClient` creates a new `httpx.AsyncClient` per call. Refactor to accept a shared client via constructor injection for connection reuse |

**Confidence:** HIGH -- the abstraction layer already exists. This is pure integration work.

**Key integration point:** The `ElevenLabsClient` currently creates a new `httpx.AsyncClient(timeout=30.0)` in both `synthesize()` and `synthesize_stream()`. This defeats connection pooling. Refactor to accept an `httpx.AsyncClient` in the constructor (injected by the lifespan), matching how the web server already manages `_tts_client` and `_whisper_client` globals.

**What changes:**
1. `ElevenLabsClient.__init__()` accepts optional `client: httpx.AsyncClient | None`
2. `KokoroClient.__init__()` same pattern
3. Lifespan creates the httpx client, passes to TTS client, stores TTS client on `app.state`
4. `web/server.py` replaces inline httpx TTS calls with `app.state.tts_client.synthesize_stream()`
5. `orchestrator/voice.py` uses `create_tts_client(settings)` instead of inline httpx calls

### CI/CD Pipeline

| Technology | Version | Purpose | Why |
|------------|---------|---------|-----|
| GitHub Actions | N/A | CI/CD platform | Already using GitHub for hosting. Native integration, free for public repos, generous minutes for private |
| `actions/checkout` | v4 | Repo checkout | Standard |
| `actions/setup-python` | v5 | Python environment | Supports 3.11+ matrix |
| `actions/setup-dotnet` | v4 | .NET 8 environment | Required for MSFS adapter build/test |
| `dorny/paths-filter` | v3 | Monorepo path-based job triggers | Only run Python CI when Python files change, only run .NET CI when adapter files change. Saves CI minutes and reduces noise |
| `actions/cache` | v4 | pip and NuGet cache | Faster builds via dependency caching |

**Confidence:** HIGH -- GitHub Actions is the obvious choice given the project already lives on GitHub.

**Workflow structure (3 separate workflows, not 1 monolith):**

1. **`python-ci.yml`** -- Triggers on `orchestrator/**`, `telemetry-service/**`, `web/**`, `tests/**` changes
   - Matrix: Python 3.11, 3.12
   - Jobs: lint (ruff), test-orchestrator, test-telemetry, test-web
   - Uses `dorny/paths-filter` to skip unchanged components

2. **`dotnet-ci.yml`** -- Triggers on `adapters/msfs/**` changes
   - .NET 8.0
   - Jobs: build, test
   - Note: SimConnect DLL won't be available in CI. Tests must mock SimConnect or be marked `[Trait("Category", "Integration")]` and skipped in CI

3. **`docker-build.yml`** -- Triggers on Dockerfile or compose changes
   - Builds Docker images to verify they compile
   - Does NOT push to registry (no deployment target yet)

**Why NOT a single workflow with matrix:** The Python and C# pipelines have different triggers, different setup, different caching strategies. Separate workflows are cleaner and allow independent re-runs.

**Why NOT Nx/Turborepo:** These are JavaScript-ecosystem monorepo tools. `dorny/paths-filter` achieves the same selective building without adding a build orchestrator dependency.

## Alternatives Considered

| Category | Recommended | Alternative | Why Not |
|----------|-------------|-------------|---------|
| DI framework | Native `app.state` + `Depends()` | `svcs` (v25.1.0) | Only 5 singletons; native pattern sufficient. Revisit if service count grows |
| DI framework | Native `app.state` + `Depends()` | `dependency-injector` | Heavy framework, steep learning curve, overkill |
| WS testing | `httpx-ws` (>= 0.6.2) | `TestClient.websocket_connect()` | Sync-only, can't test async cancellation patterns |
| WS testing | `httpx-ws` (>= 0.6.2) | `websockets` library directly | Requires starting a real server; `httpx-ws` tests in-process via ASGI transport |
| CI platform | GitHub Actions | GitLab CI, CircleCI | Project is on GitHub; native integration wins |
| Path filtering | `dorny/paths-filter` v3 | GitHub's built-in `paths:` trigger | Built-in `paths:` only works at workflow level, not job level. Can't selectively skip jobs within a workflow |
| TTS abstraction | Existing `TTSClient` protocol | `RealtimeTTS` library | External library adds dependency for something already built. MERLIN's protocol is simpler and purpose-built |

## New Dev Dependencies to Add

```bash
# Web server testing (add to web/requirements.txt or new pyproject.toml)
pip install httpx-ws>=0.6.2 pytest>=8.0 pytest-asyncio>=0.24 pytest-mock>=3.14 respx>=0.21

# No new production dependencies required
```

## Installation Summary

No new production dependencies. The TTS abstraction already exists. DI uses built-in FastAPI. CI/CD is configuration-only (YAML files).

New dev-only dependencies:
- `httpx-ws >= 0.6.2` -- WebSocket testing

## Sources

- [FastAPI Dependencies (official docs)](https://fastapi.tiangolo.com/tutorial/dependencies/)
- [FastAPI Testing WebSockets (official docs)](https://fastapi.tiangolo.com/advanced/testing-websockets/)
- [httpx-ws GitHub](https://github.com/frankie567/httpx-ws)
- [httpx-ws PyPI](https://pypi.org/project/httpx-ws/)
- [svcs FastAPI integration docs](https://svcs.hynek.me/en/stable/integrations/fastapi.html)
- [dorny/paths-filter GitHub](https://github.com/dorny/paths-filter)
- [actions/setup-dotnet GitHub](https://github.com/actions/setup-dotnet)
- [GitHub Actions monorepo CI/CD guide (General Reasoning)](https://generalreasoning.com/blog/2025/03/22/github-actions-vanilla-monorepo.html)
- [FastAPI singleton + DI patterns (Medium)](https://medium.com/@hieutrantrung.it/using-fastapi-like-a-pro-with-singleton-and-dependency-injection-patterns-28de0a833a52)
- [Starlette TestClient docs](https://www.starlette.io/testclient/)

---

*Stack research: 2026-03-26*
