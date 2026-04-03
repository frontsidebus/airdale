# Project Research Summary

**Project:** MERLIN v1.2 Consolidation
**Domain:** Codebase quality milestone for a real-time voice AI co-pilot (FastAPI + WebSocket + streaming TTS/STT)
**Researched:** 2026-03-26
**Confidence:** HIGH

## Executive Summary

MERLIN v1.2 is a consolidation milestone, not a feature milestone. The existing architecture -- event-driven microservices with pluggable sim adapters, cascading STT/LLM/TTS voice pipeline, and WebSocket IPC -- is sound and does not need restructuring. The work targets three areas of technical debt: (1) duplicated TTS and STT client code across the web server and CLI, (2) untestable global state in the 1,057-line web server, and (3) absence of CI/CD despite 361+ existing tests. A TTS abstraction layer already exists but is not wired into any consumer. Three separate Whisper transcription implementations have diverged with different confidence scoring and error handling.

The recommended approach follows a strict dependency chain: fix bugs and clean up config first (establishing a known-good baseline), then wire in the existing TTS and Whisper abstractions, then refactor the web server for testability, then add test coverage, and finally stand up CI/CD. This ordering is not arbitrary -- each phase depends on the previous one being stable. Attempting to test the web server before refactoring it wastes effort (tests would need rewriting). Standing up CI before tests exist generates noise. All four research dimensions converge on this sequencing.

The highest risk is the web server refactor, specifically the barge-in cancellation system. It coordinates task cancellation, event signaling, and WebSocket message ordering across three nested async contexts, all using module-level globals and nonlocal closures, with zero test coverage. Refactoring this without characterization tests first will produce subtle, timing-dependent regressions. The second major risk is the TTS abstraction: the existing protocol does not model ElevenLabs' incremental WebSocket streaming pattern used by the web server, and naive integration will add 200-500ms latency per sentence. The protocol must be extended before wiring it in.

## Key Findings

### Recommended Stack

No new production dependencies are required. The consolidation uses existing libraries and built-in FastAPI patterns. See [STACK.md](STACK.md) for full details.

**Core technologies:**
- **FastAPI `app.state` + `Depends()`**: Replace module-level globals in web server -- native pattern, zero new deps, well-documented
- **`httpx-ws` (>= 0.6.2)**: Async WebSocket testing -- required because barge-in tests need a real async client, not Starlette's sync TestClient
- **GitHub Actions with `dorny/paths-filter` v3**: CI/CD with monorepo path-based job triggers -- avoids running Python CI on C# changes and vice versa
- **Existing `TTSClient` protocol + factory**: Already built with ElevenLabs and Kokoro backends -- integration only, no design work needed

