# Roadmap: MERLIN v1.2 -- Consolidation & Quality

## Overview

MERLIN v1.2 consolidates technical debt accumulated during rapid v1.0/v1.1 development. The work follows a strict dependency chain: clean up config and fix bugs (establishing a known-good baseline), wire in existing TTS and Whisper abstractions, refactor the web server for testability, add test coverage for the primary user-facing component, and stand up CI/CD to prevent future regressions. Each phase depends on the previous one being stable -- the ordering is not arbitrary but driven by code dependencies.

## Phases

**Phase Numbering:**
- Integer phases (1, 2, 3): Planned milestone work
- Decimal phases (2.1, 2.2): Urgent insertions (marked with INSERTED)

Decimal phases appear between their surrounding integers in numeric order.

- [ ] **Phase 1: Housekeeping** - Independent bug fixes, config cleanup, and dependency pinning to establish a clean baseline
- [ ] **Phase 2: TTS Integration** - Wire existing TTS abstraction into all consumers with streaming support and unified config
- [ ] **Phase 3: Whisper Consolidation** - Replace three divergent transcription implementations with single async client
- [ ] **Phase 4: Web Server Refactor** - Replace module-level globals with proper DI to make the web server testable
- [ ] **Phase 5: Web Server Tests** - Add test coverage for all critical web server paths
- [ ] **Phase 6: CI/CD Pipeline** - Automate lint, test, build, and Docker verification on every PR

## Phase Details

### Phase 1: Housekeeping
**Goal**: Codebase has no known bugs, no deprecated config fields, and all Docker images use pinned versions -- establishing a clean, regression-detectable baseline
**Depends on**: Nothing (first phase)
**Requirements**: HSKP-01, HSKP-02, HSKP-03, HSKP-04, HSKP-05, HSKP-06, HSKP-07
**Success Criteria** (what must be TRUE):
  1. Orchestrator starts without any reference to `simconnect_ws_host`, `simconnect_ws_port`, `simconnect_bridge_url`, or `SimConnectClient` anywhere in the Python codebase
  2. Telemetry service handles concurrent consumer connect/disconnect without errors under asyncio load
  3. `docker compose build` succeeds with all images using pinned version tags and a single Python version across Dockerfiles
  4. No dead test files or unused environment variables remain in the repo
**Plans**: 3 plans
Plans:
- [x] 01-01-PLAN.md — Remove deprecated SimConnect config fields, alias, and references
- [x] 01-02-PLAN.md — Pin Docker images and standardize Python version
- [x] 01-03-PLAN.md — Fix telemetry consumer race condition and delete empty test file

### Phase 2: TTS Integration
**Goal**: All TTS consumers (web server and CLI voice module) use the TTSClient protocol with persistent connections, consistent voice settings from config, and streaming support
**Depends on**: Phase 1
**Requirements**: TTS-01, TTS-02, TTS-03, TTS-04, TTS-05, TTS-06, TTS-07
**Success Criteria** (what must be TRUE):
  1. Web server produces TTS audio through TTSClient protocol -- no inline httpx calls to ElevenLabs remain in `web/server.py`
  2. CLI voice module produces TTS audio through TTSClient protocol -- no inline httpx calls remain in `orchestrator/orchestrator/voice.py`
  3. Changing `tts_backend` in `.env` from `elevenlabs` to `kokoro` switches the TTS engine without code changes
  4. Voice settings (stability, similarity_boost, style) are defined once in config and used consistently by all consumers
  5. Web server TTS streaming latency (time-to-first-audio) does not regress compared to current inline implementation
**Plans**: 3 plans
Plans:
- [x] 02-01-PLAN.md — Config fields, protocol aclose, and backend refactor (persistent client, voice settings)
- [x] 02-02-PLAN.md — Wire CLI voice module and web server to use TTSClient for REST TTS
- [x] 02-03-PLAN.md — Add WebSocket streaming to protocol and wire into web server

### Phase 3: Whisper Consolidation
**Goal**: A single async WhisperClient with unified confidence scoring and retry logic replaces all three transcription implementations
**Depends on**: Phase 2
**Requirements**: WHSP-01, WHSP-02, WHSP-03, WHSP-04
**Success Criteria** (what must be TRUE):
  1. Only one Whisper transcription implementation exists in the codebase -- `grep` for transcription calls finds a single shared client
  2. Web server `/api/transcribe` endpoint and CLI voice module both use the shared async WhisperClient
  3. Confidence scoring produces identical results for the same audio input regardless of call site
  4. Failed Whisper requests are retried with backoff (existing retry logic preserved in the unified client)
**Plans**: 2 plans
Plans:
- [x] 03-01-PLAN.md — Rewrite WhisperClient as async with persistent httpx, confidence scoring, and retry
- [x] 03-02-PLAN.md — Wire WhisperClient into consumers, remove inline code, upgrade model to large-v3-turbo

### Phase 4: Web Server Refactor
**Goal**: Web server state lives in `app.state` with FastAPI dependency injection, making every component independently testable while preserving identical runtime behavior
**Depends on**: Phase 3
**Requirements**: WSRV-01, WSRV-02, WSRV-03, WSRV-04
**Success Criteria** (what must be TRUE):
  1. `web/server.py` has zero module-level mutable state -- all shared state lives on `app.state` initialized in a lifespan context manager
  2. Route handlers access shared state through `Depends()` callables, not global variable references
  3. Barge-in interruption works identically: sending a new message while MERLIN is responding cancels the in-flight response and starts the new one
  4. All existing web UI functionality (chat, telemetry display, TTS playback, transcription) works without regressions after refactor
