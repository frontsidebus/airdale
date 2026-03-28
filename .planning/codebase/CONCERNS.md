# Codebase Concerns

**Analysis Date:** 2026-03-26

## Tech Debt

**Deprecated Legacy SimConnect Bridge Config:**
- Issue: `orchestrator/orchestrator/config.py` still carries `simconnect_ws_host`, `simconnect_ws_port`, and `simconnect_bridge_url` fields marked as deprecated, along with a `_build_derived` validator that constructs the legacy URL. `sim_client.py` line 526 exports a `SimConnectClient = TelemetryClient` backward-compat alias.
- Files: `orchestrator/orchestrator/config.py` (lines 62-73), `orchestrator/orchestrator/sim_client.py` (line 526)
- Impact: Confusing for new developers; extra config fields that serve no current purpose. The docker-compose still sets `SIMCONNECT_BRIDGE_URL` (line 127).
- Fix approach: Remove deprecated fields from `Settings`, remove the alias from `sim_client.py`, and clean up `docker-compose.yml`.

**Empty Test File Left Behind:**
- Issue: `adapters/msfs/SimConnectBridge.Tests/WebSocketServerTests.cs` is a 3-line file that only contains a comment saying "this file is intentionally left empty." It was left when the WebSocketServer was replaced by TelemetryServiceClient.
- Files: `adapters/msfs/SimConnectBridge.Tests/WebSocketServerTests.cs`
- Impact: Minor confusion; clutters test output.
- Fix approach: Delete the file.

**Duplicated Whisper Transcription Logic:**
- Issue: Whisper transcription with confidence scoring is implemented in three places: `orchestrator/orchestrator/whisper_client.py` (sync `WhisperClient` class), `orchestrator/orchestrator/voice.py` (async `VoiceInput.transcribe`), and `web/server.py` (`_transcribe_with_confidence`). Each has its own confidence calculation, retry logic, and error handling with subtle differences.
- Files: `orchestrator/orchestrator/whisper_client.py`, `orchestrator/orchestrator/voice.py` (lines 177-214), `web/server.py` (lines 978-1033)
- Impact: Bug fixes or behavior changes need to be applied in three places. The `WhisperClient` class has retry logic; the web server and voice module do not.
- Fix approach: Consolidate into a single async Whisper client used by both the web server and voice module. The existing `WhisperClient` in `whisper_client.py` is sync-only (uses `httpx.Client`), so it needs an async counterpart.

**Duplicated TTS Voice Settings:**
- Issue: ElevenLabs voice settings (`stability`, `similarity_boost`, `style`) are hardcoded in multiple places with different values. `orchestrator/orchestrator/voice.py` uses `{stability: 0.5, similarity_boost: 0.75, style: 0.3}` while `web/server.py` uses `{stability: 0.75, similarity_boost: 0.80, style: 0.15}` in at least four separate locations (lines 148, 393, 669, 961).
- Files: `orchestrator/orchestrator/voice.py` (line 333), `web/server.py` (lines 148, 393, 669, 961)
- Impact: Inconsistent audio output between CLI and web modes. Changes require updating multiple locations.
- Fix approach: Extract voice settings into a shared config object or the `Settings` class.

**TTS Abstraction Layer Not Integrated:**
- Issue: A clean TTS abstraction exists in `orchestrator/orchestrator/tts/` with `base.py` (Protocol), `elevenlabs.py`, and `kokoro.py`. However, neither the web server (`web/server.py`) nor the CLI voice module (`orchestrator/orchestrator/voice.py`) uses it. Both still directly call ElevenLabs REST/WebSocket APIs with inline httpx code.
- Files: `orchestrator/orchestrator/tts/base.py`, `orchestrator/orchestrator/tts/elevenlabs.py`, `orchestrator/orchestrator/tts/kokoro.py`, `web/server.py`, `orchestrator/orchestrator/voice.py`
- Impact: The Kokoro local TTS backend is not usable from the main application paths. Switching TTS backends requires code changes in multiple files.
- Fix approach: Wire the web server and voice module to use the `TTSClient` protocol, selecting backend via config.

## Security Concerns

**Wildcard CORS on Web Server:**
- Risk: `web/server.py` line 254 sets `allow_origins=["*"]` with `allow_credentials=True`. This allows any origin to make authenticated requests to the MERLIN web server.
- Files: `web/server.py` (lines 252-258)
- Current mitigation: The server is intended for local use only.
- Recommendations: Restrict to `localhost` origins by default. Add a config option for custom origins if remote access is needed.

