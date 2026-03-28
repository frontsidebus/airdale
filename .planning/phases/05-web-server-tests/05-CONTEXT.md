# Phase 5: Web Server Tests - Context

**Gathered:** 2026-03-28
**Status:** Ready for planning

<domain>
## Phase Boundary

Add automated test coverage for all critical web server paths. Two test tiers: fast mock tests (branch commits) using fully mocked AppState, and integration tests (PRs) using real client implementations against Docker services. All 7 test requirements (WTST-01 through WTST-07) treated with equal priority.

</domain>

<decisions>
## Implementation Decisions

### Test Infrastructure
- **D-01:** Tests live in `web/tests/` with a dedicated `conftest.py` containing AppState fixtures and test app setup.
- **D-02:** Use `httpx` + `httpx-ws` for async HTTP and WebSocket testing. Async-native, matches the codebase pattern.
- **D-03:** Add `httpx-ws` to dev dependencies (web/requirements.txt or a test extras section).
- **D-04:** Tests must be runnable via `pytest web/tests/` independently from orchestrator tests.

### Two-Tier Testing Strategy
- **D-05:** **Tier 1 — Fast mock tests (branch commits):** Full mock via `dependency_overrides[get_app_state]` returning a mock `AppState` with fake TTSClient, WhisperClient, ClaudeClient, TelemetryClient. No Docker, no APIs, runs in seconds. These are the primary tests.
- **D-06:** **Tier 2 — Integration tests (PRs only):** Use real TTSClient/WhisperClient pointed at Docker services (Whisper, ChromaDB). Mark with `@pytest.mark.integration` so they can be selectively run. Phase 6 CI/CD will set up Docker services for PR jobs.
- **D-07:** Default `pytest` run (no markers) executes only Tier 1 fast tests. Integration tests require explicit `pytest -m integration`.

### Mock Strategy
- **D-08:** Create a `conftest.py` fixture that builds a mock `AppState` with:
  - `tts_client`: AsyncMock with `synthesize()` returning fake MP3 bytes, `synthesize_stream()` yielding chunks
  - `whisper_client`: AsyncMock with `transcribe_with_confidence()` returning a fake `TranscriptionResult`
  - `claude_client`: AsyncMock with `chat()` yielding text chunks (simulates streaming)
  - `sim_client`: Mock with `get_state()` returning a fixture `SimState`
  - `context_store`: Mock with `available = True`
  - `settings`: Real `Settings` instance with test values
- **D-09:** Use `app.dependency_overrides[get_app_state] = lambda: mock_state` and `app.dependency_overrides[get_ws_app_state] = lambda: mock_state` to inject mocks.

### Coverage Priority
- **D-10:** All 7 requirements (WTST-01 through WTST-07) treated equally. No special ordering.

### Performance Target
- **D-11:** Tier 1 test suite must run in under 30 seconds (per ROADMAP success criteria).

### Claude's Discretion
- Exact test function names and organization within `web/tests/`
- Whether to split into multiple test files (e.g., `test_rest.py`, `test_websocket.py`, `test_barge_in.py`) or one file
- How to simulate barge-in in tests (task cancellation timing)
- Integration test fixture design (Docker service health checks before running)

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Web Server (target)
- `web/server.py` — Full file. Focus on: `AppState` dataclass, `get_app_state`/`get_ws_app_state` dependencies, all 6 endpoints, `_stream_response`, `_tts_stream_to_browser`, `_transcribe_with_confidence`

### Phase 4 DI Pattern (enables testing)
- `web/server.py:get_app_state` — HTTP route dependency
- `web/server.py:get_ws_app_state` — WebSocket route dependency
- FastAPI `dependency_overrides` — standard test override pattern

### Existing Test Patterns
- `orchestrator/tests/conftest.py` — Existing conftest pattern for the project
- `orchestrator/tests/test_whisper_client.py` — Async test pattern with respx mocking
- `telemetry-service/tests/test_service.py` — FastAPI app testing pattern

### Requirements
- WTST-01: Chat WebSocket round-trip
- WTST-02: Barge-in interruption
- WTST-03: TTS streaming
- WTST-04: Transcription endpoint
- WTST-05: TTS phrase cache
- WTST-06: Telemetry WebSocket proxy
- WTST-07: Status endpoint

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `dependency_overrides` — FastAPI's built-in test override mechanism, perfect for AppState mocking
- `orchestrator/tests/conftest.py` — Project's existing conftest pattern
- `respx` — Already in dev deps, can mock httpx calls for integration tests

### Established Patterns
- `pytest-asyncio` for async tests (used throughout orchestrator)
- `pytest.mark.integration` for excluding slow tests (already configured in orchestrator pyproject.toml)
- `AsyncMock` from unittest.mock for async client mocking

### Endpoints to Test (6 total)
- `GET /` — Static file serving (trivial)
- `GET /api/status` — Health status of all subsystems
- `POST /api/transcribe` — STT proxy (audio upload → WhisperClient)
- `POST /api/tts` — TTS proxy (text → TTSClient → audio)
- `WS /ws/telemetry` — Telemetry broadcast proxy
- `WS /ws/chat` — Chat with Claude streaming + barge-in

</code_context>

<specifics>
## Specific Ideas

- The two-tier strategy aligns with Phase 6 CI/CD: fast tests on every push, integration tests on PRs with Docker services.
- Barge-in test requires sending a second WebSocket message while the first is still streaming — this tests the cancellation flow that was human-verified in Phase 4.

</specifics>

<deferred>
## Deferred Ideas

None — discussion stayed within phase scope.

</deferred>

---

*Phase: 05-web-server-tests*
*Context gathered: 2026-03-28*