**Plans**: 2 plans
Plans:
- [x] 04-01-PLAN.md — Define AppState dataclass, refactor lifespan, wire all handlers with Depends(get_app_state)
- [ ] 04-02-PLAN.md — Smoke test and human verification of full web UI functionality
**UI hint**: yes

### Phase 5: Web Server Tests
**Goal**: Critical web server paths have automated test coverage, providing a safety net for future changes and a meaningful test suite for CI
**Depends on**: Phase 4
**Requirements**: WTST-01, WTST-02, WTST-03, WTST-04, WTST-05, WTST-06, WTST-07
**Success Criteria** (what must be TRUE):
  1. Chat WebSocket round-trip is tested: send a user message, receive a streaming AI response
  2. Barge-in cancellation is tested: a second message during an in-flight response cancels the first
  3. TTS streaming, transcription, phrase cache, telemetry proxy, and status endpoint each have at least one passing test
  4. All web server tests pass in isolation without running services (mocked dependencies)
  5. Test suite runs in under 30 seconds
**Plans**: 2 plans
Plans:
- [x] 05-01-PLAN.md — Test infrastructure (conftest, pytest config) and REST endpoint tests (status, transcribe, TTS cache)
- [ ] 05-02-PLAN.md — WebSocket tests (chat round-trip, barge-in, TTS streaming, telemetry proxy)

### Phase 6: CI/CD Pipeline
**Goal**: Every PR automatically runs lint, tests, and Docker build verification -- regressions are caught before merge, not during flight
**Depends on**: Phase 5
**Requirements**: CICD-01, CICD-02, CICD-03, CICD-04, CICD-05, CICD-06, CICD-07
**Success Criteria** (what must be TRUE):
  1. A PR touching Python code triggers ruff lint and pytest for orchestrator, telemetry-service, and web server tests
  2. A PR touching C# code triggers dotnet test for the MSFS adapter
  3. A PR touching Dockerfiles triggers a Docker build verification step
  4. Path-based filtering prevents C# CI from running on Python-only changes and vice versa
  5. A failing test or lint error blocks PR merge
**Plans**: 2 plans
Plans:
- [x] 06-01-PLAN.md — Python CI workflow (ruff lint + pytest for orchestrator, telemetry-service, web + integration tests)
- [x] 06-02-PLAN.md — .NET CI workflow (dotnet test for MSFS adapter) and Docker CI workflow (compose build verification)

## Progress

**Execution Order:**
Phases execute in numeric order: 1 -> 2 -> 3 -> 4 -> 5 -> 6

| Phase | Plans Complete | Status | Completed |
|-------|----------------|--------|-----------|
| 1. Housekeeping | 3/3 | Complete | - |
| 2. TTS Integration | 3/3 | Complete | - |
| 3. Whisper Consolidation | 0/2 | Planned | - |
| 4. Web Server Refactor | 0/2 | Planned | - |
| 5. Web Server Tests | 1/2 | In Progress|  |
| 6. CI/CD Pipeline | 0/2 | Not started | - |

---

# v1.3 Roadmap: Agent Copilot Control

## Overview

v1.3 adds bidirectional sim control — MERLIN can now execute aircraft commands (flaps, gear, autopilot, radios, throttle, etc.) via voice or text. The foundation is built: SimConnect write path through the adapter, command routing through the telemetry service, and a Claude tool that translates natural language intent to SimConnect events. Future phases will add PID-based automated maneuvers, authority levels, and vision-based cockpit reading.

## Phases

- [x] **Phase 1: Discrete Command Control** — SimConnect event mapping, command protocol, bidirectional routing, Claude tool (COMPLETE — `feat/agent-copilot-control` branch)
- [ ] **Phase 2: Authority & Safety Layer** — Configurable authority levels (advisory/assisted/full), pilot override detection, watchdog timer, phase-aware command gating
- [ ] **Phase 3: Automated Maneuvers** — PID control loops for takeoff/landing/go-around, MCP Task pattern for long-running maneuvers, server-side control at 20Hz
- [ ] **Phase 4: Vision Cockpit Reading** — DXcam screen capture upgrade, Claude vision for instrument reading, third-party aircraft gauge interpretation

## Phase 1 Details (Complete)

**Goal**: MERLIN can execute discrete aircraft control commands via natural language
**Branch**: `feat/agent-copilot-control`
**Files modified**: 10 files across adapter (C#), telemetry service (Python), orchestrator (Python)

**What was built:**
1. Command protocol: `ConsumerCommand` → `ServiceCommand` → `AdapterCommandAck` → `ServiceCommandAck`
2. Telemetry service routing: bidirectional command forwarding with ack tracking
3. MSFS adapter: 30+ SimConnect events registered, `ExecuteCommand()` via `TransmitClientEvent`
4. Orchestrator: `send_command()` with Future-based ack, `set_aircraft_control` Claude tool
5. Command translation: `_resolve_command()` maps human-friendly params to SimConnect events

**Supported systems**: flaps, gear, autopilot, throttle, radio, barometer, trim, parking brake, spoilers, mixture, propeller