**No Authentication on WebSocket Endpoints:**
- Risk: The telemetry service (`/ws/ingest`, `/ws/telemetry`), web server (`/ws/chat`, `/ws/telemetry`), and all REST endpoints have zero authentication. Any process on the network can connect, inject telemetry, send chat messages, or consume data.
- Files: `telemetry-service/telemetry/service.py`, `web/server.py`
- Current mitigation: Intended for local/LAN use on a developer machine.
- Recommendations: Add an optional API key or token-based auth for the ingest endpoint to prevent unauthorized adapter impersonation. Consider at minimum a shared secret for the adapter registration handshake.

**No Input Validation on Adapter Registration:**
- Risk: Any WebSocket client can register as an adapter with any `adapter_id` and `sim_name`. A malicious client could overwrite legitimate adapters by reusing their ID (the manager replaces existing connections on re-registration).
- Files: `telemetry-service/telemetry/adapter_manager.py` (lines 66-81)
- Current mitigation: None.
- Recommendations: Validate adapter IDs, require a registration token, or at minimum log warnings when adapter IDs conflict.

**No Rate Limiting on API Endpoints:**
- Risk: The `/api/transcribe` and `/api/tts` endpoints forward to external services (Whisper, ElevenLabs). Without rate limiting, a client could exhaust API quotas or cause denial of service.
- Files: `web/server.py` (lines 324-408)
- Current mitigation: None.
- Recommendations: Add per-client rate limiting, especially for the ElevenLabs TTS endpoint which has usage costs.

## Performance Risks

**Unbounded Conversation History Growth:**
- Problem: `ClaudeClient._conversation` is a list that grows with every message exchange. While `_trim_history()` caps it at `max_history * 2` entries (default 40), each entry can contain large base64 images from screen capture. A single 720p JPEG is ~100KB base64, and every vision-enabled turn appends one.
- Files: `orchestrator/orchestrator/claude_client.py` (lines 300, 406-407, 519-521)
- Cause: No size-based pruning; only count-based. Image content is not stripped from older messages.
- Improvement path: Strip image content from messages older than N turns, or track total content size.

**New httpx Client Per TTS Synthesis in CLI Mode:**
- Problem: `VoiceOutput._synthesize()` creates a new `httpx.AsyncClient` for every TTS call (line 339: `async with httpx.AsyncClient...`). This means a new TCP connection and TLS handshake to ElevenLabs for every sentence.
- Files: `orchestrator/orchestrator/voice.py` (line 339)
- Cause: The web server correctly uses persistent clients (`_get_tts_client()`), but the CLI voice module does not.
- Improvement path: Use a persistent `httpx.AsyncClient` instance in `VoiceOutput`, similar to the web server pattern.

**New httpx Client Per Airport Lookup:**
- Problem: `tools.py` `lookup_airport()` creates a new `httpx.AsyncClient` per call (line 171). When `create_flight_plan()` calls `lookup_airport()` twice (departure + destination), this creates two separate connections.
- Files: `orchestrator/orchestrator/tools.py` (line 171)
- Cause: No connection pooling for external API calls in the tools module.
- Improvement path: Accept or create a shared client.

**Screen Capture Grabs Entire Primary Monitor:**
- Problem: `CaptureManager._grab_frame()` captures the entire primary monitor (`sct.monitors[1]`) and resizes to 720p. If MSFS is on a secondary monitor or windowed, the capture includes irrelevant content.
- Files: `orchestrator/orchestrator/screen_capture.py` (lines 106-108)
- Cause: No MSFS window detection logic.
- Improvement path: Add Win32 window enumeration to find the MSFS window and capture only its region.

**Telemetry Service Holds Lock During Broadcast:**
- Problem: `AdapterManager.update_telemetry()` acquires `self._lock` to update state, then calls `_broadcast_to_consumers()` outside the lock. However, `_broadcast_to_consumers()` iterates the consumer list without any lock, while `add_consumer()` and `remove_consumer()` also access the list without locking. This is a race condition.
- Files: `telemetry-service/telemetry/adapter_manager.py` (lines 103-118, 196-210)
- Cause: Consumer list is mutated without synchronization.
- Improvement path: Protect the consumer list with its own lock, or use `asyncio.Lock` consistently for both adapter and consumer operations.