**Rejected alternatives:** `svcs` and `dependency-injector` for DI (overkill for 5 singletons), `TestClient.websocket_connect()` for WS testing (sync-only, cannot test async cancellation), monolithic CI workflow (separate Python/C#/Docker workflows are cleaner).

### Expected Features

See [FEATURES.md](FEATURES.md) for the full feature landscape and dependency graph.

**Must have (table stakes):**
- TTS abstraction wired into all consumers (existing protocol, needs integration)
- Unified async Whisper client (three divergent implementations consolidated)
- Consistent TTS voice settings from config (currently hardcoded in 3+ places with different values)
- Web server DI refactor (module-level globals prevent testing)
- Web server test coverage (1,057-line user-facing component with zero tests)
- CI/CD pipeline (361+ tests only run manually)
- Deprecated config cleanup (dead SimConnect fields confuse developers)
- Dependency version pinning (unpinned chromadb and :latest Docker tags)
- Telemetry consumer list race condition fix (asyncio.Lock needed)

**Should have (differentiators):**
- Coverage threshold enforcement (75% floor in CI)
- Health/readiness endpoints on web server
- Pre-commit hooks (ruff + pytest)
- CORS restriction to localhost
- Integration test schedule (nightly)

**Defer (post-v1.2):**
- New sim adapters (X-Plane, DCS)
- Structured logging migration
- Multi-backend STT abstraction
- Screen capture window targeting
- Speech-to-speech architecture

### Architecture Approach

The consolidation does not alter component boundaries or data flows. It changes HOW the web server and CLI access TTS/STT services -- through shared abstractions instead of inline HTTP calls -- and makes the web server testable by moving state from module-level globals to an `AppState` dataclass on `app.state`. See [ARCHITECTURE.md](ARCHITECTURE.md) for component details and data flow diagrams.

**Major components affected:**
1. **TTS Client Layer** -- Wire existing Protocol + factory into web server and CLI voice module; extend protocol for incremental WebSocket streaming
2. **Whisper/STT Client** -- Create single async client replacing three divergent implementations; preserve retry logic and webm fallback
3. **Web Server State** -- Move 10+ module-level globals into `AppState` dataclass; initialize in lifespan; access via `request.app.state`
4. **Config** -- Remove deprecated SimConnect fields; add TTS backend selection and voice settings
5. **Telemetry Service** -- Add asyncio.Lock to consumer list mutations (localized fix, no API changes)
6. **CI/CD** -- Three GitHub Actions workflows: python-ci, dotnet-ci, docker-build

### Critical Pitfalls

See [PITFALLS.md](PITFALLS.md) for the full pitfall catalog with detection and prevention strategies.

1. **Barge-in breakage during web server refactor** -- The cancellation system uses nonlocal closures over globals with zero test coverage. Write characterization tests before refactoring; extract the barge-in state machine into its own class as a separate step.
2. **TTS abstraction breaks streaming latency** -- The existing protocol does not model incremental WebSocket streaming. Extend the protocol to include a `stream_session()` method before wiring it in. Benchmark time-to-first-audio before and after.
3. **WebSocket tests hang or flake** -- Use `httpx-ws` for async tests, `pytest-timeout` for safety, and structure tests as short conversations. Do not attempt to test the full infinite receive loop.
4. **Whisper consolidation changes transcription behavior** -- Three implementations have different confidence scoring. Write comparison tests with audio fixtures before consolidating; consolidate incrementally (web server first, then CLI).
5. **Mixing refactoring and bug fixes in the same commit** -- Fix known bugs in Phase 1, refactor in later phases, never both in the same commit. This enables clean `git bisect` when regressions appear.

## Implications for Roadmap

Based on combined research, the consolidation has a clear six-phase dependency chain. All four research files converge on this ordering.

### Phase 1: Housekeeping
**Rationale:** Independent, low-risk changes that establish a clean baseline. Must come first because TTS integration depends on config cleanup, and mixing bug fixes with refactoring is an explicit anti-pattern.
**Delivers:** Clean config, pinned dependencies, race condition fix, known-good baseline for regression detection.
**Addresses:** Deprecated config cleanup, dependency version pinning, telemetry race condition fix.
**Avoids:** Pitfall 8 (mixing refactoring and bug fixes), Pitfall 11 (removing config without updating consumers), Pitfall 10 (Python version standardization breaking deps).

### Phase 2: TTS Integration
**Rationale:** The TTS abstraction already exists -- this is wiring, not design. Depends on config cleanup (needs new TTS backend fields). Must come before web server refactor so the refactor moves the abstracted client into `app.state`, not the raw httpx globals.
**Delivers:** Single TTS code path across web and CLI, consistent voice settings from config, phrase cache using TTSClient.
**Addresses:** TTS abstraction integration, consistent voice settings.
**Avoids:** Pitfall 2 (streaming latency regression -- extend protocol first), Pitfall 9 (TTS cache invalidation after settings change).

### Phase 3: Whisper Consolidation
**Rationale:** Independent of TTS (different files) but follows the same Protocol + factory pattern. Could theoretically run in parallel with Phase 2, but serial execution is safer for a single developer.
**Delivers:** Single async WhisperClient used by all consumers, centralized retry logic and webm fallback.
**Addresses:** Unified Whisper client.
**Avoids:** Pitfall 4 (transcription behavior changes -- comparison tests first, incremental rollout).

### Phase 4: Web Server Refactor
**Rationale:** Depends on TTS and Whisper being abstracted so the refactor moves clean clients into `AppState`, not inline httpx calls. This is the highest-risk phase.
**Delivers:** Testable web server with all state on `app.state`, no module-level globals.
**Addresses:** Web server DI refactor, health/readiness endpoints, CORS restriction.
**Avoids:** Pitfall 1 (barge-in breakage -- characterization tests first, extract state machine separately), Pitfall 5 (initialization order -- keep all init in lifespan).

### Phase 5: Web Server Tests
**Rationale:** Depends on refactored state (testing the old global-state shape is wasted effort). Must come before CI so the pipeline has meaningful tests to run.
**Delivers:** Test coverage for critical paths (chat flow, barge-in, TTS streaming, transcription), WebSocket test infrastructure.
**Addresses:** Web server test coverage, TTS backend integration tests.
**Avoids:** Pitfall 3 (WebSocket test hangs -- use httpx-ws, pytest-timeout, short conversations).

### Phase 6: CI/CD Pipeline
**Rationale:** CI needs stable, passing tests to be meaningful. Running CI against a codebase mid-refactor generates noise.
**Delivers:** Automated lint, test, and build verification on every PR. Coverage threshold enforcement. Docker build verification on main.
**Addresses:** CI/CD pipeline, coverage thresholds, pre-commit hooks, integration test schedule.
**Avoids:** Pitfall 6 (running everything on every change -- path-based filtering from day one).

### Phase Ordering Rationale

- Phases 1-3 (housekeeping, TTS, Whisper) are foundation work that reduces duplication and establishes single sources of truth.
- Phase 4 (web server refactor) is the highest-risk change and benefits from all preceding work being stable.
- Phase 5 (tests) depends on Phase 4 by definition -- you cannot meaningfully test a structure you are about to change.
- Phase 6 (CI) is the capstone that automates quality enforcement after the quality bar has been established.
- Bug fixes are isolated in Phase 1 to avoid contaminating refactoring phases.

### Research Flags

Phases likely needing deeper research during planning:
- **Phase 2 (TTS Integration):** The TTSClient protocol must be extended to support incremental WebSocket streaming before wiring into the web server. This requires design work to define the `stream_session()` interface.
- **Phase 4 (Web Server Refactor):** Barge-in cancellation system is complex and undocumented. Characterization tests need to be designed before the refactor begins.

Phases with standard patterns (skip research-phase):
- **Phase 1 (Housekeeping):** Config field removal, dependency pinning, asyncio.Lock -- all straightforward.
- **Phase 3 (Whisper Consolidation):** Follows the Protocol + factory pattern already established by TTS.
- **Phase 5 (Web Server Tests):** httpx-ws testing patterns are documented. Test design follows from the refactored code shape.
- **Phase 6 (CI/CD):** GitHub Actions for Python/C# monorepos is well-documented with established patterns.

## Confidence Assessment

| Area | Confidence | Notes |
|------|------------|-------|
| Stack | HIGH | No new production deps. All recommendations are built-in FastAPI patterns or established test libraries. |
| Features | HIGH | Feature list derived from codebase analysis and PROJECT.md. Dependency chain verified by reading source. |
| Architecture | HIGH | All findings verified by reading actual source code. Component boundaries confirmed. |
| Pitfalls | HIGH | Pitfalls from direct code analysis (barge-in closures, TTS protocol gaps, Whisper divergence) and community docs. |

**Overall confidence:** HIGH -- This is a consolidation milestone for an existing codebase, not greenfield development. All research is grounded in direct source code analysis.

### Gaps to Address

- **TTS WebSocket streaming protocol design:** The existing `TTSClient` protocol needs a `stream_session()` method for incremental text input. The exact interface must be designed during Phase 2 planning.
- **Whisper behavior parity verification:** The three Whisper implementations must be compared with identical audio fixtures before consolidation begins. No comparison data exists yet.
- **SimConnect DLL availability in CI:** C# tests that require SimConnect must be categorized and excluded from CI. The exact test categorization has not been audited.
- **Docker image longevity:** The `faster-whisper-server` image is maintained by an individual. Long-term strategy (build own image vs. continue using community image) is deferred but should be revisited.

## Sources

### Primary (HIGH confidence)
- Direct codebase analysis: `web/server.py`, `orchestrator/orchestrator/tts/`, `orchestrator/orchestrator/voice.py`, `orchestrator/orchestrator/whisper_client.py`, `orchestrator/orchestrator/config.py`, `telemetry-service/telemetry/adapter_manager.py`
- [FastAPI Dependencies Documentation](https://fastapi.tiangolo.com/tutorial/dependencies/)
- [FastAPI Testing WebSockets](https://fastapi.tiangolo.com/advanced/testing-websockets/)
- [httpx-ws GitHub](https://github.com/frankie567/httpx-ws)

### Secondary (MEDIUM confidence)
- [Production-Ready FastAPI Project Structure 2026](https://dev.to/thesius_code_7a136ae718b7/production-ready-fastapi-project-structure-2026-guide-b1g)
- [GitHub Actions Monorepo CI/CD 2026](https://generalreasoning.com/blog/2025/03/22/github-actions-vanilla-monorepo.html)
- [dorny/paths-filter GitHub](https://github.com/dorny/paths-filter)
- [The voice AI stack for building agents in 2026](https://www.assemblyai.com/blog/the-voice-ai-stack-for-building-agents)

### Tertiary (LOW confidence)
- [FastAPI WebSocket test hang issue #2637](https://github.com/fastapi/fastapi/issues/2637) -- confirms TestClient limitations but workarounds may vary by version

---
*Research completed: 2026-03-26*
*Ready for roadmap: yes*
