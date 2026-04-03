# Requirements: MERLIN v1.2 — Consolidation & Quality

**Defined:** 2026-03-26
**Core Value:** MERLIN's voice and text responses must be fast, high-quality, and contextually accurate during flight

## v1 Requirements

Requirements for v1.2 release. Each maps to roadmap phases.

### Housekeeping

- [x] **HSKP-01**: Deprecated SimConnect config fields (`simconnect_ws_host`, `simconnect_ws_port`, `simconnect_bridge_url`) and backward-compat alias (`SimConnectClient`) removed from orchestrator
- [x] **HSKP-02**: Race condition in telemetry consumer list fixed with proper asyncio.Lock synchronization
- [x] **HSKP-03**: ChromaDB Docker image pinned to specific version tag (not `:latest`)
- [x] **HSKP-04**: Whisper Docker image pinned to specific version tag (not `:latest-cpu`)
- [x] **HSKP-05**: Python version standardized across all Dockerfiles (single version)
- [x] **HSKP-06**: Empty `WebSocketServerTests.cs` file removed
- [x] **HSKP-07**: `SIMCONNECT_BRIDGE_URL` env var removed from docker-compose.yml

### TTS Integration

- [x] **TTS-01**: Web server uses `TTSClient` protocol instead of inline ElevenLabs httpx calls
- [x] **TTS-02**: CLI voice module uses `TTSClient` protocol instead of inline ElevenLabs httpx calls
- [x] **TTS-03**: TTS protocol extended to support incremental WebSocket streaming (not just complete-text-in/audio-out)
- [x] **TTS-04**: Voice settings (stability, similarity_boost, style) consolidated into single config source used by all consumers
- [x] **TTS-05**: Persistent httpx client used for TTS calls (no per-call client creation in CLI voice module)
- [x] **TTS-06**: `tts_backend`, `tts_local_url`, and `tts_voice_id_local` config fields added to Settings class
- [x] **TTS-07**: Kokoro TTS backend selectable via config without code changes

### Whisper Consolidation

- [x] **WHSP-01**: Single async `WhisperClient` replaces three separate transcription implementations
- [x] **WHSP-02**: Confidence scoring logic unified across all call sites
- [x] **WHSP-03**: Retry logic available in the shared client (currently only in sync `WhisperClient`)
- [x] **WHSP-04**: Web server and voice module both use the shared async Whisper client

### Web Server Refactor

- [x] **WSRV-01**: Module-level global variables replaced with `app.state` + lifespan context manager
- [x] **WSRV-02**: Shared state accessible via FastAPI `Depends()` dependency injection
- [x] **WSRV-03**: Barge-in cancellation flow preserved with identical behavior after refactor
- [ ] **WSRV-04**: All existing functionality verified working after refactor (no regressions)

### Web Server Tests

- [ ] **WTST-01**: Chat WebSocket flow tested (send message, receive streaming response)
- [ ] **WTST-02**: Barge-in interruption tested (new message cancels in-flight response)
- [ ] **WTST-03**: TTS streaming tested (audio chunks delivered via WebSocket)
- [x] **WTST-04**: Transcription endpoint tested (audio upload, confidence scoring)
- [x] **WTST-05**: TTS phrase cache tested (cache hits return pre-generated audio)
- [ ] **WTST-06**: Telemetry WebSocket proxy tested
- [x] **WTST-07**: Status endpoint tested (subsystem health reporting)

### CI/CD Pipeline

- [x] **CICD-01**: GitHub Actions workflow runs ruff lint on Python code
- [x] **CICD-02**: GitHub Actions workflow runs pytest for orchestrator tests
- [x] **CICD-03**: GitHub Actions workflow runs pytest for telemetry-service tests
- [x] **CICD-04**: GitHub Actions workflow runs dotnet test for MSFS adapter
- [x] **CICD-05**: GitHub Actions workflow verifies Docker build succeeds
- [x] **CICD-06**: Path-based filtering triggers only relevant workflows on PR
- [x] **CICD-07**: Web server tests included in CI pipeline

## v2 Requirements

Deferred to future release. Tracked but not in current roadmap.

### Observability

- **OBSV-01**: Structured JSON logging across all Python components
- **OBSV-02**: Sentry or equivalent error tracking integration
- **OBSV-03**: Health endpoints (`/health`, `/ready`) on web server

### STT Abstraction

- **STT-01**: Whisper client abstracted behind protocol (like TTS) for alternative STT backends

### Security Hardening

- **SEC-01**: CORS restricted to localhost origins by default
- **SEC-02**: Optional API key authentication on WebSocket endpoints
- **SEC-03**: Rate limiting on `/api/transcribe` and `/api/tts` endpoints

## Out of Scope

| Feature | Reason |
|---------|--------|
| New sim adapters (X-Plane, DCS) | Future milestone; architecture already supports it |
| STT abstraction layer | Premature — only one STT backend exists; defer until second backend needed |
| Structured logging migration | Touches every file; defer to follow-up milestone after CI is established |
| Speech-to-speech architecture | Wrong interaction model for cockpit comms; current STT→LLM→TTS is correct |
| Screen capture window targeting | Low priority, works well enough for current use |
| Kokoro TTS server tests | Not in production path yet; test when it enters production |
| Integration test suite revival | Review after CI exists; may need fixture updates |

## Traceability

Which phases cover which requirements. Updated during roadmap creation.

| Requirement | Phase | Status |
|-------------|-------|--------|
| HSKP-01 | Phase 1 | Complete |
| HSKP-02 | Phase 1 | Complete |
| HSKP-03 | Phase 1 | Complete |
| HSKP-04 | Phase 1 | Complete |
| HSKP-05 | Phase 1 | Complete |
| HSKP-06 | Phase 1 | Complete |
| HSKP-07 | Phase 1 | Complete |
| TTS-01 | Phase 2 | Complete |
| TTS-02 | Phase 2 | Complete |
| TTS-03 | Phase 2 | Complete |
| TTS-04 | Phase 2 | Complete |
| TTS-05 | Phase 2 | Complete |
| TTS-06 | Phase 2 | Complete |
| TTS-07 | Phase 2 | Complete |
| WHSP-01 | Phase 3 | Complete |
| WHSP-02 | Phase 3 | Complete |
| WHSP-03 | Phase 3 | Complete |
| WHSP-04 | Phase 3 | Complete |
| WSRV-01 | Phase 4 | Complete |
| WSRV-02 | Phase 4 | Complete |
| WSRV-03 | Phase 4 | Complete |
| WSRV-04 | Phase 4 | Pending |
| WTST-01 | Phase 5 | Pending |
| WTST-02 | Phase 5 | Pending |
| WTST-03 | Phase 5 | Pending |
| WTST-04 | Phase 5 | Complete |
| WTST-05 | Phase 5 | Complete |
| WTST-06 | Phase 5 | Pending |
| WTST-07 | Phase 5 | Complete |
| CICD-01 | Phase 6 | Complete |
| CICD-02 | Phase 6 | Complete |
| CICD-03 | Phase 6 | Complete |
| CICD-04 | Phase 6 | Complete |
| CICD-05 | Phase 6 | Complete |
| CICD-06 | Phase 6 | Complete |
| CICD-07 | Phase 6 | Complete |

**Coverage:**
- v1 requirements: 36 total
- Mapped to phases: 36
- Unmapped: 0 ✓

---
*Requirements defined: 2026-03-26*
*Last updated: 2026-03-26 after initial definition*