## Scalability Concerns

**Global Mutable State in Web Server:**
- Issue: `web/server.py` uses module-level global variables for all shared state: `sim_client`, `claude_client`, `context_store`, `phase_detector`, `_sim_connected`, `_bridge_last_seen`, `_bridge_connected`, `_tts_client`, `_whisper_client`, `_TTS_CACHE`. These are mutated via `global` statements in five places.
- Files: `web/server.py` (lines 60-70, 84-101, 109, 168-169, 424)
- Why fragile: This pattern prevents running multiple instances behind a load balancer, makes testing difficult (state leaks between tests), and creates implicit coupling between endpoints.
- Fix approach: Encapsulate shared state in a dataclass or class, pass it via FastAPI dependency injection or `app.state`.

**Single-Adapter Telemetry Service:**
- Issue: `AdapterManager.get_current_state()` returns the most recently updated adapter's state, with no way for consumers to specify which adapter they want. If two sims are connected simultaneously (e.g., MSFS and X-Plane), consumers receive whichever updated last.
- Files: `telemetry-service/telemetry/adapter_manager.py` (lines 156-164)
- Current capacity: Works for single-adapter use.
- Scaling path: Add adapter ID filtering for consumers and update the broadcast to tag telemetry with source adapter.

**No Health Endpoint on Web Server:**
- Issue: The web server at `web/server.py` has `/api/status` but no `/health` or `/readiness` endpoint for orchestration tools (Docker, Kubernetes, load balancers).
- Files: `web/server.py`
- Fix approach: Add `/health` and `/ready` endpoints.

## Missing Infrastructure

**No CI/CD Pipeline:**
- Issue: There is no `.github/workflows/`, no Jenkinsfile, no GitLab CI, no CI configuration of any kind. The 361+ tests are only run manually.
- Impact: Regressions can be merged without detection. No automated linting, testing, or build verification on PRs.
- Fix approach: Add GitHub Actions workflow for: lint (ruff), Python tests (pytest), C# tests (dotnet test), and Docker build verification.

**No Error Tracking or Crash Reporting:**
- Issue: All error handling goes to Python's `logging` module or `Console.WriteLine` in C#. There is no Sentry, Bugsnag, or equivalent integration. Errors in production (Docker) are only visible in container logs.
- Files: All Python and C# source files.
- Fix approach: Add Sentry or a similar service, at minimum for the web server and orchestrator.

**No Structured Logging:**
- Issue: Python components use `logging.basicConfig` with a simple text format. The C# adapter uses `Console.WriteLine` with a custom format. Neither produces JSON-structured logs suitable for log aggregation.
- Files: `orchestrator/orchestrator/main.py` (lines 488-491), `web/server.py` (lines 46-48), `adapters/msfs/SimConnectManager.cs` (lines 231-234)
- Fix approach: Switch to structured JSON logging (e.g., `python-json-logger` or `structlog`). The C# adapter should use `Microsoft.Extensions.Logging`.

**No Web Server Tests:**
- Issue: `web/server.py` is 1,057 lines with complex WebSocket handling, TTS streaming, barge-in interruption, and transcription -- but has zero test coverage. There is no `web/tests/` directory.
- Files: `web/server.py`
- Impact: The most user-facing component is completely untested. Changes to chat flow, TTS streaming, or barge-in logic cannot be verified automatically.
- Fix approach: Add a `web/tests/` directory with FastAPI `TestClient` and `WebSocket` test fixtures. Priority test cases: chat flow, barge-in cancellation, TTS cache hits, transcription fallback.

## Fragile Areas

**Barge-In Cancellation Logic:**
- Files: `web/server.py` (lines 519-635)
- Why fragile: The barge-in system involves task cancellation, event signaling, and WebSocket message ordering across three nested async contexts (`ws_chat`, `_stream_response`, `_tts_websocket_stream`). Race conditions can leave orphaned TTS connections or send messages to already-closed WebSocket clients.
- Safe modification: Always test interrupt scenarios end-to-end. Ensure poison pills are always sent to the TTS queue in the `finally` block.
- Test coverage: Zero automated tests.

**TelemetryClient Reconnection State Machine:**
- Files: `orchestrator/orchestrator/sim_client.py` (lines 246-526)
- Why fragile: The reconnection logic involves three async tasks (_listen_loop, _heartbeat_loop, _reconnect), multiple state transitions, and task lifecycle management. The heartbeat loop breaks out (ending the task) when ping fails, but the listen loop is the one that calls `_reconnect`. If the heartbeat task breaks and the listen loop is still waiting on `async for message`, the connection can enter a zombie state.
- Safe modification: Add integration tests for reconnection scenarios; test state transitions explicitly.
- Test coverage: Unit tests exist for happy path (`orchestrator/tests/test_sim_client.py`), but reconnection edge cases are not well covered.

**SimConnect Message Pump Thread Safety:**
- Files: `adapters/msfs/SimConnectManager.cs` (lines 429-470)
- Why fragile: The message pump runs on a dedicated thread and calls `ReceiveMessage()`, which triggers callbacks on that same thread. The callbacks (`OnRecvSimobjectData`, `OnRecvEvent`) access `CurrentState` under `_lock`, but `StateUpdated?.Invoke(CurrentState)` (line 605) fires outside the lock, potentially delivering a partially-updated state to subscribers. The `TelemetryServiceClient` receives these events and serializes `CurrentState`, which could read mid-mutation values if a high-frequency update arrives during serialization.
- Safe modification: Copy state inside the lock and invoke subscribers with the snapshot.
- Test coverage: Unit tests mock SimConnect; threading issues are not testable this way.

## Dependencies at Risk

**ChromaDB Version Pinning:**
- Risk: `orchestrator/pyproject.toml` specifies `chromadb>=0.5.0` with no upper bound. ChromaDB has had breaking API changes between minor versions (e.g., collection API, embedding function signatures).
- Impact: A `pip install --upgrade` could break the context store.
- Migration plan: Pin to `chromadb>=0.5.0,<0.7.0` or similar range.

**Whisper Server Image:**
- Risk: `docker-compose.yml` uses `fedirz/faster-whisper-server:latest-cpu`. The `:latest` tag means the image can change unpredictably. This is a third-party community image.
- Impact: API changes in the Whisper server image could break transcription without code changes.
- Migration plan: Pin to a specific version tag (e.g., `fedirz/faster-whisper-server:0.4.0-cpu`).

**Telemetry Service Dockerfile Uses Python 3.11, Orchestrator Uses 3.12:**
- Risk: `telemetry-service/Dockerfile` uses `python:3.11-slim` while `orchestrator/Dockerfile` uses `python:3.12-slim`. Both `pyproject.toml` files require `>=3.11`. This version mismatch is not a bug today but can cause confusion and subtle behavior differences.
- Files: `telemetry-service/Dockerfile` (line 1), `orchestrator/Dockerfile` (lines 7, 30)
- Fix approach: Standardize on a single Python version across all Dockerfiles.

## Test Coverage Gaps

**Web Server (1,057 lines, 0 tests):**
- What's not tested: Chat WebSocket flow, telemetry proxy, TTS streaming with WebSocket and REST fallback, barge-in interruption, audio transcription with confidence scoring, TTS phrase caching, sentence splitting logic.
- Files: `web/server.py`
- Risk: Any refactor to the primary user-facing component could silently break functionality.
- Priority: High

**Kokoro TTS Server (0 tests):**
- What's not tested: The entire `services/tts/server.py` has no test suite.
- Files: `services/tts/server.py`
- Risk: Low (new code, not yet in production path).
- Priority: Low

**TTS Abstraction Layer (partial):**
- What's not tested: `orchestrator/orchestrator/tts/elevenlabs.py` and `orchestrator/orchestrator/tts/kokoro.py` -- the new TTS backend implementations.
- Files: `orchestrator/orchestrator/tts/`
- Risk: Medium -- these are new and not yet wired into the main application, but `test_tts_client.py` exists with 20 tests suggesting some coverage.
- Priority: Medium

**Integration Tests Excluded by Default:**
- What's not tested: `orchestrator/pyproject.toml` line 56 sets `addopts = "-m 'not integration'"`. The 67 integration tests in `tests/integration/` are never run unless explicitly requested. With no CI, they may rot silently.
- Files: `tests/integration/`, `orchestrator/pyproject.toml`
- Risk: Integration tests could be broken without anyone noticing.
- Priority: Medium -- addressed once CI is in place.

---

*Concerns audit: 2026-03-26*
